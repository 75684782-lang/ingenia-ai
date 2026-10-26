from __future__ import annotations

import hashlib
import json
from typing import Any

from ..connectors.base import CivilConnector, ConnectorError
from ..core.logging import get_logger
from ..services.operation_store import OperationStore
from .registry import ToolRegistry, ToolSpec, ToolValidationError

log = get_logger("tools.executor")


def _idempotency_key(
    session_id: str | None,
    tool: str,
    args: dict[str, Any],
    user_id: str | None = None,
) -> str:
    raw = json.dumps(
        {
            "user": user_id or "",
            "session": session_id or "",
            "tool": tool,
            "args": args,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _preview(spec: ToolSpec, args: dict[str, Any]) -> str:
    parts = ", ".join(f"{k}={v}" for k, v in args.items() if v not in (None, "", 0))
    return f"{spec.name}({parts})" if parts else spec.name


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        connector: CivilConnector,
        store: OperationStore,
    ) -> None:
        self.registry = registry
        self.connector = connector
        self.store = store

    async def execute(
        self,
        name: str,
        args: dict[str, Any],
        *,
        session_id: str | None = None,
        confirm: bool = False,
        idempotency_key: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            spec, clean_args = self.registry.validate(name, args)
        except ToolValidationError as exc:
            result = exc.as_result()
            op_id = self.store.create_operation(
                tool=name,
                risk="unknown",
                args=args or {},
                status="validation_error",
                session_id=session_id,
                error=result["error"],
                user_id=user_id,
            )
            result["operation_id"] = op_id
            return result

        key = (
            hashlib.sha256(f"{user_id or ''}:{idempotency_key}".encode()).hexdigest()
            if idempotency_key
            else _idempotency_key(session_id, name, clean_args, user_id)
        )
        existing = self.store.find_by_idempotency(key, user_id=user_id)
        if existing and existing["status"] in {"completed", "failed", "rejected"}:
            return self._view(existing)
        if existing and existing["status"] == "pending_confirmation":
            if confirm:
                result, _ = await self.execute_pending(
                    existing["id"], True, user_id=user_id
                )
                return result
            return self._view(existing)

        if spec.requires_confirmation and not confirm:
            pending = self.store.create_operation(
                tool=name,
                risk=spec.risk,
                args=clean_args,
                status="pending_confirmation",
                session_id=session_id,
                idempotency_key=key,
            )
            return {
                "ok": False,
                "status": "pending_confirmation",
                "requires_confirmation": True,
                "operation_id": pending,
                "tool": name,
                "risk": spec.risk,
                "experimental": spec.experimental,
                "args": clean_args,
                "preview": _preview(spec, clean_args),
                "message": (
                    "Operación de escritura pendiente de confirmación. "
                    "No se ha modificado el dibujo."
                ),
            }

        return await self.execute_prepared(
            spec,
            clean_args,
            session_id=session_id,
            operation_id=None,
            idempotency_key=key,
            user_id=user_id,
        )

    async def execute_pending(
        self,
        operation_id: str,
        approve: bool,
        user_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        operation = self.store.get_operation(operation_id, user_id=user_id)
        if operation is None:
            return (
                {
                    "ok": False,
                    "status": "not_found",
                    "operation_id": operation_id,
                    "error": "La operación no existe.",
                },
                None,
            )
        if operation["status"] != "pending_confirmation":
            return self._view(operation), operation

        spec = self.registry.get(operation["tool"])
        if spec is None:
            self.store.update_operation(operation_id, status="failed", error="Herramienta desconocida")
            return (
                {
                    "ok": False,
                    "status": "failed",
                    "operation_id": operation_id,
                    "error": "Herramienta desconocida.",
                },
                operation,
            )

        if not approve:
            self.store.update_operation(
                operation_id,
                status="rejected",
                result={
                    "ok": False,
                    "status": "rejected",
                    "message": "El usuario rechazó la operación. El dibujo no se modificó.",
                },
            )
            return (
                {
                    "ok": False,
                    "status": "rejected",
                    "operation_id": operation_id,
                    "message": "Operación rechazada por el usuario. El dibujo no se modificó.",
                },
                operation,
            )

        result = await self.execute_prepared(
            spec,
            operation["args"],
            session_id=operation["session_id"],
            operation_id=operation_id,
            idempotency_key=None,
            user_id=user_id,
        )
        return result, operation

    async def execute_prepared(
        self,
        spec: ToolSpec,
        args: dict[str, Any],
        *,
        session_id: str | None,
        operation_id: str | None,
        idempotency_key: str | None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if operation_id is None:
            operation_id = self.store.create_operation(
                tool=spec.name,
                risk=spec.risk,
                args=args,
                status="running",
                session_id=session_id,
                idempotency_key=idempotency_key,
                user_id=user_id,
            )
        else:
            self.store.update_operation(operation_id, status="running")

        if spec.local:
            result = self._run_local(spec, args, user_id=user_id)
        else:
            try:
                if user_id is None:
                    result = await self.connector.call(spec.name, args, operation_id)
                else:
                    result = await self.connector.call(
                        spec.name, args, operation_id, user_id=user_id
                    )
            except ConnectorError as exc:
                result = {
                    "ok": False,
                    "mode": getattr(self.connector, "mode", "unknown"),
                    "tool": spec.name,
                    "error": str(exc),
                }

        if spec.experimental:
            result["experimental"] = True
            result.setdefault(
                "notice",
                "Herramienta experimental no verificada contra una instalación real de Civil 3D.",
            )

        mode = result.get("mode")
        if mode == "mock" and result.get("ok"):
            # Safety net: a simulated connector must never be reported as real success.
            result["ok"] = False

        status = "completed" if result.get("ok") else "failed"
        self.store.update_operation(
            operation_id,
            status=status,
            result=result,
            error=None if result.get("ok") else str(result.get("error") or ""),
        )
        view = self.store.get_operation(operation_id) or {}
        return self._view(view)

    def _run_local(
        self, spec: ToolSpec, args: dict[str, Any], user_id: str | None = None
    ) -> dict[str, Any]:
        if spec.name == "get_operation_status":
            operation = self.store.get_operation(args["operation_id"], user_id=user_id)
            if operation is None:
                return {
                    "ok": False,
                    "mode": "local",
                    "error": "Operación no encontrada.",
                }
            return {"ok": True, "mode": "local", "operation": operation}
        return {"ok": False, "mode": "local", "error": "Herramienta local no implementada."}

    @staticmethod
    def _view(operation: dict[str, Any]) -> dict[str, Any]:
        result = operation.get("result") or {}
        status = operation.get("status")
        ok = bool(result.get("ok")) if isinstance(result, dict) else False
        view: dict[str, Any] = {
            "ok": ok,
            "status": status,
            "operation_id": operation.get("id"),
            "tool": operation.get("tool"),
            "risk": operation.get("risk"),
            "args": operation.get("args"),
            "mode": result.get("mode") if isinstance(result, dict) else None,
            "result": result,
            "error": operation.get("error"),
            "created_at": operation.get("created_at"),
        }
        if status == "pending_confirmation":
            view["requires_confirmation"] = True
            view["ok"] = False
        return view
