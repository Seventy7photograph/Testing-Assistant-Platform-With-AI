"""v3.0 只读助手契约。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.knowledge import KnowledgeCitation


class AssistantAskRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    current_path: str = Field(default="", max_length=500)
    conversation_id: str = Field(default="", max_length=128)
    allow_web_search: bool = True


class AssistantLink(BaseModel):
    label: str
    href: str
    resource_type: str = ""
    resource_id: str = ""


class AssistantClaim(BaseModel):
    text: str
    evidence: str = ""


class AssistantFactGroup(BaseModel):
    label: str
    claims: list[AssistantClaim] = Field(default_factory=list)


class WebCitation(BaseModel):
    citation_id: str
    title: str
    url: str
    site_name: str = ""
    snippet: str = ""
    summary: str = ""
    content_excerpt: str = ""
    published_at: str = ""
    authority: int = -1
    rerank_score: float = 0.0
    fetched: bool = False


class AssistantTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: str
    status: Literal["answered", "refused", "degraded", ""] = ""
    mode: Literal["deterministic", "llm_assisted", "web_assisted", ""] = ""
    knowledge_references: list[KnowledgeCitation] = Field(default_factory=list)
    web_citations: list[WebCitation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    degraded_reason: str = ""


class AssistantConversation(BaseModel):
    conversation_id: str
    project_id: str
    title: str = ""
    turn_count: int = 0
    web_search_count: int = 0
    last_web_search_at: str = ""
    messages: list[AssistantTurn] = Field(default_factory=list)
    created_at: str
    updated_at: str


class AssistantConversationSummary(BaseModel):
    conversation_id: str
    title: str = ""
    turn_count: int = 0
    web_search_count: int = 0
    updated_at: str


class AssistantAnswer(BaseModel):
    run_id: str
    conversation_id: str = ""
    turn_index: int = 1
    turn_limit: int = 30
    context_messages: int = 0
    status: Literal["answered", "refused", "degraded"] = "answered"
    answer: str
    mode: Literal["deterministic", "llm_assisted", "web_assisted"] = "deterministic"
    current_facts: list[AssistantFactGroup] = Field(default_factory=list)
    knowledge_references: list[KnowledgeCitation] = Field(default_factory=list)
    web_citations: list[WebCitation] = Field(default_factory=list)
    web_search_used: bool = False
    web_search_status: str = ""
    model_inferences: list[AssistantClaim] = Field(default_factory=list)
    links: list[AssistantLink] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    degraded_reason: str = ""


class ToolCatalogItem(BaseModel):
    name: str
    description: str
    readonly: bool = True
    category: str = "platform"


class AssistantStatus(BaseModel):
    model_available: bool = False
    model_provider: str = ""
    model_name: str = ""
    model_reason: str = ""
    web_search_available: bool = False
    web_search_provider: str = ""
    web_search_reason: str = ""
    max_turns: int = 30
    context_turns: int = 12
    context_chars: int = 24_000
    rate_limit_per_minute: int = 8
    web_searches_per_conversation: int = 8
    web_fetch_limit: int = 2
    web_fetch_chars: int = 12_000
    max_output_tokens: int = 8192


__all__ = [
    "AssistantAnswer",
    "AssistantAskRequest",
    "AssistantClaim",
    "AssistantFactGroup",
    "AssistantLink",
    "AssistantConversation",
    "AssistantConversationSummary",
    "AssistantStatus",
    "AssistantTurn",
    "ToolCatalogItem",
    "WebCitation",
]
