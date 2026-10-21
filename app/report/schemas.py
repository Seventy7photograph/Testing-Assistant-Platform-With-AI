"""测试报告模块的 API 数据结构（Pydantic 模型）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .config import DEFAULT_INSTRUCTION

Verdict = Literal["pass", "conditional", "reject", "unknown"]


# ------------------------------------------------------------------ 指标

class CountItem(BaseModel):
    """一项分布统计。"""

    key: str
    label: str
    count: int


class Defect(BaseModel):
    id: str | None = None
    title: str | None = None
    priority: str | None = None
    module: str | None = None
    status: str | None = None
    status_raw: str | None = None


class Metrics(BaseModel):
    """服务端确定性算出的指标。前端只做格式化，不做计算。"""

    total: int = 0
    passed: int = 0
    failed: int = 0
    blocked: int = 0
    skipped: int = 0
    executed: int = 0

    pass_rate: float = 0.0
    fail_rate: float = 0.0
    execution_rate: float = 0.0
    effective_pass_rate: float = 0.0

    defects_total: int = 0
    defects_open: int = 0
    open_p0: int = 0
    open_p1: int = 0

    by_priority: list[CountItem] = Field(default_factory=list)
    by_status: list[CountItem] = Field(default_factory=list)
    by_module: list[CountItem] = Field(default_factory=list)

    verdict: Verdict = "unknown"
    verdict_label: str = "无法判定"
    verdict_reasons: list[str] = Field(default_factory=list)


class MetricsResult(BaseModel):
    """指标计算结果：可能算不出来，此时说明原因。"""

    metrics: Metrics | None = None
    defects: list[Defect] = Field(default_factory=list)
    version: str | None = None
    source_format: Literal["json", "text"] = "text"
    warnings: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------ 请求

class AnalyzeRequest(BaseModel):
    test_data: str = Field(..., min_length=1, description="测试结果文本或 JSON")
    instruction: str = Field(default=DEFAULT_INSTRUCTION, description="额外分析要求")
    model: str | None = Field(default=None, description="覆盖默认模型")
    temperature: float | None = Field(default=None, ge=0, le=2)
    title: str | None = Field(default=None, description="报告标题，缺省时取版本号")
    save: bool = Field(default=True, description="是否写入本地存档")


class MetricsRequest(BaseModel):
    test_data: str = Field(default="", description="测试结果文本或 JSON")


# ------------------------------------------------------------------ 响应

class AnalyzeResponse(BaseModel):
    id: str | None = None
    report: str
    model: str
    provider: str
    metrics: Metrics | None = None
    warnings: list[str] = Field(default_factory=list)
    version: str | None = None
    created_at: str
    elapsed_ms: int
    usage: dict[str, Any] | None = None
    prompt_id: str = ""
    prompt_version: str = ""
    prompt_temperature: float | None = None


class ReportSummary(BaseModel):
    """存档列表项：不带正文，避免列表接口过重。"""

    id: str
    title: str | None = None
    version: str | None = None
    model: str
    provider: str = ""
    created_at: str
    elapsed_ms: int = 0
    verdict: Verdict = "unknown"
    verdict_label: str = "无法判定"
    pass_rate: float | None = None
    total: int | None = None
    failed: int | None = None
    blocked: int | None = None
    excerpt: str = ""


class ReportDetail(ReportSummary):
    instruction: str = ""
    source_data: str = ""
    report: str = ""
    metrics: Metrics | None = None
    defects: list[Defect] = Field(default_factory=list)
    usage: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


class ReportListResponse(BaseModel):
    items: list[ReportSummary]
    total: int


class TrendPoint(BaseModel):
    id: str
    label: str
    created_at: str
    pass_rate: float
    total: int
    failed: int
    blocked: int
    verdict: Verdict
    verdict_label: str


class SampleDataset(BaseModel):
    id: str
    name: str
    description: str
    content: str


class DeleteResponse(BaseModel):
    deleted: bool
    id: str


class ReportLLMTestResponse(BaseModel):
    ok: bool
    model: str
    provider: str
    latency_ms: int = 0
    message: str


# ------------------------------------------------------------------ 阈值配置

class ThresholdView(BaseModel):
    """发版判定阈值 + 每项来源，界面据此显示「已保存」或「.env 默认」。"""

    thresholds: dict[str, float] = Field(default_factory=dict)
    defaults: dict[str, float] = Field(default_factory=dict)
    sources: dict[str, str] = Field(default_factory=dict)


class ThresholdUpdate(BaseModel):
    """阈值更新：字段缺省表示不改动；显式传 null 表示恢复该项到 .env。"""

    fail_rate: float | None = Field(default=None, ge=0, le=1)
    blocked_rate: float | None = Field(default=None, ge=0, le=1)
    execution_floor: float | None = Field(default=None, ge=0, le=1)
    pass_line: float | None = Field(default=None, ge=0, le=1)
    reset: bool = Field(default=False, description="为真时清空全部覆盖，回到 .env 默认")
