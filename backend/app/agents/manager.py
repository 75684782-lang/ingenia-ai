from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from typing import Any, AsyncIterator

from fastapi import WebSocket, WebSocketDisconnect

from ..core.logging import get_logger

log = get_logger("agents")


class AgentError(RuntimeError):
    pass


class AgentUnavailable(AgentError):
    pass


class AgentConnection:
    def __init__(
        self,
        agent_id: str,
        user_id: str,
        name: str,
        websocket: WebSocket,
        store: Any,
    ) -> None:
        self.agent_id = agent_id
        self.user_id = user_id
        self.name = name
        self.websocket = websocket
        self.store = store
        self.pending: dict[str, asyncio.Queue] = {}
        self._send_lock = asyncio.Lock()

    async def send(self, payload: dict[str, Any]) -> None:
        try:
            async with self._send_lock:
                await self.websocket.send_json(payload)
        except (RuntimeError, WebSocketDisconnect) as exc:
            raise AgentUnavailable("El conector local se desconectó.") from exc

    def handle(self, message: dict[str, Any]) -> None:
        if message.get("type") == "ping":
            self.store.touch_agent(self.agent_id)
            return
        request_id = message.get("id")
        queue = self.pending.get(request_id) if isinstance(request_id, str) else None
        if queue is not None:
            queue.put_nowait(message)

    def fail_pending(self, reason: str) -> None:
        for request_id, queue in list(self.pending.items()):
            queue.put_nowait(
                {
                    "type": "response",
                    "ok": False,
                    "error": reason,
                    "id": request_id,
                }
            )

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> Any:
        request_id = uuid.uuid4().hex
        queue: asyncio.Queue = asyncio.Queue()
        self.pending[request_id] = queue
        try:
            await self.send(
                {
                    "type": "request",
                    "id": request_id,
                    "method": method,
                    "params": params or {},
                }
            )
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=timeout)
                except asyncio.TimeoutError as exc:
                    raise AgentError(
                        f"El conector local no respondió a {method} a tiempo."
                    ) from exc
                if message.get("type") == "response":
                    if not message.get("ok"):
                        raise AgentError(
                            message.get("error") or "El conector local devolvió un error."
                        )
                    return message.get("result")
        finally:
            self.pending.pop(request_id, None)

    async def stream(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        idle_timeout: float = 600.0,
    ) -> AsyncIterator[dict[str, Any]]:
        request_id = uuid.uuid4().hex
        queue: asyncio.Queue = asyncio.Queue()
        self.pending[request_id] = queue
        try:
            await self.send(
                {
                    "type": "request",
                    "id": request_id,
                    "method": method,
                    "params": params or {},
                }
            )
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=idle_timeout)
                except asyncio.TimeoutError as exc:
                    raise AgentError(
                        f"El conector local dejó de responder durante {method}."
                    ) from exc
                kind = message.get("type")
                if kind == "chunk":
                    yield message.get("data") or {}
                elif kind == "end":
                    return
                elif kind == "response":
                    if not message.get("ok"):
                        raise AgentError(
                            message.get("error")
                            or "El conector local devolvió un error."
                        )
                    return
        finally:
            self.pending.pop(request_id, None)


class AgentManager:
    def __init__(self) -> None:
        self._connections: dict[str, AgentConnection] = {}

    def register(self, connection: AgentConnection) -> AgentConnection | None:
        previous = self._connections.get(connection.agent_id)
        self._connections[connection.agent_id] = connection
        log.info("agente conectado: %s (%s)", connection.name, connection.agent_id)
        return previous

    def unregister(self, connection: AgentConnection) -> None:
        if self._connections.get(connection.agent_id) is connection:
            self._connections.pop(connection.agent_id, None)
            log.info("agente desconectado: %s", connection.agent_id)

    def get_for_user(self, user_id: str | None) -> AgentConnection | None:
        if not user_id:
            return None
        candidates = [
            c for c in self._connections.values() if c.user_id == user_id
        ]
        if not candidates:
            return None
        return candidates[-1]

    def get_by_id(self, agent_id: str) -> AgentConnection | None:
        return self._connections.get(agent_id)

    def online_ids(self, user_id: str) -> set[str]:
        return {
            c.agent_id for c in self._connections.values() if c.user_id == user_id
        }

    def is_online(self, agent_id: str) -> bool:
        return agent_id in self._connections

    async def close_all(self) -> None:
        connections = list(self._connections.values())
        self._connections.clear()
        for connection in connections:
            connection.fail_pending("El servidor se está apagando.")
            try:
                await connection.websocket.close(code=1001)
            except RuntimeError:
                pass
