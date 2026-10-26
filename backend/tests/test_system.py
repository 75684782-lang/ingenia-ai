from __future__ import annotations

from .conftest import HEADERS


def test_health_is_public(app_factory):
    ctx = app_factory()
    response = ctx.client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_api_requires_token(app_factory):
    ctx = app_factory()
    response = ctx.client.get("/api/tools")
    assert response.status_code == 401


def test_api_rejects_wrong_token(app_factory):
    ctx = app_factory()
    response = ctx.client.get("/api/tools", headers={"X-Ingenia-Token": "otro"})
    assert response.status_code == 401


def test_tools_are_listed(app_factory):
    ctx = app_factory()
    response = ctx.client.get("/api/tools", headers=HEADERS)
    assert response.status_code == 200
    names = {tool["name"] for tool in response.json()["tools"]}
    expected = {
        "get_civil3d_status",
        "get_active_drawing_info",
        "list_drawing_objects",
        "inspect_surface",
        "list_alignments",
        "create_surface",
        "generate_contours",
        "create_alignment_from_polyline",
        "generate_profile",
        "get_operation_status",
        "calculate_volumes",
    }
    assert expected.issubset(names)


def test_config_and_status(app_factory):
    ctx = app_factory()
    config = ctx.client.get("/api/config", headers=HEADERS).json()
    assert config["default_model"] == "qwen-test:1.5b"
    status = ctx.client.get("/api/civil3d/status", headers=HEADERS).json()
    assert status["connected"] is True
    assert status["mode"] == "real"


def test_models_endpoint(app_factory):
    ctx = app_factory()
    payload = ctx.client.get("/api/ollama/models", headers=HEADERS).json()
    assert payload["available"] is True
    assert payload["models"][0]["supports_tools"] is True


def test_pull_model_streams_progress(app_factory):
    from .conftest import parse_sse

    ctx = app_factory()
    response = ctx.client.post(
        "/api/ollama/pull",
        headers=HEADERS,
        json={"model": "qwen2.5-coder:1.5b"},
    )
    events = parse_sse(response.text)
    types = [event["type"] for event in events]
    assert types[0] == "start"
    assert "progress" in types
    assert types[-1] == "done"
    progress = next(event for event in events if event["type"] == "progress" and event.get("percent") is not None)
    assert progress["percent"] == 50.0


def test_pull_model_rejects_invalid_name(app_factory):
    ctx = app_factory()
    response = ctx.client.post(
        "/api/ollama/pull",
        headers=HEADERS,
        json={"model": "malicious name; rm -rf /"},
    )
    assert response.status_code == 422
