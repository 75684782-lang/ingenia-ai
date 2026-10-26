from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..security.passwords import hash_token

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
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if origin and host and urlsplit(origin).netloc.lower() != host.lower():
        await websocket.close(code=1008)
        return
    user_id = None
    if state.settings.accounts_enabled:
        token = websocket.cookies.get("ingenia_session")
        user = (
            state.store.get_auth_user(hash_token(token))
            if token
            else None
        )
        if user is None:
            await websocket.close(code=1008)
            return
        user_id = user["id"]
    elif not _authorized(websocket, state.settings.auth_token):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            if user_id is None:
                ollama_ok = await state.ollama.is_available()
                civil = await state.connector.status()
            else:
                ollama_ok = await state.ollama.is_available(user_id=user_id)
                civil = await state.connector.status(user_id=user_id)
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
