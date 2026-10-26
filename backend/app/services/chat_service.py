from __future__ import annotations

import json
from typing import Any, AsyncIterator

from ..connectors.base import CivilConnector
from ..core.logging import get_logger
from ..tools.executor import ToolExecutor
from ..tools.registry import ToolRegistry
from .ollama_client import OllamaClient, OllamaError, extract_tool_calls
from .operation_store import OperationStore

log = get_logger("chat")

SYSTEM_PROMPT = """Eres Ingenia AI, un asistente de ingeniería civil integrado con Autodesk Civil 3D.
Hablas en español, de forma breve, técnica y precisa.

REGLAS ESTRICTAS:
1. Para saber qué hay en el dibujo DEBES usar las herramientas. Nunca inventes nombres de
   superficies, alineamientos, handles ni datos del dibujo.
2. Nunca inventes resultados de operaciones. Solo puedes afirmar algo si la herramienta
   devolvió ok=true y mode="real".
3. Si una herramienta devuelve ok=false, mode="mock", status="pending_confirmation" o un error,
   di claramente que la operación NO se ejecutó y explica el motivo.
4. Las herramientas de escritura (risk="write") requieren confirmación del usuario. Al proponerlas,
   describe qué cambiará y espera la confirmación; no la repitas como si ya estuviera hecha.
5. Si faltan datos obligatorios (nombre de superficie, handle de polilínea, intervalo, etc.),
   pregunta al usuario en lugar de adivinar.
6. No ejecutes comandos de consola, SQL, PowerShell ni código. Solo puedes usar las herramientas
   disponibles en la conversación.
7. Las herramientas marcadas como experimentales deben presentarse como no verificadas.
8. Si no hay conexión con Civil 3D, dilo con claridad y ofrece solo consultas conceptuales.
"""

MAX_TOOL_RESULT_CHARS = 6000


def _compact_tool_result(result: dict[str, Any]) -> str:
    payload = {
        "ok": result.get("ok"),
        "status": result.get("status"),
        "mode": result.get("mode"),
        "operation_id": result.get("operation_id"),
        "tool": result.get("tool"),
        "error": result.get("error"),
        "message": result.get("message"),
        "data": result.get("result") if "result" in result else result.get("data"),
    }
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + "...(truncado)"
    return text


