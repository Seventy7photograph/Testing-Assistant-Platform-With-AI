"""受控 HTTP 执行契约。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.utils import now_iso
from app.schemas.execution import TestRun
from app.schemas.jobs import Job


class ApiEnvironmentProfile(BaseModel):
    environment_id: str
    project_id: str
    name: str
    base_url: str = ""
    variables: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class ApiEnvironmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    base_url: str = Field(default="", max_length=500)
    variables: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)


class ApiEnvironmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, max_length=500)
    variables: dict[str, str] | None = None
    headers: dict[str, str] | None = None


class HttpExecutionRequest(BaseModel):
    artifact_id: str = Field(..., min_length=1, max_length=128)
    case_ids: list[str] = Field(default_factory=list, max_length=200)
    allow_all_cases: bool = False
    environment_id: str = Field(default="", max_length=128)
    environment: dict[str, str] = Field(
        default_factory=dict,
        description="仅在本次执行内使用；不会写入运行记录、事件或日志。",
    )
    secret_values: dict[str, str] = Field(
        default_factory=dict,
        description="仅在本次执行内使用；支持 Authorization 等敏感变量替换。",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="仅在本次执行内使用的附加 Header；敏感值应使用双花括号变量。",
    )
    base_url: str = Field(default="", max_length=500)
    idempotency_key: str = Field(default="", max_length=200)


class HttpExecutionResponse(BaseModel):
    job: Job
    run: TestRun


__all__ = [
    "ApiEnvironmentCreate",
    "ApiEnvironmentProfile",
    "ApiEnvironmentUpdate",
    "HttpExecutionRequest",
    "HttpExecutionResponse",
]


__all__ = ["HttpExecutionRequest", "HttpExecutionResponse"]
