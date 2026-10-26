from __future__ import annotations

import httpx
import pytest

from app.connectors.base import ConnectorError
from app.connectors.civil3d_client import Civil3DClient
from app.connectors.mock_connector import MockConnector
from app.services.ollama_client import OllamaClient, OllamaUnavailable
from .conftest import HEADERS, FakeConnector, mock_transport


def test_invalid_arguments_are_rejected(app_factory):
    ctx = app_factory()
    response = ctx.client.post(
        "/api/tools/create_surface/execute",
        headers=HEADERS,
        json={"args": {}, "confirm": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["status"] == "validation_error"
    assert body["errors"]
    assert ctx.connector.calls == []


def test_unknown_tool_is_rejected(app_factory):
    ctx = app_factory()
    response = ctx.client.post(
        "/api/tools/execute_powershell/execute",
        headers=HEADERS,
        json={"args": {"command": "whoami"}},
    )
    body = response.json()
    assert body["ok"] is False
    assert body["status"] == "validation_error"


def test_read_tool_executes_without_confirmation(app_factory):
    ctx = app_factory()
    response = ctx.client.post(
        "/api/tools/list_alignments/execute",
        headers=HEADERS,
        json={"args": {}},
    )
    body = response.json()
    assert body["ok"] is True
    assert body["status"] == "completed"
    assert ctx.connector.calls[0][0] == "list_alignments"


def test_write_tool_requires_confirmation(app_factory):
    ctx = app_factory()
    response = ctx.client.post(
        "/api/tools/create_surface/execute",
        headers=HEADERS,
        json={"args": {"name": "Terreno"}, "confirm": False},
    )
    body = response.json()
    assert body["requires_confirmation"] is True
    assert body["status"] == "pending_confirmation"
    assert body["operation_id"]
    assert ctx.connector.calls == []
    stored = ctx.app.state.store.get_operation(body["operation_id"])
    assert stored["status"] == "pending_confirmation"


def test_confirmed_write_executes(app_factory):
    ctx = app_factory()
    pending = ctx.client.post(
        "/api/tools/create_surface/execute",
        headers=HEADERS,
        json={"args": {"name": "Terreno"}, "confirm": False},
    ).json()
    response = ctx.client.post(
        "/api/tools/create_surface/execute",
        headers=HEADERS,
        json={
            "args": {"name": "Terreno"},
            "confirm": True,
            "idempotency_key": "clave-1",
        },
    ).json()
    assert response["ok"] is True
    assert response["status"] == "completed"
    assert len(ctx.connector.calls) == 1
    assert pending["operation_id"] != response["operation_id"]


def test_duplicate_request_is_not_executed_twice(app_factory):
    ctx = app_factory()
    payload = {
        "args": {"name": "Terreno"},
        "confirm": True,
        "idempotency_key": "clave-unica",
    }
    first = ctx.client.post(
        "/api/tools/create_surface/execute", headers=HEADERS, json=payload
    ).json()
    second = ctx.client.post(
        "/api/tools/create_surface/execute", headers=HEADERS, json=payload
    ).json()
    assert first["operation_id"] == second["operation_id"]
    assert len(ctx.connector.calls) == 1


def test_connector_failure_is_reported(app_factory):
    ctx = app_factory(connector=FakeConnector(fail=True))
    response = ctx.client.post(
        "/api/tools/list_alignments/execute",
        headers=HEADERS,
        json={"args": {}},
    ).json()
    assert response["ok"] is False
    assert response["status"] == "failed"
    assert "bridge" in (response["error"] or "").lower()


def test_operation_status_tool_is_local(app_factory):
    ctx = app_factory()
    result = ctx.client.post(
        "/api/tools/list_alignments/execute", headers=HEADERS, json={"args": {}}
    ).json()
    status = ctx.client.post(
        "/api/tools/get_operation_status/execute",
        headers=HEADERS,
        json={"args": {"operation_id": result["operation_id"]}},
    ).json()
    assert status["ok"] is True
    assert status["result"]["operation"]["id"] == result["operation_id"]


def test_experimental_tool_is_flagged(app_factory):
    ctx = app_factory()
    response = ctx.client.post(
        "/api/tools/calculate_volumes/execute",
        headers=HEADERS,
        json={"args": {"base_surface": "A", "comparison_surface": "B"}},
    ).json()
    assert response["result"]["experimental"] is True


@pytest.mark.asyncio
async def test_mock_connector_never_reports_success():
    mock = MockConnector()
    status = await mock.status()
    assert status["connected"] is False
    assert status["mode"] == "mock"
    result = await mock.call("create_surface", {"name": "X"}, "req-1")
    assert result["ok"] is False
    assert result["mode"] == "mock"


@pytest.mark.asyncio
async def test_civil3d_client_falls_back_to_mock_when_bridge_down():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("conexión rechazada", request=request)

    client = Civil3DClient(
        "http://127.0.0.1:8756",
        token="token",
        fallback_to_mock=True,
        transport=mock_transport(handler),
    )
    status = await client.status()
    assert status["connected"] is False
    result = await client.call("get_active_drawing_info", {}, "req")
    assert result["ok"] is False
    assert result["mode"] == "mock"


@pytest.mark.asyncio
async def test_civil3d_client_propagates_real_result():
    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={"ok": True, "mode": "real", "data": {"drawing": "x.dwg"}},
        )

    client = Civil3DClient(
        "http://127.0.0.1:8756",
        token="token",
        fallback_to_mock=False,
        transport=mock_transport(handler),
    )
    result = await client.call("get_active_drawing_info", {}, "req")
    assert result["ok"] is True
    assert result["data"]["drawing"] == "x.dwg"


@pytest.mark.asyncio
async def test_civil3d_timeout_without_fallback_raises():
    def handler(request: httpx.Request):
        raise httpx.ReadTimeout("timeout", request=request)

    client = Civil3DClient(
        "http://127.0.0.1:8756",
        token="token",
        fallback_to_mock=False,
        transport=mock_transport(handler),
    )
    with pytest.raises(ConnectorError):
        await client.call("get_active_drawing_info", {}, "req")
