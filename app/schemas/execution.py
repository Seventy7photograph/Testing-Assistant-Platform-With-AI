"""V2.3 自动化资产、执行结果与结构化事件模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.utils import now_iso


class GeneratedFile(BaseModel):
    """固定模板生成的文本文件；不存二进制或本机绝对路径。"""

    path: str
    content: str
    media_type: str = "text/plain"

    @property
    def size_bytes(self) -> int:
        return len(self.content.encode("utf-8"))


class ValidationIssue(BaseModel):
    code: str
    message: str
    path: str = ""


class AutomationArtifact(BaseModel):
    artifact_id: str
    spec_id: str
    spec_title: str = ""
    parent_artifact_id: str | None = None
    source_review_id: str | None = None
    revision: int = 1
    framework: str = "pytest+httpx"
    template_version: str = "1.0.0"
    case_ids: list[str] = Field(default_factory=list)
    operation_ids: list[str] = Field(default_factory=list)
    files: list[GeneratedFile] = Field(default_factory=list)
    status: Literal["validated", "rejected"] = "validated"
    validation_errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    change_summary: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)

    def summary(self) -> "AutomationArtifactSummary":
        return AutomationArtifactSummary(
            artifact_id=self.artifact_id,
            spec_id=self.spec_id,
            spec_title=self.spec_title,
            parent_artifact_id=self.parent_artifact_id,
            source_review_id=self.source_review_id,
            revision=self.revision,
            framework=self.framework,
            template_version=self.template_version,
            case_count=len(self.case_ids),
            operation_count=len(self.operation_ids),
            file_count=len(self.files),
            total_bytes=sum(item.size_bytes for item in self.files),
            status=self.status,
            validation_errors=self.validation_errors,
            warnings=self.warnings,
            change_summary=self.change_summary,
            created_at=self.created_at,
        )


class AutomationArtifactSummary(BaseModel):
    artifact_id: str
    spec_id: str
    spec_title: str = ""
    parent_artifact_id: str | None = None
    source_review_id: str | None = None
    revision: int = 1
    framework: str = "pytest+httpx"
    template_version: str = "1.0.0"
    case_count: int = 0
    operation_count: int = 0
    file_count: int = 0
    total_bytes: int = 0
    status: Literal["validated", "rejected"] = "validated"
    validation_errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    change_summary: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class AutomationCreateRequest(BaseModel):
    spec_id: str = Field(..., min_length=1, max_length=128)
    case_ids: list[str] = Field(default_factory=list, max_length=2000)


class AutomationCaseSummary(BaseModel):
    case_id: str
    title: str
    method: str
    path: str
    operation_id: str
    category: Literal["positive", "negative", "boundary", "security", "contract"]
    priority: str
    risk: Literal["read", "write", "destructive"]
    required_variables: list[str] = Field(default_factory=list)
    assertion_count: int = 0
    manual_assertion_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class AutomationArtifactCaseList(BaseModel):
    artifact_id: str
    cases: list[AutomationCaseSummary] = Field(default_factory=list)
    missing_case_ids: list[str] = Field(default_factory=list)


class CaseResult(BaseModel):
    case_id: str | None = None
    name: str = ""
    classname: str = ""
    status: Literal["passed", "failed", "error", "skipped"] = "passed"
    duration_ms: int = 0
    operation_id: str | None = None
    message: str = ""
    stdout: str = ""
    stderr: str = ""


class TestRun(BaseModel):
    run_id: str
    artifact_id: str | None = None
    spec_id: str | None = None
    source_file: str = ""
    source_hash: str = ""
    framework: str = "junit"
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    matched: int = 0
    unmatched: int = 0
    duration_ms: int = 0
    cases: list[CaseResult] = Field(default_factory=list)
    unmatched_cases: list[CaseResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    raw_xml: str = ""
    created_at: str = Field(default_factory=now_iso)

    @property
    def pass_rate(self) -> float:
        executed = self.passed + self.failed + self.errors
        return self.passed / executed if executed else 0.0

    def summary(self) -> "TestRunSummary":
        return TestRunSummary(
            run_id=self.run_id,
            artifact_id=self.artifact_id,
            spec_id=self.spec_id,
            source_file=self.source_file,
            total=self.total,
            passed=self.passed,
            failed=self.failed,
            errors=self.errors,
            skipped=self.skipped,
            matched=self.matched,
            unmatched=self.unmatched,
            pass_rate=round(self.pass_rate, 4),
            duration_ms=self.duration_ms,
            warnings=self.warnings,
            created_at=self.created_at,
        )


class TestRunSummary(BaseModel):
    run_id: str
    artifact_id: str | None = None
    spec_id: str | None = None
    source_file: str = ""
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    matched: int = 0
    unmatched: int = 0
    pass_rate: float = 0.0
    duration_ms: int = 0
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class JobEvent(BaseModel):
    event_id: str
    trace_id: str
    action: str
    status: str
    artifact_id: str | None = None
    run_id: str | None = None
    work_item_id: str | None = None
    project_id: str = ""
    job_id: str = ""
    level: str = "info"
    message: str = ""
    created_at: str = Field(default_factory=now_iso)


__all__ = [
    "AutomationArtifact",
    "AutomationArtifactCaseList",
    "AutomationArtifactSummary",
    "AutomationCaseSummary",
    "AutomationCreateRequest",
    "CaseResult",
    "GeneratedFile",
    "JobEvent",
    "TestRun",
    "TestRunSummary",
    "ValidationIssue",
]
