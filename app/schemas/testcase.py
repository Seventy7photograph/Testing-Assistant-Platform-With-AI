"""测试用例模型与用例集统计模型。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.core.utils import now_iso
from app.schemas.common import CaseSource, CaseType, DesignMethod, Priority
from app.schemas.requirement import ClaimStatus, ParseMeta


class TestStep(BaseModel):
    """操作步骤。expected 为空表示"沿用用例级预期结果"。"""

    no: int
    action: str
    expected: str = ""


class TestCase(BaseModel):
    """单条测试用例。字段设计对齐禅道/Jira/XMind 的通用导入模板。"""

    case_id: str = Field(default="", description="用例编号，由设计引擎统一分配")
    title: str
    module: str = "默认模块"
    requirement_ids: list[str] = Field(default_factory=list)
    design_method: DesignMethod = DesignMethod.EQUIVALENCE
    case_type: CaseType = CaseType.FUNCTIONAL
    priority: Priority = Priority.P2
    preconditions: list[str] = Field(default_factory=list)
    steps: list[TestStep] = Field(default_factory=list)
    expected_result: str = ""
    test_data: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    remarks: str = ""
    source: CaseSource = CaseSource.RULE
    checksum: str = Field(default="", description="去重指纹")
    covered_methods: list[DesignMethod] = Field(
        default_factory=list,
        description="覆盖该用例的全部设计方法（去重合并后记录，说明该用例来源不唯一）",
    )
    evidence_quotes: list[str] = Field(default_factory=list)
    claim_status: ClaimStatus = ClaimStatus.VERIFIED
    uncertainty_reason: str = ""

    def step_text(self) -> str:
        """把步骤压平成一行文本（Excel/CSV 单元格友好）。"""
        if not self.steps:
            return ""
        lines: list[str] = []
        for step in self.steps:
            text = f"{step.no}. {step.action}"
            if step.expected:
                text += f" -> 预期：{step.expected}"
            lines.append(text)
        return "\n".join(lines)

    def data_text(self) -> str:
        if not self.test_data:
            return ""
        return "\n".join(f"{key} = {value}" for key, value in self.test_data.items())


class SuiteStats(BaseModel):
    total: int = 0
    duplicate_removed: int = 0
    by_method: dict[str, int] = Field(default_factory=dict)
    by_covered_method: dict[str, int] = Field(
        default_factory=dict,
        description="按覆盖方法统计：去重合并后一条用例可能同时覆盖多种方法，因此各项之和可大于用例总数。",
    )
    by_type: dict[str, int] = Field(default_factory=dict)
    by_priority: dict[str, int] = Field(default_factory=dict)
    requirement_coverage: dict[str, int] = Field(default_factory=dict)


class GenerationMeta(BaseModel):
    methods: list[str] = Field(default_factory=list)
    llm_used: bool = False
    llm_provider: str = "rule"
    llm_model: str = ""
    #: 本次生成阶段实际调用模型的次数（0 表示纯规则引擎）。
    llm_calls: int = Field(default=0, description="生成阶段调用大模型的次数，用于费用与耗时追溯")
    fallback_used: bool = False
    warnings: list[str] = Field(default_factory=list)
    #: 大模型对「规则引擎产出」的复核意见（只提意见，不自动改写用例）。
    review_findings: list["ReviewFinding"] = Field(default_factory=list)
    elapsed_ms: int = 0
    prompt_runs: list[dict[str, Any]] = Field(default_factory=list)
    validation_failures: list[str] = Field(default_factory=list)
    unreviewed_requirements: list[str] = Field(default_factory=list)
    evidence_counts: dict[str, int] = Field(default_factory=dict)


class ReviewFinding(BaseModel):
    """大模型复核规则用例时给出的一条意见。

    刻意**不**让模型直接改写用例：规则用例是确定性的产物，一旦被模型改写，
    使用者就无法判断哪条是规则结论、哪条是模型判断，整份用例集的可信度都会打折。
    因此复核结果只作为「意见」单独呈现，改不改由人决定。
    """

    severity: str = Field(default="info", description="info | warning")
    requirement_id: str = ""
    requirement_title: str = ""
    target: str = Field(default="", description="指向的用例标题 / 字段名 / 需求条目")
    target_type: str = Field(default="", description="requirement | field | case")
    target_id: str = ""
    issue: str = Field(default="", description="发现的问题")
    suggestion: str = Field(default="", description="建议怎么改")
    evidence_quotes: list[str] = Field(default_factory=list)
    claim_status: ClaimStatus = ClaimStatus.INFERRED
    uncertainty_reason: str = ""


class TestCaseSuite(BaseModel):
    """一次生成产生的用例集合（同时是 Excel 导出的数据源）。"""

    suite_id: str
    doc_id: str
    doc_title: str = ""
    revision: int = Field(
        default=0,
        description="同一条需求下的第几个版本（V2.0 起由 Repository.save_suite 分配，0 表示未分配）",
    )
    methods: list[DesignMethod] = Field(default_factory=list)
    cases: list[TestCase] = Field(default_factory=list)
    stats: SuiteStats = Field(default_factory=SuiteStats)
    generation_meta: GenerationMeta = Field(default_factory=GenerationMeta)
    parse_meta: ParseMeta = Field(
        default_factory=ParseMeta,
        description="需求解析阶段的口径快照，供导出/展示区分「解析用 LLM」与「生成用 LLM」",
    )
    external_links: list[dict[str, Any]] = Field(
        default_factory=list,
        description="外部需求/测试平台回写记录（v3.0）",
    )
    created_at: str = Field(default_factory=now_iso)

    def recount(self) -> SuiteStats:
        """重算统计口径（去重后调用）。"""
        by_method: dict[str, int] = {}
        by_covered: dict[str, int] = {}
        by_type: dict[str, int] = {}
        by_priority: dict[str, int] = {}
        coverage: dict[str, int] = {}
        for case in self.cases:
            by_method[case.design_method.label] = by_method.get(case.design_method.label, 0) + 1
            for method in case.covered_methods or [case.design_method]:
                by_covered[method.label] = by_covered.get(method.label, 0) + 1
            by_type[case.case_type.value] = by_type.get(case.case_type.value, 0) + 1
            by_priority[case.priority.value] = by_priority.get(case.priority.value, 0) + 1
            for req_id in case.requirement_ids:
                coverage[req_id] = coverage.get(req_id, 0) + 1
        self.stats.by_method = by_method
        self.stats.by_covered_method = by_covered
        self.stats.by_type = by_type
        self.stats.by_priority = by_priority
        self.stats.requirement_coverage = dict(sorted(coverage.items()))
        self.stats.total = len(self.cases)
        return self.stats

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def summary(self) -> "TestCaseSuiteSummary":
        """投影为列表项：列表页只统计不读用例，没必要把成百上千条用例塞进响应。"""
        return TestCaseSuiteSummary(
            suite_id=self.suite_id,
            doc_id=self.doc_id,
            doc_title=self.doc_title,
            revision=self.revision,
            methods=self.methods,
            stats=self.stats,
            generation_meta=self.generation_meta,
            parse_meta=self.parse_meta,
            created_at=self.created_at,
        )


class TestCaseSuiteSummary(BaseModel):
    """用例集列表项：与 TestCaseSuite 同口径，但**不含 cases**。

    用途：`GET /testcases/suites` 与首页「最近用例集」。列表只需要 `stats` 与元信息，
    带上全部用例会让响应体积随用例数线性膨胀（50 份用例集可达数百 KB）。
    需要用例明细时走 `GET /testcases/{suite_id}`。
    """

    suite_id: str
    doc_id: str
    doc_title: str = ""
    revision: int = 0
    methods: list[DesignMethod] = Field(default_factory=list)
    stats: SuiteStats = Field(default_factory=SuiteStats)
    generation_meta: GenerationMeta = Field(default_factory=GenerationMeta)
    parse_meta: ParseMeta = Field(default_factory=ParseMeta)
    created_at: str = Field(default_factory=now_iso)
