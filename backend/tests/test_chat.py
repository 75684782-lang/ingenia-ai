from __future__ import annotations

from .conftest import HEADERS, parse_sse, tool_call


def test_chat_runs_tool_and_answers(app_factory):
    ctx = app_factory(
        script=[
            {"tool_calls": [tool_call("list_alignments", {})]},
            {"content": "El dibujo tiene 0 alineamientos."},
        ]
    )
    response = ctx.client.post(
        "/api/chat",
        headers=HEADERS,
        json={"message": "¿Cuántos alineamientos hay?"},
    )
    events = parse_sse(response.text)
    types = [event["type"] for event in events]

    assert "session" in types
    assert "tool_start" in types
    assert "tool_result" in types
    final = [event for event in events if event["type"] == "assistant_message"]
    assert final and "0 alineamientos" in final[-1]["content"]
    tool_result = next(event for event in events if event["type"] == "tool_result")
    assert tool_result["result"]["ok"] is True
    assert tool_result["result"]["mode"] == "real"
    assert ctx.connector.calls[0][0] == "list_alignments"


def test_chat_write_requires_confirmation(app_factory):
    ctx = app_factory(
        script=[
            {
                "tool_calls": [
                    tool_call("create_surface", {"name": "Terreno Natural"})
                ]
            }
        ]
    )
    response = ctx.client.post(
        "/api/chat",
        headers=HEADERS,
        json={"message": "Crea una superficie Terreno Natural"},
    )
    events = parse_sse(response.text)
    confirmation = [e for e in events if e["type"] == "confirmation_required"]
    assert confirmation
    operation = confirmation[0]["result"]
    assert operation["requires_confirmation"] is True
    assert ctx.connector.calls == []
    stored = ctx.app.state.store.get_operation(operation["operation_id"])
    assert stored["status"] == "pending_confirmation"


def test_chat_confirmation_approves_and_reports_real_result(app_factory):
    ctx = app_factory(
        script=[
            {
                "tool_calls": [
                    tool_call("create_surface", {"name": "Terreno Natural"})
                ]
            },
            {"content": "Superficie creada y verificada."},
        ]
    )
    first = parse_sse(
        ctx.client.post(
            "/api/chat",
            headers=HEADERS,
            json={"message": "Crea una superficie Terreno Natural"},
        ).text
    )
    operation_id = next(
        e for e in first if e["type"] == "confirmation_required"
    )["result"]["operation_id"]

    second = parse_sse(
        ctx.client.post(
            "/api/chat/confirm",
            headers=HEADERS,
            json={"operation_id": operation_id, "approve": True},
        ).text
    )
    tool_result = next(e for e in second if e["type"] == "tool_result")
    assert tool_result["result"]["ok"] is True
    assert tool_result["result"]["mode"] == "real"
    assert len(ctx.connector.calls) == 1
    stored = ctx.app.state.store.get_operation(operation_id)
    assert stored["status"] == "completed"


def test_chat_confirmation_rejection_does_not_execute(app_factory):
    ctx = app_factory(
        script=[
            {
                "tool_calls": [
                    tool_call("create_surface", {"name": "Terreno Natural"})
                ]
            }
        ]
    )
    first = parse_sse(
        ctx.client.post(
            "/api/chat",
            headers=HEADERS,
            json={"message": "Crea una superficie"},
        ).text
    )
    operation_id = next(
        e for e in first if e["type"] == "confirmation_required"
    )["result"]["operation_id"]

    second = parse_sse(
        ctx.client.post(
            "/api/chat/confirm",
            headers=HEADERS,
            json={"operation_id": operation_id, "approve": False},
        ).text
    )
    assert any(e["type"] == "assistant_message" for e in second)
    assert ctx.connector.calls == []
    stored = ctx.app.state.store.get_operation(operation_id)
    assert stored["status"] == "rejected"


def test_chat_surfaces_ollama_error(app_factory):
    class BrokenOllama:
        async def is_available(self):
            return False

        async def list_models(self):
            return []

        async def chat_stream(self, *args, **kwargs):
            from app.services.ollama_client import OllamaUnavailable

            raise OllamaUnavailable("Ollama no responde.")
            yield  # pragma: no cover

    ctx = app_factory()
    ctx.app.state.ollama = BrokenOllama()
    ctx.app.state.chat.ollama = BrokenOllama()

    events = parse_sse(
        ctx.client.post(
            "/api/chat", headers=HEADERS, json={"message": "Hola"}
        ).text
    )
    error = [e for e in events if e["type"] == "error"]
    assert error and "Ollama" in error[0]["message"]