class ChatService:
    def __init__(
        self,
        ollama: OllamaClient,
        registry: ToolRegistry,
        executor: ToolExecutor,
        store: OperationStore,
        connector: CivilConnector,
        max_steps: int = 4,
    ) -> None:
        self.ollama = ollama
        self.registry = registry
        self.executor = executor
        self.store = store
        self.connector = connector
        self.max_steps = max(1, max_steps)
        self._cancelled: set[str] = set()

    def request_cancel(self, session_id: str) -> None:
        self._cancelled.add(session_id)

    def clear_cancel(self, session_id: str) -> None:
        self._cancelled.discard(session_id)

    async def stream_reply(
        self,
        text: str,
        session_id: str | None,
        model: str | None,
        user_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        session_id = self.store.ensure_session(
            session_id, title=text.strip()[:60], user_id=user_id
        )
        self.clear_cancel(session_id)
        yield {"type": "session", "session_id": session_id}

        self.store.add_message(session_id, "user", text)
        history = self.store.get_messages(session_id, user_id=user_id)
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for item in history:
            if item["role"] in {"user", "assistant"} and item["content"].strip():
                messages.append({"role": item["role"], "content": item["content"]})

        async for event in self._loop(session_id, model, messages, user_id=user_id):
            yield event

    async def stream_confirm(
        self,
        operation_id: str,
        approve: bool,
        model: str | None,
        user_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        operation = self.store.get_operation(operation_id, user_id=user_id)
        if operation is None:
            yield {"type": "error", "message": "La operación no existe."}
            return

        session_id = operation.get("session_id")
        result, _ = await self.executor.execute_pending(
            operation_id, approve, user_id=user_id
        )
        yield {
            "type": "tool_result",
            "tool": operation["tool"],
            "result": result,
        }

        if not session_id:
            yield {"type": "done"}
            return

        self.clear_cancel(session_id)
        yield {"type": "session", "session_id": session_id}

        messages = operation.get("messages")
        if not messages:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            for item in self.store.get_messages(session_id, user_id=user_id):
                if item["role"] in {"user", "assistant"} and item["content"].strip():
                    messages.append({"role": item["role"], "content": item["content"]})

        messages.append(
            {
                "role": "tool",
                "name": operation["tool"],
                "content": _compact_tool_result(result),
            }
        )
        if approve:
            resolved_model = model or (
                self.store.get_session(session_id, user_id=user_id) or {}
            ).get("model")
            self.store.touch_session(session_id, resolved_model)
        else:
            self.store.add_message(
                session_id,
                "assistant",
                "Operación cancelada. El dibujo no se modificó.",
            )
            yield {
                "type": "assistant_message",
                "content": "Operación cancelada. El dibujo no se modificó.",
            }
            yield {"type": "done"}
            return

        async for event in self._loop(session_id, model, messages, user_id=user_id):
            yield event

    async def _loop(
        self,
        session_id: str,
        model: str | None,
        messages: list[dict[str, Any]],
        user_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        tools = self.registry.ollama_tools()
        for _step in range(self.max_steps):
            if session_id in self._cancelled:
                yield {"type": "stopped", "message": "Generación detenida por el usuario."}
                return

            content_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            try:
                if user_id is None:
                    stream = self.ollama.chat_stream(model, messages, tools)
                else:
                    stream = self.ollama.chat_stream(
                        model, messages, tools, user_id=user_id
                    )
                async for chunk in stream:
                    if session_id in self._cancelled:
                        yield {"type": "stopped", "message": "Generación detenida por el usuario."}
                        return
                    message = chunk.get("message") or {}
                    piece = message.get("content") or ""
                    if piece:
                        content_parts.append(piece)
                        yield {"type": "token", "text": piece}
                    tool_calls.extend(extract_tool_calls(message))
                    if chunk.get("done"):
                        break
            except OllamaError as exc:
                log.warning("ollama error: %s", exc)
                yield {"type": "error", "message": str(exc)}
                return

            content = "".join(content_parts).strip()

            if not tool_calls:
                if content:
                    self.store.add_message(session_id, "assistant", content)
                yield {"type": "assistant_message", "content": content}
                yield {"type": "done"}
                return

            assistant_message: dict[str, Any] = {"role": "assistant", "content": content}
            assistant_message["tool_calls"] = [call["raw"] for call in tool_calls]
            messages.append(assistant_message)

            for call in tool_calls:
                if session_id in self._cancelled:
                    yield {"type": "stopped", "message": "Generación detenida por el usuario."}
                    return
                name = call["name"]
                args = call["args"]
                yield {"type": "tool_start", "tool": name, "args": args}

                result = await self.executor.execute(
                    name, args, session_id=session_id, user_id=user_id
                )
                yield {"type": "tool_result", "tool": name, "result": result}
                self.store.add_message(
                    session_id,
                    "tool",
                    _compact_tool_result(result),
                    tool_name=name,
                )

                if result.get("requires_confirmation"):
                    operation_id = result.get("operation_id")
                    if operation_id:
                        self.store.set_operation_messages(operation_id, messages)
                    yield {"type": "confirmation_required", "result": result}
                    return

                messages.append(
                    {
                        "role": "tool",
                        "name": name,
                        "content": _compact_tool_result(result),
                    }
                )

        message = (
            "Se alcanzó el límite de pasos de herramientas sin una respuesta final. "
            "Revisa el panel de operaciones."
        )
        yield {"type": "error", "message": message}
