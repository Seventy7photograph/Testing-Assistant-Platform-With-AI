"""生成阶段的「大模型复核与补缺」。

定位：**模型不重写规则结果，只提意见、补空白**。

规则引擎（等价类 / 边界值 / 判定表 / 因果图 / 正交实验）的产出是确定、可复现、可离线核对的，
这是本项目的立身之本；模型的价值在于规则天生做不好的三件事：

  1. 判断「这套字段约束背后真实的业务语义」有没有漏测（如字段级枚举之外的状态组合）；
  2. 指出规则用例内部的自相矛盾（数据违反自身约束、预期与业务规则打架）；
  3. 补上真实业务里一定会发生、但规则方法覆盖不到的场景（并发、权限、幂等、状态时序、脏数据）。

因此本模块的产物有两类，且**各自带来源标记**：
  - ``ReviewFinding``：复核意见，只呈现、不自动改写任何规则用例；
  - ``TestCase(source=LLM)``：补充用例，标题带 ``[LLM补充]``、标签带「需复核」，
    并挂到模型指定的设计方法下（于是按方法的统计里能看出模型贡献了什么）。

一次调用处理**一条需求**（同时产出意见与补充），而不是每个方法调一次 ——
六个方法各调一次，一份 5 条需求的文档就是 30 次请求，成本与耗时都失控。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.exceptions import LLMError
from app.core.logging import get_logger
from app.core.utils import truncate
from app.design.base import DesignContext
from app.design.scenario import repair_test_data, to_case_type, to_priority
from app.llm.base import user
from app.llm.prompt_registry import PROMPT_GENERATION_REVIEW
from app.llm.prompts import build_review_messages
from app.schemas.common import CaseSource, CaseType, DesignMethod
from app.schemas.requirement import ClaimStatus, RequirementItem
from app.schemas.testcase import ReviewFinding, TestCase, TestStep
from app.services.evidence import (
    quote_in_source,
    requirement_source_text,
    validate_review_target,
)

logger = get_logger(__name__)

#: 每条需求的补充用例上限：再多就该回到规则引擎去补条件，而不是让模型继续编。
MAX_EXTRA_CASES = 5

#: 塞进 Prompt 的规则用例摘要长度上限（防止一条用例集把上下文吃满）。
MAX_DIGEST_CHARS = 4000

TITLE_PREFIX = "[LLM补充]"

REVIEW_TAGS = ["LLM补充", "需复核"]


class _LLMFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    severity: str = "info"
    target: str = ""
    target_type: str = ""
    target_id: str = ""
    issue: str = ""
    suggestion: str = ""
    evidence_quotes: list[str] = Field(default_factory=list)
    claim_status: str = ClaimStatus.INFERRED.value
    uncertainty_reason: str = ""

    @field_validator("severity", mode="before")
    @classmethod
    def _severity(cls, value: Any) -> str:
        text = str(value or "info").strip().lower()
        return text if text in {"info", "warning"} else "info"

    @field_validator("target", "target_type", "target_id", "issue", "suggestion", "uncertainty_reason", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()

    @field_validator("evidence_quotes", mode="before")
    @classmethod
    def _quotes(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        return [str(item).strip() for item in value if str(item).strip()]


class _LLMStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: str = ""
    expected: str = ""

    @field_validator("action", "expected", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return "" if value is None else str(value)


class _LLMReviewCase(BaseModel):
    """宽松模型：模型字段缺失/类型漂移时降级处理，不整批丢弃。"""

    model_config = ConfigDict(extra="ignore")

    title: str = ""
    method: str = ""
    case_type: str = "场景"
    priority: str = "P2"
    preconditions: list[str] = Field(default_factory=list)
    steps: list[_LLMStep] = Field(default_factory=list)
    expected_result: str = ""
    test_data: dict[str, str] = Field(default_factory=dict)
    reason: str = ""
    evidence_quotes: list[str] = Field(default_factory=list)
    claim_status: str = ClaimStatus.INFERRED.value
    uncertainty_reason: str = ""

    @field_validator("title", "method", "expected_result", "reason", "uncertainty_reason", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()

    @field_validator("evidence_quotes", mode="before")
    @classmethod
    def _quotes(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        return [str(item).strip() for item in value if str(item).strip()]

    @field_validator("preconditions", mode="before")
    @classmethod
    def _list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        return [str(item) for item in value]

    @field_validator("steps", mode="before")
    @classmethod
    def _steps(cls, value: Any) -> list[Any]:
        if value is None:
            return []
        return [{"action": item, "expected": ""} if isinstance(item, str) else item for item in value]

    @field_validator("test_data", mode="before")
    @classmethod
    def _data(cls, value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        return {str(key): "" if item is None else str(item) for key, item in value.items()}


def build_case_digest(cases: list[TestCase], *, limit: int = MAX_DIGEST_CHARS) -> str:
    """把规则用例压成一段紧凑摘要：标题 / 方法 / 数据 / 预期。

    只给标题，模型没法判断"数据是否违反约束"；给全文又太贵。摘要取这四项的折中。
    """
    lines: list[str] = []
    for case in cases:
        data = "、".join(f"{key}={value or '(空)'}" for key, value in case.test_data.items()) or "（无）"
        lines.append(
            f"- {case.case_id or '（未编号）'}｜{case.design_method.label}｜{case.case_type.value}"
            f"｜{truncate(case.title, 60)}\n  数据：{truncate(data, 120)}\n  预期：{truncate(case.expected_result, 120)}"
        )
    digest = "\n".join(lines)
    return truncate(digest, limit, suffix="\n…（用例较多，已截断）")


def known_field_names(item: RequirementItem) -> set[str]:
    names: set[str] = set()
    for field in item.testable_fields:
        names.add(field.name)
        if field.label:
            names.add(field.label)
    return names


def sanitize_test_data(item: RequirementItem, data: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """把模型给的测试数据收敛到"需求里真实存在的字段"。

    模型最常见的越界行为是编造字段名（如给一个不存在的 `user_id` 配数据），
    这类数据会直接进用例集、进 Excel，看起来还很像真的。这里直接丢弃 + 记告警。
    """
    known = known_field_names(item)
    kept: dict[str, str] = {}
    dropped: list[str] = []
    for key, value in data.items():
        if key in known:
            kept[key] = value
        else:
            dropped.append(key)
    return kept, dropped


def resolve_method(raw: str, *, default: DesignMethod = DesignMethod.SCENARIO) -> DesignMethod:
    try:
        return DesignMethod(str(raw).strip().lower())
    except ValueError:
        return default


def to_test_case(
    item: RequirementItem,
    parsed: _LLMReviewCase,
    context: DesignContext,
) -> TestCase | None:
    """把模型返回的一条补充用例转成领域模型；不可用时返回 None。"""
    title = parsed.title.strip()
    if not title:
        return None
    method = resolve_method(parsed.method)
    case_type = to_case_type(parsed.case_type)
    test_data, dropped = sanitize_test_data(item, dict(parsed.test_data))
    if dropped:
        context.warn(
            f"大模型为需求「{item.title}」补充的用例引用了需求里没有的字段（{'、'.join(dropped)}），"
            "已丢弃这些测试数据。"
        )
    # 正常/边界类用例的数据必须满足字段自身约束：否则会产出"断言成功、实际被拒"的假用例。
    repaired, repairs = repair_test_data(item, test_data, case_type)
    if repairs:
        context.warn(
            f"大模型补充用例「{truncate(title, 30)}」的数据与字段约束不一致，已按约束修正："
            + "；".join(repairs)
        )

    steps = [
        TestStep(no=index, action=step.action or "（模型未给出步骤，请人工补充）", expected=step.expected)
        for index, step in enumerate(parsed.steps, start=1)
    ] or [TestStep(no=1, action=f"按用例「{title}」执行", expected="")]

    reason = truncate(parsed.reason, 120) or "模型未说明补充理由"
    source = requirement_source_text(item)
    verified_quotes = [
        quote for quote in parsed.evidence_quotes if quote_in_source(quote, source)
    ]
    claim_status = ClaimStatus.VERIFIED if verified_quotes else ClaimStatus.INFERRED
    if not verified_quotes:
        context.warn(
            f"大模型补充用例「{truncate(title, 30)}」未找到原文逐字证据，"
            "已标为模型推断并保留人工复核。"
        )
    return TestCase(
        title=f"{TITLE_PREFIX} {title}",
        module=item.module,
        requirement_ids=[item.id],
        design_method=method,
        case_type=case_type,
        priority=to_priority(parsed.priority, fallback=item.priority),
        preconditions=parsed.preconditions or item.preconditions,
        steps=steps,
        expected_result=parsed.expected_result or "（模型未给出预期结果，请人工确认）",
        test_data=repaired,
        tags=[*REVIEW_TAGS, method.label],
        remarks=f"大模型在复核「{item.title}」时补充。理由：{reason}",
        source=CaseSource.LLM,
        evidence_quotes=verified_quotes[:5],
        claim_status=claim_status,
        uncertainty_reason=(
            "" if verified_quotes else (parsed.uncertainty_reason or "未找到原文逐字证据")
        ),
    )


async def review_item(
    item: RequirementItem,
    cases: list[TestCase],
    *,
    context: DesignContext,
    methods: list[DesignMethod],
    allow_cases: bool,
    max_cases: int = MAX_EXTRA_CASES,
    allow_retry: bool = True,
) -> tuple[list[TestCase], list[ReviewFinding]]:
    """对一条需求的规则产出做一次复核；返回 (补充用例, 复核意见)。"""
    payload = item.model_dump(mode="json")
    messages = build_review_messages(
        payload,
        case_titles=[case.title for case in cases],
        case_digest=build_case_digest(cases),
        methods=[method.value for method in methods],
        allow_cases=allow_cases,
        max_cases=max_cases,
    )
    response = None
    body: dict[str, Any] = {}
    issues: list[str] = []
    for attempt in range(2 if allow_retry else 1):
        try:
            context.llm_call_count += 1
            response = await context.llm.complete_json(
                messages,
                expect=dict,
                prompt=PROMPT_GENERATION_REVIEW,
                retries=0,
            )
        except LLMError as exc:
            context.warn(f"大模型复核失败（{exc.code}），本条需求沿用规则结果：{exc.message}")
            return [], []

        body = response.parsed if isinstance(response.parsed, dict) else {}
        issues = _review_semantic_issues(item, cases, body, allow_cases=allow_cases)
        context.prompt_runs.append(
            {
                "prompt_id": response.prompt_id or PROMPT_GENERATION_REVIEW.prompt_id,
                "prompt_version": response.prompt_version or PROMPT_GENERATION_REVIEW.version,
                "model": response.model or context.llm.model,
                "temperature": response.temperature,
                "route": response.route.as_dict() if response.route else {},
                "requirement_id": item.id,
                "attempt": attempt + 1,
                "validation_failures": issues,
            }
        )
        if not issues:
            break
        context.validation_failures.extend(f"需求 {item.id}：{issue}" for issue in issues)
        if attempt == 0:
            messages = [
                *messages,
                user(
                    "上一次复核输出未通过确定性校验，请只修复以下问题后重新输出完整 JSON：\n- "
                    + "\n- ".join(issues[:20])
                ),
            ]
            if context.llm_call_count >= context.max_llm_calls:
                break

    findings = collect_findings(item, body.get("findings"), context=context, cases=cases)
    if not allow_cases:
        return [], findings

    raw_cases = body.get("cases")
    if not isinstance(raw_cases, list):
        return [], findings

    extra: list[TestCase] = []
    skipped = 0
    for raw in raw_cases[:max_cases]:
        try:
            parsed = _LLMReviewCase.model_validate(raw)
        except ValidationError:
            skipped += 1
            continue
        case = to_test_case(item, parsed, context)
        if case is None:
            skipped += 1
            continue
        extra.append(case)
    if skipped:
        context.warn(f"大模型补充用例中有 {skipped} 条因字段缺失被丢弃（已保留其余结果）。")
    if extra:
        context.warn(
            f"大模型为需求「{item.title}」补充了 {len(extra)} 条用例，均已标记「需复核」，请人工确认后再使用。"
        )
    return extra, findings


def _review_semantic_issues(
    item: RequirementItem,
    cases: list[TestCase],
    body: dict[str, Any],
    *,
    allow_cases: bool,
) -> list[str]:
    issues: list[str] = []
    raw_findings = body.get("findings")
    if raw_findings is not None and not isinstance(raw_findings, list):
        issues.append("findings 必须是数组")
        raw_findings = []
    for index, entry in enumerate(raw_findings or [], start=1):
        try:
            parsed = _LLMFinding.model_validate(entry)
        except ValidationError:
            issues.append(f"findings[{index}] 结构不合法")
            continue
        ok, _ = validate_review_target(
            item,
            cases,
            target=parsed.target,
            target_type=parsed.target_type,
            target_id=parsed.target_id,
        )
        if not ok:
            issues.append(f"findings[{index}] target 未指向真实需求、字段或用例")

    raw_cases = body.get("cases")
    if raw_cases is not None and not isinstance(raw_cases, list):
        issues.append("cases 必须是数组")
        raw_cases = []
    if allow_cases:
        known = known_field_names(item)
        for index, entry in enumerate(raw_cases or [], start=1):
            try:
                parsed_case = _LLMReviewCase.model_validate(entry)
            except ValidationError:
                issues.append(f"cases[{index}] 结构不合法")
                continue
            if not parsed_case.title:
                issues.append(f"cases[{index}] 缺少 title")
            unknown = sorted(set(parsed_case.test_data) - known)
            if unknown:
                issues.append(f"cases[{index}] 引用了不存在的字段：{'、'.join(unknown)}")
    return issues


def collect_findings(
    item: RequirementItem,
    raw: Any,
    *,
    context: DesignContext,
    cases: list[TestCase] | None = None,
    limit: int = 6,
) -> list[ReviewFinding]:
    if not isinstance(raw, list):
        return []
    findings: list[ReviewFinding] = []
    for entry in raw[:limit]:
        try:
            parsed = _LLMFinding.model_validate(entry)
        except ValidationError:
            continue
        if not parsed.issue:
            continue
        ok, target_type = validate_review_target(
            item,
            cases or [],
            target=parsed.target,
            target_type=parsed.target_type,
            target_id=parsed.target_id,
        )
        if not ok:
            context.validation_failures.append(
                f"需求 {item.id} 的复核意见已拒绝：{parsed.target or '缺少 target'}"
            )
            context.warn(
                f"大模型复核意见指向不存在的目标「{parsed.target or '空'}」，已拒绝。"
            )
            continue
        source = requirement_source_text(item)
        verified_quotes = [
            quote for quote in parsed.evidence_quotes if quote_in_source(quote, source)
        ]
        findings.append(
            ReviewFinding(
                severity=parsed.severity,
                requirement_id=item.id,
                requirement_title=item.title,
                target=parsed.target,
                target_type=target_type,
                target_id=parsed.target_id or parsed.target,
                issue=parsed.issue,
                suggestion=parsed.suggestion,
                evidence_quotes=verified_quotes[:5],
                claim_status=ClaimStatus.VERIFIED if verified_quotes else ClaimStatus.INFERRED,
                uncertainty_reason=(
                    ""
                    if verified_quotes
                    else (parsed.uncertainty_reason or "该意见为模型判断，需人工核对")
                ),
            )
        )
    return findings


__all__ = [
    "MAX_DIGEST_CHARS",
    "MAX_EXTRA_CASES",
    "REVIEW_TAGS",
    "TITLE_PREFIX",
    "build_case_digest",
    "collect_findings",
    "known_field_names",
    "resolve_method",
    "review_item",
    "sanitize_test_data",
    "to_test_case",
]
