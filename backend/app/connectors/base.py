from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class ConnectorError(RuntimeError):
    pass


@runtime_checkable
class CivilConnector(Protocol):
    mode: str

    async def status(self, user_id: str | None = None) -> dict[str, Any]:
        ...

    async def call(
        self,
        tool: str,
        args: dict[str, Any],
        request_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        ...
