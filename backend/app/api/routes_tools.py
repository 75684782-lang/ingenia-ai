from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..models.schemas import ToolExecuteRequest
from ..security.auth import require_local

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("")
async def list_tools(request: Request, _: None = Depends(require_local)) -> dict:
    return {"tools": request.app.state.registry.describe()}


@router.post("/{tool_name}/execute")
async def execute_tool(
    tool_name: str,
    payload: ToolExecuteRequest,
    request: Request,
    _: None = Depends(require_local),
) -> dict:
    result = await request.app.state.executor.execute(
        tool_name,
        payload.args,
        confirm=payload.confirm,
        idempotency_key=payload.idempotency_key,
    )
    return result
