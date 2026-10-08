"""需求解析服务：文档/文本 -> 结构化需求模型（RequirementDoc）。

链路（两段式 LLM 调用的第一段）：
    文本 --[LLM 结构化抽取]--> RequirementDoc
         --[LLM 不可用/失败]--> 规则解析器兜底（rule_parser）

关键异常路径策略：
    1. LLM 网络/接口错误        -> 降级规则解析，并在 parse_meta 标注原因；
    2. LLM 返回非 JSON          -> 由 provider 内置重试修复，仍失败则降级；
    3. LLM 返回字段缺失         -> 宽松模型校验，缺失项用默认值补齐；
    4. LLM 未解析出任何条目     -> 降级规则解析；
    5. 规则解析也失败（空文档） -> 抛 EmptyDocumentError，由 API 返回明确提示。
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.config import Settings, get_settings
from app.core.exceptions import EmptyDocumentError, LLMError
from app.core.logging import get_logger
from app.core.utils import Timer, new_id, truncate
from app.llm.base import LLMProvider
from app.llm.factory import get_llm_provider
from app.llm.prompts import build_requirement_messages
from app.repository import Repository, get_repository
from app.schemas.common import DataType, Priority, RequirementType, ValueCharset
from app.schemas.requirement import FieldConstraint, ParseMeta, RequirementDoc, RequirementItem
from app.services import rule_parser

logger = get_logger(__name__)

DATA_TYPE_MAP: dict[str, DataType] = {
    "string": DataType.STRING,
    "str": DataType.STRING,
    "字符串": DataType.STRING,
    "文本": DataType.STRING,
    "integer": DataType.INTEGER,
    "int": DataType.INTEGER,
    "整数": DataType.INTEGER,
    "整型": DataType.INTEGER,
    "float": DataType.FLOAT,
    "double": DataType.FLOAT,
    "decimal": DataType.FLOAT,
    "小数": DataType.FLOAT,
    "数值": DataType.FLOAT,
    "金额": DataType.FLOAT,
    "boolean": DataType.BOOLEAN,
    "bool": DataType.BOOLEAN,
    "布尔": DataType.BOOLEAN,
    "enum": DataType.ENUM,
    "枚举": DataType.ENUM,
    "date": DataType.DATE,
    "日期": DataType.DATE,
    "datetime": DataType.DATETIME,
    "时间": DataType.DATETIME,
    "other": DataType.OTHER,
}

REQUIREMENT_TYPE_MAP: dict[str, RequirementType] = {
    "functional": RequirementType.FUNCTION,
    "function": RequirementType.FUNCTION,
    "功能": RequirementType.FUNCTION,
    "business_rule": RequirementType.BUSINESS_RULE,
    "业务规则": RequirementType.BUSINESS_RULE,
    "interface": RequirementType.INTERFACE,
    "接口": RequirementType.INTERFACE,
    "constraint": RequirementType.CONSTRAINT,
    "约束": RequirementType.CONSTRAINT,
    "non_functional": RequirementType.NON_FUNCTIONAL,
    "非功能": RequirementType.NON_FUNCTIONAL,
}

TRUE_WORDS = {"是", "y", "yes", "true", "1", "必填", "必输", "required"}


# --------------------------------------------------------------------------- #
# 宽松校验模型：LLM 返回字段缺失/类型漂移时自动兜底，不直接抛错
# --------------------------------------------------------------------------- #
class _LLMField(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    label: str = ""
    data_type: str = "string"
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
    description: str = ""

    @field_validator("name", "label", "description", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()

    @field_validator("data_type", mode="before")
    @classmethod
    def _data_type(cls, value: Any) -> str:
        return DATA_TYPE_MAP.get(str(value or "string").strip().lower(), DataType.STRING).value

    @field_validator("required", "nullable", mode="before")
    @classmethod
    def _bool(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in TRUE_WORDS

    @field_validator("enum_values", mode="before")
    @classmethod
    def _enum(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            parts = [item.strip() for item in value.replace("，", ",").split(",")]
            return [item for item in parts if item]
        return [str(item) for item in value]

    @field_validator("min_value", "max_value", mode="before")
    @classmethod
    def _number(cls, value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(str(value).strip().rstrip("岁个位元次"))
        except (TypeError, ValueError):
            return None

    @field_validator("min_length", "max_length", mode="before")
    @classmethod
    def _int(cls, value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(float(str(value).strip().rstrip("位个字符")))
        except (TypeError, ValueError):
            return None

    @field_validator("pattern", "default", "unit", mode="before")
    @classmethod
    def _optional_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


# LLM 常把「11位数字」这类自然语言描述塞进 pattern 字段，而不是给出真正的正则。
# 含中文的一定不是正则，直接当格式约束使用会产出「有效数据却违反格式」的假缺陷。
_NATURAL_LANGUAGE_PATTERN_RE = re.compile(r"[\u4e00-\u9fff]")


def _is_usable_regex(pattern: str) -> bool:
    """判断 LLM 给出的 pattern 是否为可用的正则表达式。"""
    if not pattern or _NATURAL_LANGUAGE_PATTERN_RE.search(pattern):
        return False
    try:
        re.compile(pattern)
    except re.error:
        return False
    return True


def _interpret_natural_pattern(raw: _LLMField) -> tuple[str | None, int | None, int | None, ValueCharset]:
    """把自然语言格式描述（「11位数字」「长度5~200」）还原成结构化约束。

    复用规则解析器：它能识别长度与数字字符集，并补上手机号 / 身份证 / 邮编等内置正则，
    避免 LLM 措辞差异直接污染测试数据与展示。
    """
    parsed = rule_parser.build_field_constraint(
        name=raw.name,
        type_text=raw.data_type,
        required=raw.required,
        constraint_text=raw.pattern or "",
        default=raw.default,
        description=raw.description or raw.pattern or "",
    )
    return parsed.pattern, parsed.min_length, parsed.max_length, parsed.value_charset


def _text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [item.strip() for item in value.replace("；", "\n").split("\n")]
        return [item for item in parts if item]
    return [str(item).strip() for item in value if str(item).strip()]


class _LLMItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    title: str = ""
    module: str = ""
    description: str = ""
    priority: str = "P2"
    requirement_type: str = "functional"
    fields: list[_LLMField] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    main_flow: list[str] = Field(default_factory=list)
    alternative_flows: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    source_ref: str = ""

    @field_validator("id", "title", "module", "description", "priority", "requirement_type", "source_ref", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()

    @field_validator(
        "business_rules",
        "preconditions",
        "main_flow",
        "alternative_flows",
        "exceptions",
        "acceptance_criteria",
        mode="before",
    )
    @classmethod
    def _list(cls, value: Any) -> list[str]:
        return _text_list(value)


class _LLMDoc(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    summary: str = ""
    items: list[_LLMItem] = Field(default_factory=list)

    @field_validator("title", "summary", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()


# --------------------------------------------------------------------------- #
class RequirementService:
    """需求解析服务。"""

    def __init__(
        self,
        settings: Settings | None = None,
        llm: LLMProvider | None = None,
        repository: Repository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm or get_llm_provider()
        self.repository = repository or get_repository()

    # ------------------------------------------------------------------ #
    async def parse_text(
        self,
        text: str,
        *,
        title: str = "粘贴的需求文本",
        doc_id: str | None = None,
        source_file: str = "",
        source_type: str = "text",
        use_llm: bool = True,
        max_items: int = 8,
        persist: bool = True,
    ) -> RequirementDoc:
        if not (text or "").strip():
            raise EmptyDocumentError("需求内容为空，请检查文档或粘贴文本。")

        doc_id = doc_id or new_id("DOC-")
        with Timer() as timer:
            doc = await self._build_doc(
                text=text,
                title=title,
                doc_id=doc_id,
                source_file=source_file,
                source_type=source_type,
                use_llm=use_llm,
                max_items=max_items,
            )
        doc.parse_meta.elapsed_ms = timer.elapsed_ms
        doc.parse_meta.item_count = doc.item_count

        if persist:
            self.repository.requirements.save(doc)
        logger.info(
            "需求解析完成：doc=%s 条目=%d 字段=%d provider=%s 耗时=%dms",
            doc.doc_id,
            doc.item_count,
            doc.field_count,
            doc.parse_meta.provider,
            timer.elapsed_ms,
        )
        return doc

    async def parse_document(
        self,
        doc_id: str,
        *,
        title: str | None = None,
        use_llm: bool = True,
        max_items: int = 8,
    ) -> RequirementDoc:
        record = self.repository.documents.get(doc_id)
        return await self.parse_text(
            record.text,
            title=title or record.filename,
            doc_id=record.doc_id,
            source_file=record.filename,
            source_type=record.extension,
            use_llm=use_llm,
            max_items=max_items,
        )

    def get(self, doc_id: str) -> RequirementDoc:
        return self.repository.requirements.get(doc_id)

    # ------------------------------------------------------------------ #
    async def _build_doc(
        self,
        *,
        text: str,
        title: str,
        doc_id: str,
        source_file: str,
        source_type: str,
        use_llm: bool,
        max_items: int,
    ) -> RequirementDoc:
        meta = ParseMeta()
        if use_llm and self.llm.available:
            try:
                doc = await self._parse_with_llm(text, title=title, doc_id=doc_id, max_items=max_items)
                doc.source_file = source_file or title
                doc.source_type = source_type
                return doc
            except LLMError as exc:
                logger.warning("LLM 需求解析失败，降级规则解析：%s", exc.message)
                meta.fallback_used = True
                meta.fallback_reason = f"LLM 解析失败（{exc.code}）：{exc.message}"
        elif use_llm:
            meta.fallback_used = True
            meta.fallback_reason = self.llm.degraded_reason or "未启用大模型"

        doc = self._parse_with_rules(text, title=title, doc_id=doc_id, max_items=max_items)
        doc.source_file = source_file or title
        doc.source_type = source_type
        doc.parse_meta.fallback_used = meta.fallback_used
        doc.parse_meta.fallback_reason = meta.fallback_reason
        if meta.fallback_reason:
            doc.parse_meta.warnings.append("已使用规则引擎解析：" + meta.fallback_reason)
        return doc

    # ------------------------------------------------------------------ #
    async def _parse_with_llm(self, text: str, *, title: str, doc_id: str, max_items: int) -> RequirementDoc:
        messages = build_requirement_messages(text, title=title, max_items=max_items)
        response = await self.llm.complete_json(messages, expect=dict)
        payload = response.parsed or {}
        try:
            parsed_doc = _LLMDoc.model_validate(payload)
        except ValidationError as exc:
            raise LLMError(f"LLM 返回结构不符合预期：{exc.error_count()} 处校验失败") from exc

        field_warnings: list[str] = []
        items = [
            self._to_item(raw, index, field_warnings)
            for index, raw in enumerate(parsed_doc.items[:max_items], start=1)
        ]
        items = [item for item in items if item.title]
        if not items:
            raise LLMError("LLM 未解析出任何需求条目（items 为空），已降级规则解析。")

        rule_doc = self._parse_with_rules(text, title=title, doc_id=doc_id, max_items=max_items)
        enriched = self._merge_rule_fields(items, rule_doc.items)

        return RequirementDoc(
            doc_id=doc_id,
            title=parsed_doc.title or title,
            source_file=title,
            summary=parsed_doc.summary or rule_doc.summary,
            items=enriched,
            parse_meta=ParseMeta(
                provider=self.llm.name,
                model=self.llm.model,
                llm_used=True,
                fallback_used=False,
                attempts=response.attempts,
                warnings=list(rule_doc.parse_meta.warnings) + field_warnings,
            ),
        )

    def _to_item(self, raw: _LLMItem, index: int, warnings: list[str] | None = None) -> RequirementItem:
        fields = [self._to_field(field, warnings) for field in raw.fields]
        fields = [field for field in fields if field.name]
        return RequirementItem(
            id=raw.id or f"REQ-{index:03d}",
            title=raw.title or f"需求条目 {index}",
            module=raw.module or "默认模块",
            description=truncate(raw.description, 600),
            priority=_to_priority(raw.priority),
            requirement_type=REQUIREMENT_TYPE_MAP.get(raw.requirement_type.lower(), RequirementType.FUNCTION),
            fields=fields,
            business_rules=raw.business_rules,
            preconditions=raw.preconditions,
            main_flow=raw.main_flow,
            alternative_flows=raw.alternative_flows,
            exceptions=raw.exceptions,
            acceptance_criteria=raw.acceptance_criteria,
            source_ref=raw.source_ref,
        )

    @staticmethod
    def _to_field(raw: _LLMField, warnings: list[str] | None = None) -> FieldConstraint:
        enum_values = raw.enum_values
        data_type = DataType(raw.data_type)
        if enum_values:
            data_type = DataType.ENUM

        pattern = raw.pattern
        min_length = raw.min_length
        max_length = raw.max_length
        charset = ValueCharset.TEXT
        if pattern and not _is_usable_regex(pattern):
            inferred_pattern, inferred_min, inferred_max, inferred_charset = _interpret_natural_pattern(raw)
            if min_length is None:
                min_length = inferred_min
            if max_length is None:
                max_length = inferred_max
            charset = inferred_charset
            pattern = inferred_pattern
            message = (
                f"字段「{raw.label or raw.name}」的格式描述「{raw.pattern}」不是合法正则，"
                "已按长度/字符集约束处理。"
            )
            logger.info(message)
            if warnings is not None and message not in warnings:
                warnings.append(message)

        if charset is ValueCharset.TEXT and pattern and rule_parser.is_digit_charset(raw.name, "", pattern):
            # 内置格式本身只接受数字（如手机号）时，数据构造也应按数字填充。
            charset = ValueCharset.DIGITS

        return FieldConstraint(
            name=raw.name,
            label=raw.label or raw.name,
            data_type=data_type,
            required=raw.required,
            nullable=raw.nullable if not raw.required else False,
            min_value=raw.min_value,
            max_value=raw.max_value,
            min_length=min_length,
            max_length=max_length,
            enum_values=enum_values,
            pattern=pattern,
            default=raw.default,
            unit=raw.unit,
            value_charset=charset,
            description=raw.description,
        )

    @staticmethod
    def _merge_rule_fields(llm_items: list[RequirementItem], rule_items: list[RequirementItem]) -> list[RequirementItem]:
        """LLM 未给出字段约束时，用规则解析结果补齐（两路互补，提高召回）。"""
        if not rule_items:
            return llm_items
        pool = list(rule_items)
        for item in llm_items:
            if item.fields:
                continue
            best, score = _best_match(item.title, pool)
            if best is not None and score >= 0.4:
                item.fields = list(best.fields)
                if not item.main_flow and best.main_flow:
                    item.main_flow = list(best.main_flow)
                if not item.business_rules and best.business_rules:
                    item.business_rules = list(best.business_rules)
        return llm_items

    # ------------------------------------------------------------------ #
    def _parse_with_rules(self, text: str, *, title: str, doc_id: str, max_items: int) -> RequirementDoc:
        doc_title, summary, items, warnings = rule_parser.parse_requirements(
            text, doc_title=title, max_items=max_items
        )
        return RequirementDoc(
            doc_id=doc_id,
            title=doc_title or title,
            source_file=title,
            summary=summary,
            items=items,
            parse_meta=ParseMeta(
                provider="rule",
                model="",
                llm_used=False,
                fallback_used=False,
                warnings=warnings,
            ),
        )


def _to_priority(value: str) -> Priority:
    text = (value or "").strip().upper()
    return Priority(text) if text in Priority._value2member_map_ else Priority.P2


def _best_match(title: str, pool: list[RequirementItem]) -> tuple[RequirementItem | None, float]:
    best: RequirementItem | None = None
    best_score = 0.0
    for candidate in pool:
        score = SequenceMatcher(None, title, candidate.title).ratio()
        if score > best_score:
            best, best_score = candidate, score
    return best, best_score
