"""v3.0 合并版知识库契约。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.utils import now_iso

KnowledgeSourceType = Literal[
    "document",
    "case",
    "defect",
    "report",
    "help",
    "api_spec",
    "runbook",
]
KnowledgeStatus = Literal["active", "expired", "deleted"]


class KnowledgeSource(BaseModel):
    source_id: str
    project_id: str
    source_type: KnowledgeSourceType
    resource_id: str
    title: str
    version: str = ""
    status: KnowledgeStatus = "active"
    content_hash: str = ""
    citation_url: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: str = Field(default_factory=now_iso)


class KnowledgeChunk(BaseModel):
    chunk_id: str
    source_id: str
    project_id: str
    ordinal: int = 0
    locator: str = ""
    text: str
    content_hash: str = ""


class KnowledgeCitation(BaseModel):
    citation_id: str
    source_id: str
    title: str
    source_type: KnowledgeSourceType
    version: str = ""
    locator: str = ""
    url: str = ""
    excerpt: str = ""
    score: float = 0.0


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    source_types: list[KnowledgeSourceType] = Field(default_factory=list)
    limit: int = Field(default=8, ge=1, le=30)
    include_expired: bool = False


class KnowledgeSearchResult(BaseModel):
    query: str
    citations: list[KnowledgeCitation] = Field(default_factory=list)
    total: int = 0
    degraded_reason: str = ""


class KnowledgeIndexStats(BaseModel):
    project_id: str
    sources: int = 0
    active_sources: int = 0
    chunks: int = 0
    indexed: int = 0
    removed: int = 0
    degraded_reason: str = ""
    updated_at: str = Field(default_factory=now_iso)


__all__ = [
    "KnowledgeChunk",
    "KnowledgeCitation",
    "KnowledgeIndexStats",
    "KnowledgeSearchRequest",
    "KnowledgeSearchResult",
    "KnowledgeSource",
    "KnowledgeSourceType",
    "KnowledgeStatus",
]
