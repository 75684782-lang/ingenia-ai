from __future__ import annotations

from typing import Any

from ..core.logging import get_logger

log = get_logger("connector.mock")


class MockConnector:
    """Connector used only when Civil 3D is not reachable.

    It deliberately never reports success for read or write tools. Every call
    returns ok=False plus mode="mock" so the UI and the model cannot mistake a
    simulation for a real Civil 3D operation.
    """

    mode = "mock"

    async def status(self) -> dict[str, Any]:
        return {
            "connected": False,
            "mode": "mock",
            "simulated": True,
            "message": (
                "Civil 3D no está conectado. Este es el conector simulado: "
                "ninguna operación se ejecuta ni modifica el dibujo."
            ),
        }

    async def call(
        self, tool: str, args: dict[str, Any], request_id: str
    ) -> dict[str, Any]:
        log.warning("mock call tool=%s request=%s", tool, request_id)
        return {
            "ok": False,
            "mode": "mock",
            "simulated": True,
            "tool": tool,
            "request_id": request_id,
            "error": (
                "Civil 3D no está conectado. La operación NO se ejecutó "
                "(conector simulado). Configura el complemento y vuelve a intentarlo."
            ),
            "data": None,
        }
