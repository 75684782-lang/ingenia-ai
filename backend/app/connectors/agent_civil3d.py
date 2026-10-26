from __future__ import annotations

from typing import Any

from ..agents import AgentError, AgentManager
from ..core.logging import get_logger
from .base import ConnectorError

log = get_logger("connector.agent")

_MOCK_MESSAGE = (
    "Tu PC no está conectada. Abre Ingenia Connector, introduce el código y "
    "asegúrate de que Civil 3D esté abierto con el complemento iniciado."
)


class AgentCivil3DConnector:
    """Civil 3D connector that relays calls to the local agent."""

    mode = "real"

    def __init__(self, manager: AgentManager) -> None:
        self.manager = manager

    def _connection(self, user_id: str | None):
        return self.manager.get_for_user(user_id)

    async def status(self, user_id: str | None = None) -> dict[str, Any]:
        connection = self._connection(user_id)
        if connection is None:
            return {
                "connected": False,
                "mode": "mock",
                "drawing": None,
                "message": _MOCK_MESSAGE,
            }
        try:
            data = await connection.request("civil3d.status", timeout=10.0)
        except AgentError as exc:
            log.info("agente civil3d no disponible: %s", exc)
            return {
                "connected": False,
                "mode": "mock",
                "drawing": None,
                "message": f"El conector no pudo consultar Civil 3D: {exc}",
            }
        if not isinstance(data, dict):
            data = {}
        data.setdefault("connected", False)
        data["mode"] = "real" if data.get("connected") else "mock"
        return data

    async def call(
        self,
        tool: str,
        args: dict[str, Any],
        request_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        connection = self._connection(user_id)
        if connection is None:
            return {
                "ok": False,
                "mode": "mock",
                "tool": tool,
                "error": _MOCK_MESSAGE,
            }
        try:
            data = await connection.request(
                "civil3d.call",
                {"tool": tool, "args": args, "request_id": request_id},
                timeout=90.0,
            )
        except AgentError as exc:
            raise ConnectorError(str(exc)) from exc
        if not isinstance(data, dict):
            raise ConnectorError("El conector local devolvió una respuesta inválida.")
        data.setdefault("mode", "real")
        data.setdefault("ok", False)
        return data
