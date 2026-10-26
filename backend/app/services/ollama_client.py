from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator

import httpx

from ..core.logging import get_logger

log = get_logger("ollama")

MODEL_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/@-]{0,119}$")


def is_valid_model_name(name: str) -> bool:
    return bool(name and MODEL_NAME_RE.fullmatch(name) and ".." not in name)


class OllamaError(RuntimeError):
    """Raised when Ollama is unreachable or returns an invalid response."""


class OllamaUnavailable(OllamaError):
    pass


def normalize_models(payload: dict[str, Any]) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    for item in payload.get("models", []):
        details = item.get("details", {}) or {}
        capabilities = item.get("capabilities") or []
        models.append(
            {
                "name": item.get("name") or item.get("model"),
                "size": item.get("size"),
                "parameter_size": details.get("parameter_size"),
                "capabilities": capabilities,
                "supports_tools": "tools" in capabilities,
            }
        )
    models.sort(key=lambda m: (not m["supports_tools"], m["name"] or ""))
    return models


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport

    def _client(self, timeout: float | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base,
            timeout=httpx.Timeout(timeout or self._timeout, connect=5.0),
            transport=self._transport,
        )

    async def is_available(self, user_id: str | None = None) -> bool:
        try:
            async with self._client(timeout=3.0) as client:
                resp = await client.get("/api/tags")
                return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def list_models(self, user_id: str | None = None) -> list[dict[str, Any]]:
        try:
            async with self._client(timeout=10.0) as client:
                resp = await client.get("/api/tags")
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(f"No se pudo consultar Ollama: {exc}") from exc

        models: list[dict[str, Any]] = []
        for item in payload.get("models", []):
            details = item.get("details", {}) or {}
            capabilities = item.get("capabilities") or []
            models.append(
                {
                    "name": item.get("name") or item.get("model"),
                    "size": item.get("size"),
                    "parameter_size": details.get("parameter_size"),
                    "capabilities": capabilities,
                    "supports_tools": "tools" in capabilities,
                }
            )
        models.sort(key=lambda m: (not m["supports_tools"], m["name"] or ""))
        return models

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        user_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temperature},
        }
        if tools:
            payload["tools"] = tools

        log.debug("chat model=%s messages=%d tools=%d", model, len(messages), len(tools or []))
        try:
            async with self._client() as client:
                async with client.stream("POST", "/api/chat", json=payload) as resp:
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode("utf-8", "replace")[:500]
                        raise OllamaError(
                            f"Ollama devolvió HTTP {resp.status_code}: {body}"
                        )
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError as exc:
                            raise OllamaError(
                                f"Respuesta NDJSON inválida de Ollama: {line[:200]}"
                            ) from exc
                        if data.get("error"):
                            raise OllamaError(str(data["error"]))
                        yield data
                        if data.get("done"):
                            break
        except httpx.TimeoutException as exc:
            raise OllamaUnavailable(
                "Ollama agotó el tiempo de espera. El modelo puede ser demasiado grande para este equipo."
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(f"No se pudo conectar con Ollama: {exc}") from exc


    async def pull_model_stream(self, model: str, user_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
        """Download a model through Ollama's /api/pull, streaming progress."""
        if not is_valid_model_name(model):
            raise OllamaError("Nombre de modelo inválido.")

        payload = {"model": model, "stream": True}
        try:
            async with httpx.AsyncClient(
                base_url=self._base,
                timeout=httpx.Timeout(None, connect=10.0),
                transport=self._transport,
            ) as client:
                async with client.stream("POST", "/api/pull", json=payload) as resp:
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode("utf-8", "replace")[:500]
                        raise OllamaError(
                            f"Ollama devolvió HTTP {resp.status_code}: {body}"
                        )
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError as exc:
                            raise OllamaError(
                                f"Respuesta NDJSON inválida de Ollama: {line[:200]}"
                            ) from exc
                        if data.get("error"):
                            raise OllamaError(str(data["error"]))
                        yield data
                        if data.get("status") == "success":
                            break
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(f"No se pudo descargar el modelo: {exc}") from exc


def extract_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    calls = message.get("tool_calls") or []
    normalized: list[dict[str, Any]] = []
    for call in calls:
        function = call.get("function") or {}
        name = function.get("name")
        args = function.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"_raw": args}
        if not isinstance(args, dict):
            args = {}
        if name:
            normalized.append({"name": name, "args": args, "raw": call})
    return normalized

