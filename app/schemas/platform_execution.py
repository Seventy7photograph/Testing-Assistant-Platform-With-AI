"""受控 HTTP 执行契约。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.execution import TestRun
from app.schemas.jobs import Job


class HttpExecutionRequest(BaseModel):
    artifact_id: str = Field(..., min_length=1, max_length=128)
    case_ids: list[str] = Field(default_factory=list, max_length=200)
    allow_all_cases: bool = False
    environment: dict[str, str] = Field(
        default_factory=dict,
        description="仅在本次执行内使用；不会写入运行记录、事件或日志。",
    )
    base_url: str = Field(default="", max_length=500)
    idempotency_key: str = Field(default="", max_length=200)


class HttpExecutionResponse(BaseModel):
    job: Job
    run: TestRun


__all__ = ["HttpExecutionRequest", "HttpExecutionResponse"]
