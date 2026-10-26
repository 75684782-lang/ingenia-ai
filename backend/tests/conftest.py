from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.connectors.base import ConnectorError
from app.core.config import Settings
from app.main import create_app

TOKEN = "test-token"
HEADERS = {"X-Ingenia-Token": TOKEN}


class FakeOllama:
    def __init__(self, script: list[dict] | None = None) -> None:
        self.script = list(script or [])
        self.calls = 0

    async def is_available(self) -> bool:
        return True

    async def list_models(self) -> list[dict]:
        return [
            {
                "name": "qwen-test:1.5b",
                "size": 1,
                "parameter_size": "1.5B",
                "capabilities": ["completion", "tools"],
                "supports_tools": True,
            }
        ]

    async def chat_stream(self, model, messages, tools=None, temperature=0.2):
        index = self.calls
        self.calls += 1
        reply = self.script[index] if index < len(self.script) else {
            "content": "Respuesta simulada.",
            "tool_calls": [],
        }
        message: dict = {"role": "assistant", "content": reply.get("content", "")}
        if reply.get("tool_calls"):
            message["tool_calls"] = reply["tool_calls"]
        yield {"message": message, "done": False}
        yield {"message": {"role": "assistant", "content": ""}, "done": True}

    async def pull_model_stream(self, model: str):
        yield {"status": "pulling manifest"}
        yield {"status": "downloading", "total": 1000, "completed": 500}
        yield {"status": "success"}


class FakeConnector:
    mode = "real"

    def __init__(self, result: dict | None = None, fail: bool = False) -> None:
        self.result = result
        self.fail = fail
        self.calls: list[tuple[str, dict, str]] = []

    async def status(self) -> dict:
        return {
            "connected": True,
            "mode": "real",
            "drawing": {"name": "prueba.dwg"},
        }

    async def call(self, tool: str, args: dict, request_id: str) -> dict:
        self.calls.append((tool, args, request_id))
        if self.fail:
            raise ConnectorError("El bridge no responde.")
        if self.result is not None:
            return self.result
        return {
            "ok": True,
            "mode": "real",
            "tool": tool,
            "request_id": request_id,
            "data": {"echo": args},
        }


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        auth_token=TOKEN,
        database_path=str(tmp_path / "test.db"),
        ollama_model="qwen-test:1.5b",
        civil3d_fallback_to_mock=False,
        rate_limit_per_minute=100000,
    )


@pytest.fixture
def app_factory(settings):
    created: list[TestClient] = []

    def make(*, script: list[dict] | None = None, connector=None):
        app = create_app(settings)
        fake_ollama = FakeOllama(script)
        fake_connector = connector or FakeConnector()
        app.state.ollama = fake_ollama
        app.state.chat.ollama = fake_ollama
        app.state.connector = fake_connector
        app.state.executor.connector = fake_connector
        app.state.chat.connector = fake_connector
        client = TestClient(app)
        client.__enter__()
        created.append(client)
        return SimpleNamespace(
            app=app,
            client=client,
            ollama=fake_ollama,
            connector=fake_connector,
        )

    yield make
    for client in created:
        client.__exit__(None, None, None)


def parse_sse(text: str) -> list[dict]:
    import json

    events: list[dict] = []
    for block in text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload:
                    events.append(json.loads(payload))
    return events


def tool_call(name: str, args: dict) -> dict:
    return {"function": {"name": name, "arguments": args}}


def mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)
