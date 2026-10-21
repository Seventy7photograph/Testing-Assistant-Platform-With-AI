"""Deterministic evidence checks for model-derived claims.

The model is allowed to propose structure, but only the source document and the
deterministically parsed requirement model can establish facts.  This module
normalizes text conservatively (whitespace, punctuation, full-width forms and
OCR line breaks) and rejects quotes that cannot be found in the source.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from app.schemas.requirement import ClaimStatus, RequirementItem

_NON_CONTENT_RE = re.compile(r"[\W_]+", re.UNICODE)

INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("要求忽略既有指令", re.compile(r"(忽略|无视|忘记).{0,12}(以上|之前|系统|所有).{0,8}(要求|指令|提示)", re.I)),
    ("要求覆盖系统指令", re.compile(r"(覆盖|替换|改变).{0,12}(系统|开发者).{0,6}(指令|提示|角色)", re.I)),
    ("要求输出系统提示词", re.compile(r"(输出|泄露|打印|展示).{0,12}(系统提示词|system prompt|developer message)", re.I)),
    ("英文指令注入", re.compile(r"(ignore|disregard|forget).{0,20}(previous|above|system|developer).{0,20}(instruction|prompt)", re.I)),
    ("角色劫持", re.compile(r"(you are now|act as|从现在开始你是|扮演系统管理员)", re.I)),
    ("密钥窃取", re.compile(r"(api[_ -]?key|secret|token).{0,24}(输出|告诉我|reveal|print)", re.I)),
)


def normalize_evidence(value: str) -> str:
    """Normalize evidence without making matching dangerously fuzzy."""
    text = unicodedata.normalize("NFKC", value or "").casefold()
    return _NON_CONTENT_RE.sub("", text)


def quote_in_source(quote: str, source: str) -> bool:
    normalized_quote = normalize_evidence(quote)
    if len(normalized_quote) < 2:
        return False
    return normalized_quote in normalize_evidence(source)


def source_excerpt(source: str, terms: list[str], *, limit: int = 180) -> str:
    """Return a small source excerpt around the first matching term."""
    raw = source or ""
    for term in terms:
        needle = (term or "").strip()
        if not needle:
            continue
        index = raw.find(needle)
        if index >= 0:
            start = max(index - 40, 0)
            return raw[start : start + limit].strip()
    return ""


def detect_prompt_injection(text: str) -> list[str]:
    warnings: list[str] = []
    for label, pattern in INJECTION_PATTERNS:
        if pattern.search(text or ""):
            warnings.append(f"检测到疑似 Prompt 注入（{label}），已按不可信测试素材处理。")
    return warnings


def requirement_source_text(item: RequirementItem) -> str:
    """Build the deterministic evidence surface for one structured requirement."""
    parts = [
        item.raw_text,
        item.title,
        item.module,
        item.description,
        item.source_ref,
        *item.business_rules,
        *item.preconditions,
        *item.main_flow,
        *item.alternative_flows,
        *item.exceptions,
        *item.acceptance_criteria,
    ]
    for item_field in item.fields:
        parts.extend(
            [
                item_field.name,
                item_field.label,
                item_field.description,
                *item_field.enum_values,
                item_field.pattern or "",
            ]
        )
    return "\n".join(part for part in parts if part)


def _claim_status(value: Any, *, fallback: ClaimStatus = ClaimStatus.INFERRED) -> ClaimStatus:
    try:
        return ClaimStatus(str(value or fallback.value).strip().lower())
    except ValueError:
        return fallback


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(entry).strip() for entry in value if str(entry).strip()]
    return []


@dataclass(slots=True)
class EvidenceIssue:
    path: str
    message: str
    critical: bool = False

    def render(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass(slots=True)
class RequirementGateResult:
    payload: dict[str, Any]
    issues: list[EvidenceIssue] = field(default_factory=list)
    injection_warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def critical_errors(self) -> list[str]:
        return [issue.render() for issue in self.issues if issue.critical]

    @property
    def all_errors(self) -> list[str]:
        return [issue.render() for issue in self.issues]


def _validate_field(field_payload: dict[str, Any], source: str, path: str) -> tuple[dict[str, Any], list[EvidenceIssue], str]:
    issues: list[EvidenceIssue] = []
    name = str(field_payload.get("name") or "").strip()
    label = str(field_payload.get("label") or "").strip()
    if not name:
        issues.append(EvidenceIssue(path, "字段名称为空，已拒绝该字段", critical=True))
        return field_payload, issues, ClaimStatus.REJECTED.value

    quotes = _string_list(field_payload.get("evidence_quotes"))
    name_located = bool(
        normalize_evidence(name) in normalize_evidence(source)
        or (label and normalize_evidence(label) in normalize_evidence(source))
    )
    verified_quotes = [
        quote
        for quote in quotes
        if quote_in_source(quote, source)
        and (
            normalize_evidence(name) in normalize_evidence(quote)
            or (label and normalize_evidence(label) in normalize_evidence(quote))
            or name_located
        )
    ]
    if not verified_quotes:
        excerpt = source_excerpt(source, [name, label])
        if excerpt:
            verified_quotes = [excerpt]

    requested_status = _claim_status(field_payload.get("claim_status"))
    status = ClaimStatus.VERIFIED if verified_quotes else requested_status
    if status is ClaimStatus.VERIFIED and not verified_quotes:
        status = ClaimStatus.INFERRED
    if status is ClaimStatus.REJECTED:
        issues.append(
            EvidenceIssue(path, "模型将字段标为 rejected，已从规则输入中排除", critical=False)
        )
    elif not verified_quotes:
        issues.append(
            EvidenceIssue(
                path,
                f"字段「{name}」未找到原文证据，已标为模型推断并排除出确定性规则",
                critical=True,
            )
        )

    minimum = field_payload.get("min_value")
    maximum = field_payload.get("max_value")
    if isinstance(minimum, (int, float)) and isinstance(maximum, (int, float)) and minimum > maximum:
        issues.append(EvidenceIssue(path, f"字段「{name}」最小值大于最大值", critical=True))
        status = ClaimStatus.REJECTED

    min_length = field_payload.get("min_length")
    max_length = field_payload.get("max_length")
    if (
        isinstance(min_length, int)
        and isinstance(max_length, int)
        and min_length > max_length
    ):
        issues.append(EvidenceIssue(path, f"字段「{name}」最小长度大于最大长度", critical=True))
        status = ClaimStatus.REJECTED

    cleaned = dict(field_payload)
    cleaned["evidence_quotes"] = verified_quotes[:5]
    cleaned["claim_status"] = status.value
    if status is ClaimStatus.INFERRED and not cleaned.get("uncertainty_reason"):
        cleaned["uncertainty_reason"] = "原文中未找到可直接核验的字段证据"
    return cleaned, issues, status.value


def gate_requirement_payload(
    payload: dict[str, Any],
    source_text: str,
    *,
    max_items: int = 8,
) -> RequirementGateResult:
    """Normalize claim statuses and block unsupported facts from rule input."""
    result = RequirementGateResult(payload={"title": "", "summary": "", "items": []})
    result.injection_warnings = detect_prompt_injection(source_text)
    counts = {status.value: 0 for status in ClaimStatus}

    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        result.issues.append(EvidenceIssue("items", "items 不是数组", critical=True))
        return result

    result.payload["title"] = str(payload.get("title") or "").strip()
    result.payload["summary"] = str(payload.get("summary") or "").strip()
    items: list[dict[str, Any]] = []
    for item_index, raw_item in enumerate(raw_items[:max_items], start=1):
        if not isinstance(raw_item, dict):
            result.issues.append(EvidenceIssue(f"items[{item_index}]", "条目不是对象", critical=True))
            continue
        item = dict(raw_item)
        path = f"items[{item_index}]"
        title = str(item.get("title") or "").strip()
        if not title:
            result.issues.append(EvidenceIssue(path, "标题为空，已拒绝该条目", critical=True))
            counts[ClaimStatus.REJECTED.value] += 1
            continue

        quotes = _string_list(item.get("evidence_quotes"))
        title_located = bool(
            normalize_evidence(title) in normalize_evidence(source_text)
            or (
                item.get("source_ref")
                and normalize_evidence(str(item.get("source_ref"))) in normalize_evidence(source_text)
            )
        )
        verified_quotes = [
            quote
            for quote in quotes
            if quote_in_source(quote, source_text)
            and (
                normalize_evidence(title) in normalize_evidence(quote)
                or (
                    item.get("source_ref")
                    and normalize_evidence(str(item.get("source_ref")))
                    in normalize_evidence(quote)
                )
                or title_located
            )
        ]
        if not verified_quotes:
            excerpt = source_excerpt(source_text, [title, str(item.get("source_ref") or "")])
            if excerpt:
                verified_quotes = [excerpt]
        item_status = _claim_status(item.get("claim_status"))
        if verified_quotes:
            item_status = ClaimStatus.VERIFIED
        elif item_status is ClaimStatus.VERIFIED:
            item_status = ClaimStatus.INFERRED
        if item_status is ClaimStatus.REJECTED:
            counts[item_status.value] += 1
            result.issues.append(EvidenceIssue(path, "条目被模型标为 rejected，已排除", critical=True))
            continue
        if item_status is ClaimStatus.INFERRED:
            result.issues.append(
                EvidenceIssue(
                    path,
                    f"条目「{title}」未找到原文证据，已标为模型推断",
                    critical=True,
                )
            )
            if not item.get("uncertainty_reason"):
                item["uncertainty_reason"] = "原文中未找到可直接核验的条目证据"
        counts[item_status.value] += 1

        clean_fields: list[dict[str, Any]] = []
        for field_index, raw_field in enumerate(item.get("fields") or [], start=1):
            if not isinstance(raw_field, dict):
                result.issues.append(
                    EvidenceIssue(f"{path}.fields[{field_index}]", "字段不是对象", critical=True)
                )
                continue
            field_path = f"{path}.fields[{field_index}]"
            field, field_issues, field_status = _validate_field(raw_field, source_text, field_path)
            result.issues.extend(field_issues)
            counts[field_status] += 1
            if field_status != ClaimStatus.REJECTED.value:
                clean_fields.append(field)

        item["fields"] = clean_fields
        item["evidence_quotes"] = verified_quotes[:5]
        item["claim_status"] = item_status.value
        items.append(item)

    result.payload["items"] = items
    result.counts = counts
    return result


def validate_review_target(
    item: RequirementItem,
    cases: list[Any],
    *,
    target: str,
    target_type: str,
    target_id: str,
) -> tuple[bool, str]:
    """Check that a review finding points at a real requirement/field/case."""
    needle = normalize_evidence(target_id or target)
    if not needle:
        return False, "复核意见缺少 target"
    if item.id.casefold() in target.casefold() or normalize_evidence(item.title) in needle:
        return True, "requirement"
    for field in item.fields:
        if normalize_evidence(field.name) in needle or normalize_evidence(field.label) in needle:
            return True, "field"
    for case in cases:
        if normalize_evidence(case.title) in needle or needle in normalize_evidence(case.title):
            return True, "case"
    if target_type in {"requirement", "field", "case"} and needle:
        # A self-declared target type is not enough; the identifier must exist.
        return False, f"target「{target_id or target}」未指向真实需求、字段或用例"
    return False, f"target「{target_id or target}」未能定位"


__all__ = [
    "EvidenceIssue",
    "RequirementGateResult",
    "detect_prompt_injection",
    "gate_requirement_payload",
    "normalize_evidence",
    "quote_in_source",
    "requirement_source_text",
    "source_excerpt",
    "validate_review_target",
]
