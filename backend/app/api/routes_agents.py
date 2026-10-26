from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)

from ..agents import AgentConnection
from ..models.schemas import PairRequest
from ..security.auth import require_user
from ..security.passwords import hash_token, new_token

router = APIRouter(prefix="/api/agents", tags=["agents"])
websocket_router = APIRouter()
PAIR_CODE_TTL_SECONDS = 300


@router.post("/pair-code")
async def create_pair_code(
    request: Request, user: dict = Depends(require_user)
) -> dict:
    if not request.app.state.settings.use_agents:
        raise HTTPException(status_code=404, detail="Conectores no habilitados.")
    client = request.client.host if request.client else "unknown"
    request.app.state.pair_limiter.check(client)
    code = f"{secrets.randbelow(1_000_000_000):09d}"
    expires = datetime.now(timezone.utc) + timedelta(
        seconds=PAIR_CODE_TTL_SECONDS
    )
    request.app.state.store.create_pair_code(
        code, user["id"], expires.isoformat(timespec="seconds")
    )
    return {
        "code": code,
        "expires_at": expires.isoformat(timespec="seconds"),
        "expires_in": PAIR_CODE_TTL_SECONDS,
    }


@router.get("")
async def list_agents(
    request: Request, user: dict = Depends(require_user)
) -> dict:
    online = request.app.state.agent_manager.online_ids(user["id"])
    agents = request.app.state.store.list_agents(user["id"])
    for agent in agents:
        agent["online"] = agent["id"] in online
    return {"agents": agents}


@router.delete("/{agent_id}")
async def revoke_agent(
    agent_id: str, request: Request, user: dict = Depends(require_user)
) -> dict:
    revoked = request.app.state.store.revoke_agent(user["id"], agent_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="Conector no encontrado.")
    connection = request.app.state.agent_manager.get_by_id(agent_id)
    if connection is not None:
        connection.fail_pending("El conector fue revocado desde tu cuenta.")
        try:
            await connection.websocket.close(code=1008)
        except RuntimeError:
            pass
    return {"ok": True}


@websocket_router.websocket("/ws/agent")
async def agent_socket(websocket: WebSocket) -> None:
    state = websocket.app.state
    if not state.settings.accounts_enabled or not state.settings.use_agents:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    connection: AgentConnection | None = None
    try:
        message = await asyncio.wait_for(websocket.receive_json(), timeout=15)
        if not isinstance(message, dict):
            await websocket.close(code=1008)
            return

        if message.get("type") == "pair":
            client = websocket.client.host if websocket.client else "unknown"
            try:
                state.pair_limiter.check(client)
            except HTTPException:
                await websocket.close(code=1013)
                return
            payload = PairRequest.model_validate(
                {"code": message.get("code"), "name": message.get("name", "Mi PC")}
            )
            user_id = state.store.consume_pair_code(payload.code)
            if user_id is None:
                await websocket.send_json(
                    {"type": "error", "error": "Código inválido o vencido."}
                )
                await websocket.close(code=1008)
                return
            token = new_token("iga_")
            agent = state.store.create_agent(user_id, payload.name, hash_token(token))
            connection = AgentConnection(
                agent["id"], user_id, agent["name"], websocket, state.store
            )
            previous = state.agent_manager.register(connection)
            if previous is not None:
                previous.fail_pending("El conector volvió a conectarse.")
                try:
                    await previous.websocket.close(code=1000)
                except RuntimeError:
                    pass
            await websocket.send_json(
                {
                    "type": "paired",
                    "agent_id": agent["id"],
                    "name": agent["name"],
                    "token": token,
                }
            )
        elif message.get("type") == "authenticate":
            token = message.get("token")
            if not isinstance(token, str) or not token.startswith("iga_"):
                await websocket.close(code=1008)
                return
            agent = state.store.get_agent_by_token(hash_token(token))
            if agent is None:
                await websocket.close(code=1008)
                return
            connection = AgentConnection(
                agent["id"],
                agent["user_id"],
                agent["name"],
                websocket,
                state.store,
            )
            previous = state.agent_manager.register(connection)
            if previous is not None:
                previous.fail_pending("El conector volvió a conectarse.")
                try:
                    await previous.websocket.close(code=1000)
                except RuntimeError:
                    pass
            state.store.touch_agent(agent["id"])
            await websocket.send_json({"type": "authenticated"})
        else:
            await websocket.close(code=1008)
            return

        while True:
            incoming = await websocket.receive_json()
            if isinstance(incoming, dict):
                connection.handle(incoming)
    except asyncio.TimeoutError:
        await websocket.close(code=1008)
    except WebSocketDisconnect:
        pass
    except (ValueError, TypeError):
        await websocket.close(code=1003)
    finally:
        if connection is not None:
            connection.fail_pending("El conector local se desconectó.")
            state.agent_manager.unregister(connection)
