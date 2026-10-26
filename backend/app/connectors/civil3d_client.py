from __future__ import annotations

from typing import Any

import httpx

from ..core.logging import get_logger
from .base import ConnectorError
from .mock_connector import MockConnector

log = get_logger("connector.civil3d")


class Civil3DClient:
    """HTTP client for the local Civil 3D plugin bridge.

    The plugin listens exclusively on 127.0.0.1 and requires a shared token.
    If the bridge is unreachable and fallback is enabled, calls are delegated
    to MockConnector which never reports success.
    """

    mode = "real"

    def __init__(
        self,
        base_url: str,
        token: str = "",
        timeout: float = 30.0,
        fallback_to_mock: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._fallback = fallback_to_mock
        self._transport = transport
        self._mock = MockConnector()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["X-Ingenia-Token"] = self._token
        return headers

    async def status(self, user_id: str | None = None) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(3.0, connect=2.0),
                transport=self._transport,
            ) as client:
                resp = await client.get(f"{self._base}/status", headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
                data.setdefault("connected", True)
                data["mode"] = "real"
                return data
        except (httpx.HTTPError, ValueError) as exc:
            log.info("bridge no disponible: %s", exc)
            mock_status = await self._mock.status()
            mock_status["message"] = (
                "Complemento de Civil 3D no disponible en "
                f"{self._base}. {mock_status['message']}"
            )
            return mock_status

    async def call(
        self, tool: str, args: dict[str, Any], request_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {"tool": tool, "args": args, "request_id": request_id}
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=3.0),
                transport=self._transport,
            ) as client:
                resp = await client.post(
                    f"{self._base}/rpc", json=payload, headers=self._headers()
                )
                if resp.status_code == 401:
                    raise ConnectorError(
                        "El complemento rechazó el token compartido (CIVIL3D_TOKEN)."
                    )
                resp.raise_for_status()
                data = resp.json()
        except ConnectorError:
            raise
        except httpx.TimeoutException as exc:
            if self._fallback:
                return await self._mock.call(tool, args, request_id)
            raise ConnectorError(
                "El complemento de Civil 3D agotó el tiempo de espera."
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            if self._fallback:
                return await self._mock.call(tool, args, request_id)
            raise ConnectorError(
                f"No se pudo comunicar con el complemento de Civil 3D: {exc}"
            ) from exc

        data.setdefault("mode", "real")
        data.setdefault("ok", False)
        return data

