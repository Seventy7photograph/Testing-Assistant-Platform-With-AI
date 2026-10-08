"""场景法策略。

规则部分基于需求模型中的 主流程 / 备选流程 / 异常场景 / 业务规则 直接构造用例；
在 use_llm 且 Provider 可用时，额外调用一次 LLM 补充"易漏场景"
（并发、弱网、权限、幂等、状态时序等），失败自动降级为纯规则结果。
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.exceptions import LLMError
from app.core.logging import get_logger
from app.core.utils import dump_json, truncate
from app.design.base import (
    DesignStrategy,
    fill_value,
    make_single_step,
    pattern_is_digit_only,
    pattern_sample,
)
from app.llm.prompts import build_scenario_messages
from app.schemas.common import CaseSource, CaseType, DesignMethod, Priority, ValueCharset
from app.schemas.requirement import FieldConstraint, RequirementItem
from app.schemas.testcase import TestCase, TestStep

logger = get_logger(__name__)

DEFAULT_MAX_LLM_CASES = 5

_TYPE_MAP = {
    "功能": CaseType.FUNCTIONAL,
    "边界": CaseType.BOUNDARY,
    "异常": CaseType.EXCEPTION,
    "场景": CaseType.SCENARIO,
    "安全": CaseType.SECURITY,
    "性能": CaseType.PERFORMANCE,
    "兼容性": CaseType.COMPATIBILITY,
    "functional": CaseType.FUNCTIONAL,
    "boundary": CaseType.BOUNDARY,
    "exception": CaseType.EXCEPTION,
    "scenario": CaseType.SCENARIO,
}


class _LLMStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: str = ""
    expected: str = ""

    @field_validator("action", "expected", mode="before")
    @classmethod
    def _to_text(cls, value: Any) -> str:
        return "" if value is None else str(value)


class _LLMScenarioCase(BaseModel):
    """LLM 返回用例的宽松模型：字段缺失不报错，统一在转换阶段降级处理。"""

    model_config = ConfigDict(extra="ignore")

    title: str = ""
    case_type: str = "场景"
    priority: str = "P2"
    preconditions: list[str] = Field(default_factory=list)
    steps: list[_LLMStep] = Field(default_factory=list)
    expected_result: str = ""
    test_data: dict[str, str] = Field(default_factory=dict)

    @field_validator("title", "expected_result", mode="before")
    @classmethod
    def _to_text(cls, value: Any) -> str:
        return "" if value is None else str(value)

    @field_validator("preconditions", mode="before")
    @classmethod
    def _to_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        return [str(item) for item in value]

    @field_validator("steps", mode="before")
    @classmethod
    def _to_steps(cls, value: Any) -> list[Any]:
        if value is None:
            return []
        result: list[Any] = []
        for item in value:
            if isinstance(item, str):
                result.append({"action": item, "expected": ""})
            else:
                result.append(item)
        return result

    @field_validator("test_data", mode="before")
    @classmethod
    def _to_data(cls, value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        return {str(key): "" if item is None else str(item) for key, item in value.items()}


class ScenarioStrategy(DesignStrategy):
    method = DesignMethod.SCENARIO
    description = "基于主流程/备选流程/异常场景生成端到端用例，可选 LLM 补充易漏场景"

    def is_applicable(self, item: RequirementItem) -> bool:
        return bool(
            item.main_flow
            or item.alternative_flows
            or item.exceptions
            or item.business_rules
            or item.description
        )

    async def generate(self, item: RequirementItem) -> list[TestCase]:
        cases = self._rule_cases(item)
        if self.context.llm_ready:
            cases.extend(await self._llm_cases(item, cases))
        return self.too_many(cases)

    # ------------------------------------------------------------------ #
    # 规则部分
    # ------------------------------------------------------------------ #
    def _rule_cases(self, item: RequirementItem) -> list[TestCase]:
        cases: list[TestCase] = []
        acceptance = item.acceptance_criteria[0] if item.acceptance_criteria else ""

        if item.main_flow:
            cases.append(
                self.build_case(
                    item,
                    title=f"[场景] {item.title}｜主流程（正常场景）",
                    case_type=CaseType.SCENARIO,
                    steps=[TestStep(no=index, action=step) for index, step in enumerate(item.main_flow, start=1)],
                    expected_result=acceptance or "主流程各步骤执行成功，业务目标达成",
                    remarks="场景法：基本流（Happy Path）",
                    tags=["主流程", "基本流"],
                )
            )
        else:
            cases.append(
                self.build_case(
                    item,
                    title=f"[场景] {item.title}｜主流程（正常场景）",
                    case_type=CaseType.SCENARIO,
                    steps=make_single_step(
                        action=f"按需求描述执行「{truncate(item.description or item.title, 80)}」的正常业务流程",
                        expected="业务流程执行成功",
                    ),
                    expected_result=acceptance or "业务目标达成",
                    remarks="场景法：基本流（由需求描述推导，建议人工细化步骤）",
                    tags=["主流程", "基本流"],
                )
            )

        for index, flow in enumerate(item.alternative_flows, start=1):
            cases.append(
                self.build_case(
                    item,
                    title=f"[场景] {item.title}｜备选流 {index}：{truncate(flow, 40)}",
                    case_type=CaseType.SCENARIO,
                    steps=make_single_step(action=flow, expected="系统按备选流程正确分支处理"),
                    expected_result=acceptance or "分支流程按需求预期执行，数据一致",
                    remarks="场景法：备选流",
                    tags=["备选流"],
                )
            )

        for index, exception in enumerate(item.exceptions, start=1):
            cases.append(
                self.build_case(
                    item,
                    title=f"[场景] {item.title}｜异常场景 {index}：{truncate(exception, 40)}",
                    case_type=CaseType.EXCEPTION,
                    priority=item.priority,
                    steps=make_single_step(
                        action=f"构造异常条件：{exception}",
                        expected="系统捕获异常并给出可读提示，保持数据一致（可回滚）",
                    ),
                    expected_result=f"发生「{exception}」时系统有明确兜底策略，不产生脏数据。",
                    remarks="场景法：异常流",
                    tags=["异常流"],
                )
            )

        for index, rule in enumerate(item.business_rules, start=1):
            cases.append(
                self.build_case(
                    item,
                    title=f"[场景] {item.title}｜业务规则 {index}：{truncate(rule, 40)}",
                    case_type=CaseType.FUNCTIONAL,
                    steps=make_single_step(
                        action=f"构造满足/不满足业务规则的输入验证：{rule}",
                        expected="规则命中时按预期拦截或放行",
                    ),
                    expected_result=f"业务规则「{truncate(rule, 60)}」被正确执行。",
                    remarks="场景法：业务规则校验",
                    tags=["业务规则"],
                )
            )
        return cases

    # ------------------------------------------------------------------ #
    # LLM 增强部分
    # ------------------------------------------------------------------ #
    async def _llm_cases(self, item: RequirementItem, existing: list[TestCase]) -> list[TestCase]:
        max_cases = min(DEFAULT_MAX_LLM_CASES, max(self.context.max_cases_per_item - len(existing), 0))
        if max_cases <= 0:
            return []

        payload = item.model_dump(mode="json")
        messages = build_scenario_messages(
            payload,
            existing_titles=[case.title for case in existing],
            max_cases=max_cases,
        )
        try:
            self.context.llm_call_count += 1
            response = await self.context.llm.complete_json(messages, expect=dict)
        except LLMError as exc:
            self.context.warn(f"场景法 LLM 增强失败（{exc.code}），已降级为规则用例：{exc.message}")
            return []

        raw_cases = (response.parsed or {}).get("cases")
        if not isinstance(raw_cases, list):
            self.context.warn("场景法 LLM 返回缺少 cases 数组，已忽略该次增强结果。")
            return []

        cases: list[TestCase] = []
        skipped = 0
        for raw in raw_cases[:max_cases]:
            try:
                parsed = _LLMScenarioCase.model_validate(raw)
            except ValidationError:
                skipped += 1
                continue
            if not parsed.title.strip():
                skipped += 1
                continue
            cases.append(self._to_test_case(item, parsed))
        if skipped:
            self.context.warn(f"场景法 LLM 结果中有 {skipped} 条用例字段缺失被丢弃（已保留其余结果）。")
        return cases

    def _to_test_case(self, item: RequirementItem, parsed: _LLMScenarioCase) -> TestCase:
        case_type = to_case_type(parsed.case_type)
        steps = [
            TestStep(no=index, action=step.action or "（模型未给出步骤，请人工补充）", expected=step.expected)
            for index, step in enumerate(parsed.steps, start=1)
        ]
        if not steps:
            steps = make_single_step(action=f"按用例「{parsed.title}」执行", expected="")

        test_data = dict(parsed.test_data)
        test_data, repairs = repair_test_data(item, test_data, case_type)
        if repairs:
            self.context.warn(
                f"场景法 LLM 用例「{truncate(parsed.title, 30)}」的测试数据与字段约束不一致，已按约束修正："
                + "；".join(repairs)
                + "。如与用例意图不符请人工复核。"
            )

        return self.build_case(
            item,
            title=f"[场景-LLM] {parsed.title}",
            case_type=case_type,
            priority=to_priority(parsed.priority, fallback=item.priority),
            preconditions=parsed.preconditions or item.preconditions,
            steps=steps,
            expected_result=parsed.expected_result or "（模型未给出预期结果，请人工确认）",
            test_data=test_data,
            remarks="场景法 LLM 增强用例（" + dump_json({"requirement": item.id}, indent=None) + "），需人工复核。",
            tags=["LLM增强", "需复核"],
            source=CaseSource.LLM,
        )


# 这些用例类型代表「正常路径」，其测试数据必须满足字段自身约束；
# 异常用例本就以越界数据为输入，不做一致性校验。
_VALID_CASE_TYPES = frozenset({CaseType.FUNCTIONAL, CaseType.BOUNDARY, CaseType.SCENARIO})


def _index_fields(item: RequirementItem) -> dict[str, FieldConstraint]:
    """按字段名与字段中文标签建立索引，兼容 LLM 用标签当 key 的情况。"""
    fields: dict[str, FieldConstraint] = {}
    for field in item.fields:
        fields.setdefault(field.name, field)
        if field.label:
            fields.setdefault(field.label, field)
    return fields


def _charset_for(field: FieldConstraint) -> ValueCharset:
    if field.data_charset == ValueCharset.DIGITS or pattern_is_digit_only(field.pattern):
        return ValueCharset.DIGITS
    return ValueCharset.TEXT


def _clamp_length(field: FieldConstraint, length: int) -> int:
    if field.min_length is not None:
        length = max(length, field.min_length)
    if field.max_length is not None:
        length = min(length, field.max_length)
    return max(length, 0)


def _evaluate(field: FieldConstraint, name: str, value: str) -> tuple[str | None, str | None]:
    """检查单个字段值，返回 (问题描述, 修正后的合法值)。

    无问题时返回 ``(None, None)``。修正策略：先按正则取内置样例或按字符集填充，
    再按 min_length 补足、max_length 截断，保证修正值重新满足字段自身约束。
    """
    issue: str | None = None
    fixed = value
    if field.pattern:
        try:
            matched = re.fullmatch(field.pattern, value) is not None
        except re.error:
            matched = True
        if not matched:
            issue = f"{name}=「{truncate(value, 16)}」不符合格式 {field.pattern}"
            sample = pattern_sample(field.pattern)
            fixed = sample if sample is not None else fill_value(
                _clamp_length(field, len(value)), _charset_for(field)
            )
    if field.min_length is not None and len(fixed) < field.min_length:
        issue = issue or f"{name}=「{truncate(value, 16)}」长度小于最小长度 {field.min_length}"
        fixed = fixed + fill_value(field.min_length - len(fixed), _charset_for(field))
    elif field.max_length is not None and len(fixed) > field.max_length:
        issue = issue or f"{name}=「{truncate(value, 16)}」长度超过最大长度 {field.max_length}"
        fixed = fixed[: field.max_length]
    if issue is None:
        return None, None
    return issue, fixed


def describe_test_data_issues(
    item: RequirementItem, test_data: dict[str, str], case_type: CaseType
) -> list[str]:
    """检查 LLM 给出的测试数据是否满足字段约束，返回人类可读的问题列表。

    LLM 偶尔会在「正常/边界」用例里塞入违反 min_length 或正则的数据
    （如退款原因只写 4 个字），若不提示，用例会带着自相矛盾的数据进入交付物。
    """
    if case_type not in _VALID_CASE_TYPES:
        return []

    fields = _index_fields(item)
    issues: list[str] = []
    for name, value in test_data.items():
        field = fields.get(name)
        if field is None or not value:
            continue
        issue, _ = _evaluate(field, name, value)
        if issue:
            issues.append(issue)
    return issues


def repair_test_data(
    item: RequirementItem, test_data: dict[str, str], case_type: CaseType
) -> tuple[dict[str, str], list[str]]:
    """把「正常/边界」用例中违反字段约束的测试数据修正为合法值。

    LLM 生成的场景用例偶尔会给出越界数据（如邀请码长度 12 而约束上限 10），
    这类数据会让"正常用例"自相矛盾；这里按字段约束裁剪/补全，返回 (修正后数据, 修正说明)。

    异常用例本就用越界数据，不做修正。
    """
    if case_type not in _VALID_CASE_TYPES:
        return dict(test_data), []

    fields = _index_fields(item)
    repaired = dict(test_data)
    notes: list[str] = []
    for name, value in test_data.items():
        field = fields.get(name)
        if field is None or not value:
            continue
        issue, fixed = _evaluate(field, name, value)
        if issue and fixed is not None:
            repaired[name] = fixed
            notes.append(issue + f"，已修正为「{truncate(fixed, 16)}」")
    return repaired, notes


def to_case_type(value: str) -> CaseType:
    return _TYPE_MAP.get((value or "").strip().lower(), CaseType.SCENARIO)


def to_priority(value: str, *, fallback: Priority) -> Priority:
    text = (value or "").strip().upper()
    return Priority(text) if text in Priority._value2member_map_ else fallback
