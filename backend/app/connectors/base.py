from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class ConnectorError(RuntimeError):
    pass


@runtime_checkable
class CivilConnector(Protocol):
    mode: str

    async def status(self) -> dict[str, Any]:
        ...

    async def call(
        self, tool: str, args: dict[str, Any], request_id: str
    ) -> dict[str, Any]:
        ...
