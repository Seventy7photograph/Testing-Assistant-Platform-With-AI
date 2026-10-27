"""v3.0 项目、身份、配额与审计模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.utils import now_iso

ProjectRole = Literal["owner", "admin", "member", "viewer"]
ProjectStatus = Literal["active", "archived"]


class ProjectQuota(BaseModel):
    max_documents: int = 10_000
    max_suites: int = 5_000
    max_jobs: int = 50_000


class Project(BaseModel):
    project_id: str
    key: str
    name: str
    description: str = ""
    status: ProjectStatus = "active"
    quota: ProjectQuota = Field(default_factory=ProjectQuota)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class ProjectCreate(BaseModel):
    key: str = Field(..., min_length=2, max_length=32)
    name: str = Field(..., min_length=1, max_length=80)
    description: str = Field(default="", max_length=1000)
    quota: ProjectQuota | None = None

    @field_validator("key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        clean = "".join(char for char in value.upper() if char.isalnum() or char in "-_")
        if len(clean) < 2:
            raise ValueError("项目 Key 至少包含 2 个字母或数字")
        return clean


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    status: ProjectStatus | None = None
    quota: ProjectQuota | None = None


class ProjectContextInfo(BaseModel):
    project: Project
    actor: str
    role: ProjectRole
    auth_enabled: bool
    isolation_enabled: bool
    storage_backend: str


class AuditEvent(BaseModel):
    audit_id: str
    project_id: str
    actor: str
    role: str = "member"
    action: str
    resource_type: str = ""
    resource_id: str = ""
    outcome: Literal["allowed", "denied", "succeeded", "failed"] = "succeeded"
    trace_id: str = ""
    detail: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)


__all__ = [
    "AuditEvent",
    "Project",
    "ProjectContextInfo",
    "ProjectCreate",
    "ProjectQuota",
    "ProjectRole",
    "ProjectStatus",
    "ProjectUpdate",
]
