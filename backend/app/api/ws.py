from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


def _authorized(websocket: WebSocket, expected: str) -> bool:
    if not expected:
        return True
    token = websocket.headers.get("x-ingenia-token") or websocket.cookies.get(
        "ingenia_token"
    )
    return token == expected


@router.websocket("/ws/status")
async def status_socket(websocket: WebSocket) -> None:
    state = websocket.app.state
    if not _authorized(websocket, state.settings.auth_token):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            ollama_ok = await state.ollama.is_available()
            civil = await state.connector.status()
            await websocket.send_json(
                {
                    "type": "status",
                    "ollama": {"available": ollama_ok},
                    "civil3d": civil,
                }
            )
            await asyncio.sleep(15)
    except (WebSocketDisconnect, RuntimeError):
        return
