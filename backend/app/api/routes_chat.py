from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..models.schemas import ChatRequest, ConfirmRequest
from ..security.auth import require_access

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


def _stream_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


@router.post("")
async def chat(
    payload: ChatRequest,
    request: Request,
    user: dict | None = Depends(require_access),
) -> StreamingResponse:
    state = request.app.state
    model = payload.model or state.settings.ollama_model

    async def generator():
        try:
            async for event in state.chat.stream_reply(
                payload.message,
                payload.session_id,
                model,
                user_id=user["id"] if user else None,
            ):
                yield _sse(event)
        except Exception as exc:  # noqa: BLE001
            yield _sse({"type": "error", "message": f"Error interno: {exc}"})

    return StreamingResponse(
        generator(), media_type="text/event-stream", headers=_stream_headers()
    )


@router.post("/confirm")
async def confirm(
    payload: ConfirmRequest,
    request: Request,
    user: dict | None = Depends(require_access),
) -> StreamingResponse:
    state = request.app.state
    model = payload.model or state.settings.ollama_model

    async def generator():
        try:
            async for event in state.chat.stream_confirm(
                payload.operation_id,
                payload.approve,
                model,
                user_id=user["id"] if user else None,
            ):
                yield _sse(event)
        except Exception as exc:  # noqa: BLE001
            yield _sse({"type": "error", "message": f"Error interno: {exc}"})

    return StreamingResponse(
        generator(), media_type="text/event-stream", headers=_stream_headers()
    )


@router.post("/stop")
async def stop(
    request: Request,
    session_id: str,
    user: dict | None = Depends(require_access),
) -> dict[str, Any]:
    if user and not request.app.state.store.get_session(session_id, user_id=user["id"]):
        raise HTTPException(status_code=404, detail="Conversación no encontrada.")
    request.app.state.chat.request_cancel(session_id)
    return {"ok": True, "message": "Solicitud de detención registrada."}
