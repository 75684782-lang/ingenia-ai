from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: str | None = None
    model: str | None = None


class ConfirmRequest(BaseModel):
    operation_id: str
    approve: bool
    model: str | None = None


class ToolExecuteRequest(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)
    confirm: bool = False
    idempotency_key: str | None = None


class PullModelRequest(BaseModel):
    model: str = Field(..., min_length=1, max_length=120)


class HealthResponse(BaseModel):
    status: str
    app: str
    time: str


class OllamaModel(BaseModel):
    name: str
    size: int | None = None
    parameter_size: str | None = None
    supports_tools: bool = False
    capabilities: list[str] = Field(default_factory=list)


class OperationView(BaseModel):
    id: str
    session_id: str | None
    tool: str
    risk: str
    status: str
    args: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str
    updated_at: str


class MessageView(BaseModel):
    id: int
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    tool_name: str | None = None
    created_at: str
