from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..models.schemas import PullModelRequest
from ..security.auth import require_local
from ..services.ollama_client import is_valid_model_name

router = APIRouter(prefix="/api", tags=["system"])

public_router = APIRouter(prefix="/api", tags=["public"])


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


@public_router.get("/health")
async def health(request: Request) -> dict:
    return {
        "status": "ok",
        "app": request.app.state.settings.app_name,
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


@router.get("/config")
async def config(request: Request, _: None = Depends(require_local)) -> dict:
    settings = request.app.state.settings
    return {
        "app": settings.app_name,
        "default_model": settings.ollama_model,
        "auth_required": bool(settings.auth_token),
        "civil3d_fallback_to_mock": settings.civil3d_fallback_to_mock,
    }


@router.get("/ollama/status")
async def ollama_status(request: Request, _: None = Depends(require_local)) -> dict:
    available = await request.app.state.ollama.is_available()
    return {"available": available, "url": request.app.state.settings.ollama_url}


@router.get("/ollama/models")
async def ollama_models(request: Request, _: None = Depends(require_local)) -> dict:
    try:
        models = await request.app.state.ollama.list_models()
        return {"available": True, "models": models, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "models": [], "error": str(exc)}


@router.post("/ollama/pull")
async def pull_model(
    payload: PullModelRequest,
    request: Request,
    _: None = Depends(require_local),
) -> StreamingResponse:
    model = payload.model.strip()
    if not is_valid_model_name(model):
        raise HTTPException(
            status_code=422,
            detail="Nombre de modelo inválido. Usa un tag de Ollama, por ejemplo qwen2.5-coder:1.5b.",
        )

    ollama = request.app.state.ollama

    async def generator():
        yield _sse({"type": "start", "model": model})
        try:
            async for chunk in ollama.pull_model_stream(model):
                status = chunk.get("status", "")
                total = chunk.get("total") or 0
                completed = chunk.get("completed") or 0
                percent = round(completed / total * 100, 1) if total else None
                yield _sse(
                    {
                        "type": "progress",
                        "model": model,
                        "status": status,
                        "completed": completed,
                        "total": total,
                        "percent": percent,
                    }
                )
                if status == "success":
                    yield _sse({"type": "done", "model": model})
                    return
            yield _sse({"type": "done", "model": model})
        except Exception as exc:  # noqa: BLE001
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/civil3d/status")
async def civil3d_status(request: Request, _: None = Depends(require_local)) -> dict:
    return await request.app.state.connector.status()


@router.get("/sessions")
async def list_sessions(request: Request, limit: int = 50, _: None = Depends(require_local)) -> dict:
    return {"sessions": request.app.state.store.list_sessions(limit=limit)}


@router.get("/sessions/{session_id}/messages")
async def session_messages(
    session_id: str, request: Request, _: None = Depends(require_local)
) -> dict:
    return {
        "session": request.app.state.store.get_session(session_id),
        "messages": request.app.state.store.get_messages(session_id),
    }


@router.get("/operations")
async def list_operations(
    request: Request,
    session_id: str | None = None,
    limit: int = 30,
    _: None = Depends(require_local),
) -> dict:
    return {
        "operations": request.app.state.store.list_operations(
            session_id=session_id, limit=limit
        )
    }


@router.get("/operations/{operation_id}")
async def get_operation(
    operation_id: str, request: Request, _: None = Depends(require_local)
) -> dict:
    operation = request.app.state.store.get_operation(operation_id)
    if operation is None:
        return {"found": False, "operation": None}
    return {"found": True, "operation": operation}
