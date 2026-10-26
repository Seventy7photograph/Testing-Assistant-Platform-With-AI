"""自动化脚本受控 AI 增强的请求、建议与配方模型。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.utils import now_iso

AutomationAIKind = Literal[
    "operation_gap",
    "failure_assertion",
    "fixture_recipe",
    "script_review",
]
AutomationAIStatus = Literal["running", "completed", "failed"]
FindingDisposition = Literal["pending", "accepted", "rejected"]
ReviewDecision = Literal["pending", "accepted", "rejected"]


class AutomationAIRequest(BaseModel):
    kind: AutomationAIKind
    spec_id: str = Field(..., min_length=1, max_length=128)
    artifact_id: str | None = Field(default=None, max_length=128)
    run_id: str | None = Field(default=None, max_length=128)
    focus: str = Field(default="", max_length=500)


class AIAssertionProposal(BaseModel):
    """仅供人工采纳的断言提案，不会自动写入生成资产。"""

    kind: Literal["status", "header", "json"] = "json"
    path: str = ""
    operator: str = ""
    expected: Any = None
    description: str = ""
    source_ref: str = ""


class AutomationAIFinding(BaseModel):
    finding_id: str
    category: Literal[
        "operation_coverage",
        "failure_assertion",
        "fixture_recipe",
        "script_review",
    ]
    severity: Literal["info", "warning"] = "info"
    operation_id: str | None = None
    case_id: str | None = None
    target: str = ""
    issue: str
    suggestion: str = ""
    rationale: str = ""
    source_ref: str = ""
    claim_status: Literal["inferred"] = "inferred"
    disposition: FindingDisposition = "pending"
    proposed_assertion: AIAssertionProposal | None = None


class FixtureEnvironmentVariable(BaseModel):
    name: str
    description: str = ""
    secret: bool = False
    placeholder: str = ""


class FixtureDefinition(BaseModel):
    name: str
    purpose: str = ""
    setup: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


class TestDataRow(BaseModel):
    case_id: str = ""
    title: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""


class AutomationFixtureRecipe(BaseModel):
    summary: str = ""
    environment_variables: list[FixtureEnvironmentVariable] = Field(default_factory=list)
    fixtures: list[FixtureDefinition] = Field(default_factory=list)
    test_data: list[TestDataRow] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    execution_notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AutomationAIMeta(BaseModel):
    requested: bool = True
    used: bool = False
    status: AutomationAIStatus = "running"
    provider: str = ""
    model: str = ""
    prompt_id: str = ""
    prompt_version: str = ""
    temperature: float | None = None
    llm_calls: int = 0
    elapsed_ms: int = 0
    warnings: list[str] = Field(default_factory=list)


class AutomationAIReview(BaseModel):
    review_id: str
    kind: AutomationAIKind
    spec_id: str
    artifact_id: str | None = None
    run_id: str | None = None
    focus: str = ""
    status: AutomationAIStatus = "running"
    summary: str = ""
    findings: list[AutomationAIFinding] = Field(default_factory=list)
    recipe: AutomationFixtureRecipe | None = None
    decision: ReviewDecision = "pending"
    context: dict[str, Any] = Field(default_factory=dict)
    meta: AutomationAIMeta = Field(default_factory=AutomationAIMeta)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class FindingDecisionRequest(BaseModel):
    disposition: Literal["accepted", "rejected"]


class ReviewDecisionRequest(BaseModel):
    decision: Literal["accepted", "rejected"]


__all__ = [
    "AIAssertionProposal",
    "AutomationAIFinding",
    "AutomationAIKind",
    "AutomationAIMeta",
    "AutomationAIRequest",
    "AutomationAIReview",
    "AutomationAIStatus",
    "AutomationFixtureRecipe",
    "FindingDecisionRequest",
    "FixtureDefinition",
    "FixtureEnvironmentVariable",
    "ReviewDecision",
    "ReviewDecisionRequest",
    "TestDataRow",
]
