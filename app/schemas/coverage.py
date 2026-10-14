"""覆盖率分析模型（V2.0 S4）。

三个维度分别回答三个不同的问题：
  - **字段**：「这个字段有没有被测到？」—— 一个字段一条用例都没有，是最严重的漏测；
  - **边界**：「边界点测全了吗？」—— 字段被测到不等于边界被取到，
    只测了中间值会漏掉 off-by-one 一类缺陷；
  - **规则**：「业务规则/流程都有对应用例吗？」—— 字段都覆盖了，业务规则仍可能漏。

缺口一律带上「需求条目 + 具体目标」，不带定位的覆盖率报告只能看不能改。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CoverageItem(BaseModel):
    """一条被覆盖（或未覆盖）的具体目标。"""

    requirement_id: str = ""
    requirement_title: str = ""
    target: str = Field(default="", description="字段名 / 边界点描述 / 规则原文")
    detail: str = Field(default="", description="补充说明，如该边界点的取值")


class CoverageDimension(BaseModel):
    """一个维度的覆盖情况。"""

    key: str
    label: str
    total: int = 0
    covered: int = 0
    ratio: float = 0.0
    note: str = Field(default="", description="该维度的口径说明或不可用原因")
    gaps: list[CoverageItem] = Field(default_factory=list)


class CoverageReport(BaseModel):
    """一份用例集相对其源需求的覆盖率报告。"""

    doc_id: str
    doc_title: str = ""
    suite_id: str
    dimensions: list[CoverageDimension] = Field(default_factory=list)
    overall_ratio: float = 0.0
    summary: str = ""

    def dimension(self, key: str) -> CoverageDimension | None:
        return next((item for item in self.dimensions if item.key == key), None)
