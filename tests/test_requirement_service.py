"""LLM 字段归一化回归：真实模型常把自然语言写进 pattern 字段。

缺陷背景：DeepSeek 对「取值范围：11位数字」的字段会返回 ``pattern="11位数字"``
（而不是正则），导致等价类/边界值产出 AAAAAAAAAAA 这类「有效却非法」的数据，
展示上还会出现「需匹配格式 11位数字」。这里校验归一化后的约束与数据。
"""
from __future__ import annotations

import re

from app.core.config import get_settings
from app.design.base import DesignContext
from app.design.equivalence import EquivalenceStrategy
from app.llm.null_provider import NullProvider
from app.schemas.common import CaseType, ValueCharset
from app.schemas.requirement import RequirementItem
from app.services.requirement_service import RequirementService, _LLMField


def _field(**kwargs) -> _LLMField:
    return _LLMField(**kwargs)


def test_natural_language_pattern_becomes_length_and_digits() -> None:
    """「6位数字」不是正则：应还原为长度约束与数字字符集，而不是当格式使用。"""
    warnings: list[str] = []
    field = RequirementService._to_field(
        _field(name="验证码", label="验证码", pattern="6位数字", min_length=6, max_length=6),
        warnings,
    )
    assert field.pattern is None
    assert (field.min_length, field.max_length) == (6, 6)
    assert field.data_charset is ValueCharset.DIGITS
    assert warnings and "不是合法正则" in warnings[0]


def test_natural_language_pattern_recovers_builtin_regex() -> None:
    """手机号「11位数字」应补回内置手机号正则，有效数据才能通过校验。"""
    field = RequirementService._to_field(_field(name="手机号", label="手机号", pattern="11位数字"))
    assert field.pattern == r"^1[3-9]\d{9}$"
    assert (field.min_length, field.max_length) == (11, 11)
    assert field.data_charset is ValueCharset.DIGITS


def test_natural_language_length_range_is_parsed() -> None:
    """「长度5~200」这类描述应还原为长度区间。"""
    field = RequirementService._to_field(_field(name="退款原因", label="退款原因", pattern="长度5~200"))
    assert field.pattern is None
    assert (field.min_length, field.max_length) == (5, 200)


def test_real_regex_is_kept() -> None:
    """真正的正则必须原样保留。"""
    field = RequirementService._to_field(_field(name="订单号", label="订单号", pattern=r"^\d{12}$"))
    assert field.pattern == r"^\d{12}$"


def test_invalid_regex_is_dropped() -> None:
    """无法编译的伪正则不应残留，避免污染展示与数据构造。"""
    field = RequirementService._to_field(_field(name="备注", label="备注", pattern="[unclosed"))
    assert field.pattern is None


def test_field_without_pattern_is_untouched() -> None:
    field = RequirementService._to_field(_field(name="昵称", label="昵称", min_length=2, max_length=20))
    assert field.pattern is None
    assert (field.min_length, field.max_length) == (2, 20)


async def test_normalized_field_yields_conforming_valid_data() -> None:
    """端到端：归一化后的手机号字段，其「有效等价类」数据必须满足自身正则。"""
    settings = get_settings()
    field = RequirementService._to_field(
        _field(name="手机号", label="手机号", pattern="11位数字", required=True)
    )
    item = RequirementItem(id="REQ-001", title="注册", fields=[field])
    context = DesignContext(settings=settings, llm=NullProvider(settings), use_llm=False)

    cases = await EquivalenceStrategy(context).generate(item)
    valid = [
        case.test_data["手机号"]
        for case in cases
        if case.case_type is CaseType.FUNCTIONAL and case.test_data.get("手机号")
    ]
    assert valid, "应至少产出一条有效等价类用例"
    assert all(re.fullmatch(field.pattern or "", value) for value in valid), valid
