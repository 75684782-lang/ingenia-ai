from __future__ import annotations

import httpx
import pytest

from app.services.ollama_client import (
    OllamaClient,
    OllamaUnavailable,
    extract_tool_calls,
)
from .conftest import mock_transport


@pytest.mark.asyncio
async def test_list_models_maps_capabilities():
    def handler(request: httpx.Request):
        assert request.url.path == "/api/tags"
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "qwen2.5-coder:1.5b",
                        "size": 986_000_000,
                        "details": {"parameter_size": "1.5B"},
                        "capabilities": ["completion", "tools"],
                    },
                    {
                        "name": "gemma3:4b",
                        "size": 3_300_000_000,
                        "details": {"parameter_size": "4.3B"},
                        "capabilities": ["completion", "vision"],
                    },
                ]
            },
        )

    client = OllamaClient("http://ollama", transport=mock_transport(handler))
    models = await client.list_models()
    assert models[0]["name"] == "qwen2.5-coder:1.5b"
    assert models[0]["supports_tools"] is True
    assert models[1]["supports_tools"] is False


@pytest.mark.asyncio
async def test_ollama_unavailable():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("sin conexión", request=request)

    client = OllamaClient("http://ollama", transport=mock_transport(handler))
    assert await client.is_available() is False
    with pytest.raises(OllamaUnavailable):
        await client.list_models()


@pytest.mark.asyncio
async def test_chat_stream_parses_ndjson():
    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            text=(
                '{"message":{"role":"assistant","content":"Hola "},"done":false}\n'
                '{"message":{"role":"assistant","content":"mundo"},"done":false}\n'
                '{"message":{"role":"assistant","content":""},"done":true}\n'
            ),
        )

    client = OllamaClient("http://ollama", transport=mock_transport(handler))
    chunks = [chunk async for chunk in client.chat_stream("m", [{"role": "user", "content": "x"}])]
    text = "".join(c["message"]["content"] for c in chunks)
    assert text == "Hola mundo"


def test_extract_tool_calls_accepts_string_arguments():
    message = {
        "tool_calls": [
            {
                "function": {
                    "name": "create_surface",
                    "arguments": '{"name": "Terreno"}',
                }
            }
        ]
    }
    calls = extract_tool_calls(message)
    assert calls[0]["name"] == "create_surface"
    assert calls[0]["args"] == {"name": "Terreno"}
