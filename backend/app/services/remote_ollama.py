from __future__ import annotations

from typing import Any, AsyncIterator

from ..agents import AgentError, AgentManager, AgentUnavailable
from .ollama_client import (
    OllamaError,
    OllamaUnavailable,
    is_valid_model_name,
    normalize_models,
)


class RemoteOllamaClient:
    """Ollama proxy that runs on the user's PC through the local agent."""

    def __init__(self, manager: AgentManager) -> None:
        self.manager = manager

    def _connection(self, user_id: str | None):
        connection = self.manager.get_for_user(user_id)
        if connection is None:
            raise OllamaUnavailable(
                "Tu PC no está conectada. Abre Ingenia Connector e introduce el código de emparejamiento."
            )
        return connection

    async def is_available(self, user_id: str | None = None) -> bool:
        try:
            result = await self._connection(user_id).request(
                "ollama.status", timeout=8.0
            )
            return bool(result and result.get("available"))
        except (AgentError, OllamaUnavailable):
            return False

    async def list_models(self, user_id: str | None = None) -> list[dict[str, Any]]:
        try:
            payload = await self._connection(user_id).request(
                "ollama.models", timeout=20.0
            )
        except AgentError as exc:
            raise OllamaUnavailable(str(exc)) from exc
        if not isinstance(payload, dict):
            raise OllamaUnavailable("Respuesta inválida del conector local.")
        return normalize_models(payload)

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        user_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        params: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            params["tools"] = tools
        try:
            async for chunk in self._connection(user_id).stream(
                "ollama.chat", params, idle_timeout=600.0
            ):
                if isinstance(chunk, dict) and chunk.get("error"):
                    raise OllamaError(str(chunk["error"]))
                yield chunk
        except AgentUnavailable as exc:
            raise OllamaUnavailable(str(exc)) from exc
        except AgentError as exc:
            raise OllamaError(str(exc)) from exc

    async def pull_model_stream(
        self, model: str, user_id: str | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        if not is_valid_model_name(model):
            raise OllamaError("Nombre de modelo inválido.")
        try:
            async for chunk in self._connection(user_id).stream(
                "ollama.pull", {"model": model}, idle_timeout=600.0
            ):
                yield chunk
        except AgentUnavailable as exc:
            raise OllamaUnavailable(str(exc)) from exc
        except AgentError as exc:
            raise OllamaError(str(exc)) from exc
