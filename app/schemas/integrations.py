"""v3.0 外部需求同步契约。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.utils import now_iso
from app.schemas.document import DocumentSummary

IntegrationName = Literal["jira", "zentao"]


class ExternalRequirement(BaseModel):
    external_id: str
    title: str
    body: str
    status: str = ""
    url: str = ""
    version: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExternalStatus(BaseModel):
    external_id: str
    status: str
    title: str = ""
    updated_at: str = ""
    url: str = ""


class IntegrationSyncRequest(BaseModel):
    project_key: str = Field(default="", max_length=120)
    options: dict[str, Any] = Field(default_factory=dict)


class IntegrationPullResult(BaseModel):
    integration: str
    fetched: int = 0
    created: int = 0
    updated: int = 0
    requirements: list[ExternalRequirement] = Field(default_factory=list)
    documents: list[DocumentSummary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class IntegrationPushRequest(IntegrationSyncRequest):
    issue_key: str = ""
    create_issue: bool = True


class IntegrationPushResult(BaseModel):
    integration: str
    suite_id: str
    external_ids: list[str] = Field(default_factory=list)
    message: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class IntegrationHealth(BaseModel):
    name: str
    label: str
    implemented: bool = True
    configured: bool = False
    available: bool = False
    message: str = ""
    degraded_reason: str = ""


__all__ = [
    "ExternalRequirement",
    "ExternalStatus",
    "IntegrationHealth",
    "IntegrationName",
    "IntegrationPullResult",
    "IntegrationPushRequest",
    "IntegrationPushResult",
    "IntegrationSyncRequest",
]
