from __future__ import annotations

import sqlite3
import threading

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.operation_store import OperationStore


def _account_app(tmp_path) -> TestClient:
    settings = Settings(
        _env_file=None,
        auth_token="",
        allow_remote=True,
        cookie_secure=True,
        accounts_enabled=True,
        use_agents=True,
        database_path=str(tmp_path / "accounts.db"),
        rate_limit_per_minute=1000,
    )
    return TestClient(create_app(settings), base_url="https://testserver")


def _register(client: TestClient, email: str) -> dict:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "correct horse battery", "name": email},
    )
    assert response.status_code == 200
    return response.json()["user"]


def test_account_routes_require_session_and_pair_agent(tmp_path):
    with _account_app(tmp_path) as client:
        assert client.get("/api/config").status_code == 401
        user = _register(client, "first@example.com")

        code_response = client.post("/api/agents/pair-code")
        assert code_response.status_code == 200
        code = code_response.json()["code"]

        with client.websocket_connect("/ws/agent") as socket:
            socket.send_json({"type": "pair", "code": code, "name": "PC de prueba"})
            paired = socket.receive_json()
            assert paired["type"] == "paired"
            assert paired["token"].startswith("iga_")
            agent_id = paired["agent_id"]

            agents = client.get("/api/agents").json()["agents"]
            assert agents[0]["id"] == agent_id
            assert agents[0]["online"] is True

        assert client.get("/api/agents").json()["agents"][0]["online"] is False
        assert user["id"]


def test_pair_code_is_single_use(tmp_path):
    with _account_app(tmp_path) as client:
        _register(client, "pair@example.com")
        code = client.post("/api/agents/pair-code").json()["code"]
        with client.websocket_connect("/ws/agent") as socket:
            socket.send_json({"type": "pair", "code": code})
            assert socket.receive_json()["type"] == "paired"
        with client.websocket_connect("/ws/agent") as socket:
            socket.send_json({"type": "pair", "code": code})
            assert socket.receive_json()["type"] == "error"


def test_web_requests_are_routed_to_the_paired_pc(tmp_path):
    with _account_app(tmp_path) as client:
        _register(client, "routing@example.com")
        code = client.post("/api/agents/pair-code").json()["code"]
        with client.websocket_connect("/ws/agent") as socket:
            socket.send_json({"type": "pair", "code": code})
            assert socket.receive_json()["type"] == "paired"

            ollama_result = []
            ollama_request = threading.Thread(
                target=lambda: ollama_result.append(client.get("/api/ollama/status"))
            )
            ollama_request.start()
            message = socket.receive_json()
            assert message["method"] == "ollama.status"
            socket.send_json(
                {
                    "type": "response",
                    "id": message["id"],
                    "ok": True,
                    "result": {"available": True},
                }
            )
            ollama_request.join(timeout=10)
            assert not ollama_request.is_alive()
            assert ollama_result[0].json()["available"] is True

            civil_result = []
            civil_request = threading.Thread(
                target=lambda: civil_result.append(client.get("/api/civil3d/status"))
            )
            civil_request.start()
            message = socket.receive_json()
            assert message["method"] == "civil3d.status"
            socket.send_json(
                {
                    "type": "response",
                    "id": message["id"],
                    "ok": True,
                    "result": {
                        "connected": True,
                        "mode": "real",
                        "drawing": {"name": "proyecto.dwg"},
                    },
                }
            )
            civil_request.join(timeout=10)
            assert not civil_request.is_alive()
            assert civil_result[0].json()["connected"] is True

            chat_result = []
            chat_request = threading.Thread(
                target=lambda: chat_result.append(
                    client.post("/api/chat", json={"message": "Saluda"})
                )
            )
            chat_request.start()
            message = socket.receive_json()
            assert message["method"] == "ollama.chat"
            socket.send_json(
                {
                    "type": "chunk",
                    "id": message["id"],
                    "data": {
                        "message": {"role": "assistant", "content": "Hola desde Ollama"},
                        "done": True,
                    },
                }
            )
            socket.send_json({"type": "end", "id": message["id"]})
            chat_request.join(timeout=10)
            assert not chat_request.is_alive()
            assert "Hola desde Ollama" in chat_result[0].text


def test_users_cannot_read_each_others_sessions_or_operations(tmp_path):
    with _account_app(tmp_path) as client:
        first = _register(client, "one@example.com")
        session_id = client.app.state.store.create_session(
            "Privada", user_id=first["id"]
        )
        operation_id = client.app.state.store.create_operation(
            "list_alignments",
            "read",
            {},
            "completed",
            session_id=session_id,
            user_id=first["id"],
            result={"ok": True},
        )
        client.post("/api/auth/logout")
        _register(client, "two@example.com")

        assert client.get(f"/api/sessions/{session_id}/messages").status_code == 404
        assert client.get(f"/api/operations/{operation_id}").json() == {
            "found": False,
            "operation": None,
        }
        assert client.get("/api/sessions").json()["sessions"] == []


def test_legacy_database_is_migrated_before_indexes(tmp_path):
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            model TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            tool_name TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE operations (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            tool TEXT NOT NULL,
            risk TEXT NOT NULL,
            status TEXT NOT NULL,
            args_json TEXT NOT NULL,
            result_json TEXT,
            error TEXT,
            idempotency_key TEXT,
            messages_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    connection.close()

    store = OperationStore(database)
    try:
        columns = {
            row["name"]
            for row in store._conn.execute("PRAGMA table_info(sessions)")
        }
        assert "user_id" in columns
        columns = {
            row["name"]
            for row in store._conn.execute("PRAGMA table_info(operations)")
        }
        assert "user_id" in columns
    finally:
        store.close()
