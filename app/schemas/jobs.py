"""v3.0 运行治理：Job、Schedule、AgentRun 与 ToolCall。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.utils import now_iso

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
AgentRunStatus = Literal["running", "succeeded", "failed", "refused"]
ToolCallStatus = Literal["running", "succeeded", "failed", "denied"]


class Job(BaseModel):
    job_id: str
    project_id: str
    kind: str
    status: JobStatus = "queued"
    trace_id: str
    idempotency_key: str = ""
    attempt: int = 0
    max_attempts: int = 1
    timeout_seconds: float = 30.0
    payload_summary: dict[str, Any] = Field(default_factory=dict)
    result_summary: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    created_by: str = "local"
    created_at: str = Field(default_factory=now_iso)
    started_at: str | None = None
    finished_at: str | None = None


class JobCreate(BaseModel):
    kind: str = Field(..., min_length=2, max_length=80)
    timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    max_attempts: int = Field(default=1, ge=1, le=5)
    idempotency_key: str = Field(default="", max_length=200)
    payload_summary: dict[str, Any] = Field(default_factory=dict)


class Schedule(BaseModel):
    schedule_id: str
    project_id: str
    name: str
    job_kind: str
    interval_seconds: int = Field(default=3600, ge=30)
    timezone: str = "Asia/Shanghai"
    enabled: bool = True
    next_run_at: str | None = None
    max_runs: int | None = Field(default=None, ge=1)
    run_count: int = 0
    last_job_id: str = ""
    payload_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class ScheduleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    job_kind: str = Field(..., min_length=2, max_length=80)
    interval_seconds: int = Field(default=3600, ge=30)
    timezone: str = "Asia/Shanghai"
    enabled: bool = True
    max_runs: int | None = Field(default=None, ge=1)
    first_run_at: str | None = None
    payload_summary: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    tool_call_id: str
    project_id: str
    run_id: str = ""
    job_id: str = ""
    tool_name: str
    status: ToolCallStatus = "running"
    arguments_summary: dict[str, Any] = Field(default_factory=dict)
    result_summary: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    trace_id: str = ""
    started_at: str = Field(default_factory=now_iso)
    finished_at: str | None = None


class AgentRun(BaseModel):
    run_id: str
    project_id: str
    agent_kind: str = "readonly_assistant"
    conversation_id: str = ""
    status: AgentRunStatus = "running"
    request: str = ""
    response: str = ""
    citation_ids: list[str] = Field(default_factory=list)
    tool_call_ids: list[str] = Field(default_factory=list)
    trace_id: str
    created_by: str = "local"
    started_at: str = Field(default_factory=now_iso)
    finished_at: str | None = None
    error: str = ""


__all__ = [
    "AgentRun",
    "AgentRunStatus",
    "Job",
    "JobCreate",
    "JobStatus",
    "Schedule",
    "ScheduleCreate",
    "ToolCall",
    "ToolCallStatus",
]
