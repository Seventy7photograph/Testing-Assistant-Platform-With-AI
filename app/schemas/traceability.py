"""需求变更差异与需求-用例追溯模型（V2.0 S5）。

差异模型回答「这次改版改了什么」，追溯模型回答「这条需求被哪些用例覆盖、
这条用例又是为哪条需求写的」。
"""
from __future__ import annotations

from pydantic import BaseModel, Field, computed_field


class FieldChange(BaseModel):
    """字段级变更：哪个字段的哪个属性从什么变成了什么。"""

    field: str = Field(..., description="字段名")
    attribute: str = Field(..., description="发生变化的属性，如 min_value / required")
    before: str = ""
    after: str = ""

    def describe(self) -> str:
        return f"{self.field}.{self.attribute}: {self.before or '（空）'} -> {self.after or '（空）'}"


class RequirementChange(BaseModel):
    """一条需求条目的变更。"""

    kind: str = Field(..., description="added / removed / modified")
    requirement_id: str = ""
    title: str = ""
    detail: str = ""
    field_changes: list[FieldChange] = Field(default_factory=list)
    changed_sections: list[str] = Field(
        default_factory=list, description="发生变化的非字段部分：业务规则 / 主流程 / 验收标准…"
    )


class RequirementDiff(BaseModel):
    """两个版本需求模型的差异报告。"""

    doc_id: str = ""
    older_doc_id: str = ""
    newer_doc_id: str = ""
    older_title: str = ""
    newer_title: str = ""
    added: list[RequirementChange] = Field(default_factory=list)
    removed: list[RequirementChange] = Field(default_factory=list)
    modified: list[RequirementChange] = Field(default_factory=list)
    unchanged: int = 0
    summary: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def changed_count(self) -> int:
        """变更总数：界面用它决定「要不要展开差异面板」，因此必须进响应体。"""
        return len(self.added) + len(self.removed) + len(self.modified)


class TraceCase(BaseModel):
    """追溯矩阵里的一格：一条用例。"""

    case_id: str = ""
    title: str = ""
    design_method: str = ""
    case_type: str = ""
    priority: str = ""


class RequirementTrace(BaseModel):
    """正向：需求条目 -> 用例。"""

    requirement_id: str
    requirement_title: str
    module: str = ""
    case_count: int = 0
    cases: list[TraceCase] = Field(default_factory=list)


class CaseTrace(BaseModel):
    """反向：用例 -> 需求条目。"""

    case_id: str = ""
    title: str = ""
    design_method: str = ""
    suite_id: str = ""
    requirement_ids: list[str] = Field(default_factory=list)
    resolved_requirement_ids: list[str] = Field(default_factory=list)
    missing_requirement_ids: list[str] = Field(
        default_factory=list, description="用例标注了、但在需求模型里找不到的需求 ID"
    )


class TraceabilityMatrix(BaseModel):
    """需求-用例双向追溯矩阵。"""

    doc_id: str
    doc_title: str = ""
    suite_ids: list[str] = Field(default_factory=list)
    requirements: list[RequirementTrace] = Field(default_factory=list)
    cases: list[CaseTrace] = Field(default_factory=list)
    uncovered_requirement_ids: list[str] = Field(default_factory=list)
    orphan_case_ids: list[str] = Field(default_factory=list)
    summary: str = ""
