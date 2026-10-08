"""结构化需求模型。

链路：非结构化文档 --(解析 + LLM/规则抽取)--> RequirementDoc --(设计引擎)--> TestCaseSuite

该模型是整条流水线的"中间表示(IR)"，设计引擎只依赖它，
因此更换 LLM、更换文档格式都不会影响设计方法本身。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.core.utils import now_iso
from app.schemas.common import DataType, Priority, RequirementType, ValueCharset


class FieldConstraint(BaseModel):
    """字段级约束：等价类/边界值分析算法的输入。"""

    name: str = Field(..., description="字段名")
    label: str = Field(default="", description="字段中文名/别名")
    data_type: DataType = DataType.STRING
    required: bool = False
    nullable: bool = True
    min_value: float | None = None
    max_value: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    enum_values: list[str] = Field(default_factory=list)
    pattern: str | None = None
    default: str | None = None
    unit: str | None = None
    value_charset: ValueCharset = Field(
        default=ValueCharset.TEXT,
        description="长度类字段的测试数据字符集：text(字母) / digits(数字)",
    )
    description: str = ""

    @field_validator("enum_values", mode="before")
    @classmethod
    def _coerce_enum_values(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
        return [str(item) for item in value]

    @property
    def display_name(self) -> str:
        return self.label or self.name

    @property
    def has_numeric_range(self) -> bool:
        return self.min_value is not None or self.max_value is not None

    @property
    def has_length_range(self) -> bool:
        return self.min_length is not None or self.max_length is not None

    @property
    def data_charset(self) -> ValueCharset:
        """数据构造使用的字符集：显式声明优先，纯数值类型一律按数字处理。"""
        if self.value_charset is ValueCharset.DIGITS:
            return ValueCharset.DIGITS
        if self.data_type in (DataType.INTEGER, DataType.FLOAT):
            return ValueCharset.DIGITS
        return ValueCharset.TEXT

    def describe_constraint(self) -> str:
        """把约束描述成人类可读文本，用于生成用例预期结果。"""
        parts: list[str] = []
        if self.required:
            parts.append("必填")
        if self.enum_values:
            parts.append("取值必须是 " + "/".join(self.enum_values) + " 之一")
        if self.has_numeric_range:
            left = "不限" if self.min_value is None else f"{_num(self.min_value)}"
            right = "不限" if self.max_value is None else f"{_num(self.max_value)}"
            unit = self.unit or ""
            parts.append(f"取值范围 {left}~{right}{unit}")
        if self.has_length_range:
            left = self.min_length if self.min_length is not None else "-"
            right = self.max_length if self.max_length is not None else "-"
            parts.append(f"长度 {left}~{right}")
        if self.pattern:
            parts.append(f"需匹配格式 {self.pattern}")
        if not parts and self.description:
            parts.append(self.description)
        return "，".join(parts)


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


class RequirementItem(BaseModel):
    """单条需求（通常对应一个功能点或一条业务规则）。"""

    id: str
    title: str
    module: str = "默认模块"
    description: str = ""
    priority: Priority = Priority.P2
    requirement_type: RequirementType = RequirementType.FUNCTION
    fields: list[FieldConstraint] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    main_flow: list[str] = Field(default_factory=list)
    alternative_flows: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    source_ref: str = Field(default="", description="来源锚点，如摘要/章节标题")
    raw_text: str = Field(default="", description="该条需求的原文片段，便于人工回溯")

    @property
    def testable_fields(self) -> list[FieldConstraint]:
        """有实际可测约束的字段（无约束的纯文本字段会被设计引擎降级处理）。"""
        return [f for f in self.fields if f.name]

    @property
    def flows(self) -> list[str]:
        return [*self.main_flow, *self.alternative_flows]


class ParseMeta(BaseModel):
    """解析过程元信息：可观测性 > 黑盒。"""

    provider: str = "rule"
    model: str = ""
    llm_used: bool = False
    fallback_used: bool = False
    fallback_reason: str = ""
    attempts: int = 0
    elapsed_ms: int = 0
    item_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class RequirementDoc(BaseModel):
    """一份需求文档的结构化表示。"""

    doc_id: str
    title: str = "未命名需求文档"
    source_file: str = ""
    source_type: str = "text"
    version: str = "1.0"
    summary: str = ""
    items: list[RequirementItem] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    parse_meta: ParseMeta = Field(default_factory=ParseMeta)

    @property
    def item_count(self) -> int:
        return len(self.items)

    @property
    def field_count(self) -> int:
        return sum(len(item.fields) for item in self.items)

    def get_item(self, item_id: str) -> RequirementItem | None:
        return next((item for item in self.items if item.id == item_id), None)

    def compact_summary(self, limit: int = 200) -> str:
        from app.core.utils import truncate

        return truncate(self.summary or self.title, limit)