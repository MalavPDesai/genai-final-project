from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(default="demo-session", min_length=1, max_length=120)
    simulate_failure: bool = False


class PolicySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)


class ApproveActionRequest(BaseModel):
    action_id: str
    selected_room_type: str | None = None
    simulate_failure: bool = False


class RejectActionRequest(BaseModel):
    action_id: str


class ToolActivity(BaseModel):
    name: str
    result_summary: str
    status: Literal["success", "warning", "blocked", "escalation"] = "success"


class ChatResponse(BaseModel):
    message: str
    tool_calls: list[ToolActivity] = Field(default_factory=list)
    retrieved_policies: list[dict[str, Any]] = Field(default_factory=list)
    record_preview: dict[str, Any] | None = None
    evidence_status: Literal[
        "SUPPORTED", "PARTIALLY_SUPPORTED", "NOT_SUPPORTED", "CONFLICTING"
    ] | None = None
    requires_escalation: bool = False
    requires_approval: bool = False
    pending_action: dict[str, Any] | None = None
    mode: Literal["openai", "offline-test"] = "openai"


class HealthResponse(BaseModel):
    status: str
    database: str
    rag: str
    mode: str
