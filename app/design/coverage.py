"""覆盖率分析：字段 / 边界 / 规则三维覆盖与缺口清单（V2.0 S4 落点）。

设计原则：

  1. **口径必须与生成端一致**：边界点直接复用 :func:`app.design.boundary.boundary_points`。
     若覆盖率自己另写一套取点规则，就会出现「界面说缺边界、实际用例里明明有」的假告警，
     这种报告比没有报告更伤信任。
  2. **缺口必须可定位**：每条缺口都带需求条目与具体目标（哪个字段、哪个边界点、
     哪条规则），否则使用者只知道「覆盖率 70%」，不知道该补什么。
  3. **抓不到就说抓不到**：用例没有标注 requirement_ids 时，规则覆盖无法判断归属，
     这时在 ``note`` 里写明口径，而不是把它算成「已覆盖」。
"""
from __future__ import annotations

import re

from app.core.utils import truncate
from app.design.boundary import boundary_points
from app.schemas.coverage import CoverageDimension, CoverageItem, CoverageReport
from app.schemas.requirement import FieldConstraint, RequirementDoc, RequirementItem
from app.schemas.testcase import TestCase, TestCaseSuite

_NORMALIZE_RE = re.compile(r"[\s　,，。.:：;；\-—_/\\|（）()【】\[\]「」\"'`]+")

#: 规则原文至少要匹配到这么多连续字符才算命中。
#: 定在 4 是权衡出来的：「填写手机号」这类 5 字流程步骤必须能被认出来（否则会
#: 产生大量假缺口），而「提交」「确认」这类 2 字串又太容易在任何文本里误命中。
MIN_RULE_KEY = 4

#: 每个维度最多回报的缺口条数。
DEFAULT_MAX_GAPS = 50


def analyze_coverage(
    doc: RequirementDoc,
    suite: TestCaseSuite,
    *,
    max_gaps: int = DEFAULT_MAX_GAPS,
) -> CoverageReport:
    """对比「需求模型」与「用例集」，产出三维覆盖率报告。"""
    buckets = _index_cases_by_requirement(suite)
    fields = _field_dimension(doc, buckets, max_gaps=max_gaps)
    boundaries = _boundary_dimension(doc, buckets, max_gaps=max_gaps)
    rules = _rule_dimension(doc, buckets, max_gaps=max_gaps)
    dimensions = [fields, boundaries, rules]
    overall = _overall_ratio(dimensions)
    return CoverageReport(
        doc_id=doc.doc_id,
        doc_title=doc.title,
        suite_id=suite.suite_id,
        dimensions=dimensions,
        overall_ratio=overall,
        summary=_summary(dimensions, overall),
    )


# --------------------------------------------------------------------------- #
# 维度一：字段
# --------------------------------------------------------------------------- #


def _field_dimension(
    doc: RequirementDoc, buckets: dict[str, list[TestCase]], *, max_gaps: int
) -> CoverageDimension:
    total = 0
    covered = 0
    gaps: list[CoverageItem] = []
    for item in doc.items:
        cases = _cases_for(buckets, item.id)
        for field in item.testable_fields:
            total += 1
            if any(case_covers_field(case, field) for case in cases):
                covered += 1
                continue
            if len(gaps) < max_gaps:
                gaps.append(
                    CoverageItem(
                        requirement_id=item.id,
                        requirement_title=item.title,
                        target=field.display_name,
                        detail=_constraint_text(field),
                    )
                )
    note = ""
    if total == 0:
        note = "该需求未解析出任何可测字段，字段覆盖率不适用。"
    return CoverageDimension(
        key="field",
        label="字段覆盖",
        total=total,
        covered=covered,
        ratio=_ratio(covered, total),
        note=note,
        gaps=gaps,
    )


def case_covers_field(case: TestCase, field: FieldConstraint) -> bool:
    """用例是否覆盖了该字段（测试数据键 / 标签 / 标题三种口径取并集）。"""
    if field.name in case.test_data or field.label in case.test_data:
        return True
    names = {field.name, field.label}
    if names & set(case.tags):
        return True
    haystack = f"{case.title} {case.remarks}"
    return any(name and name in haystack for name in names)


def _constraint_text(field: FieldConstraint) -> str:
    return field.describe_constraint() or "无显式约束"


# --------------------------------------------------------------------------- #
# 维度二：边界
# --------------------------------------------------------------------------- #


def _boundary_dimension(
    doc: RequirementDoc, buckets: dict[str, list[TestCase]], *, max_gaps: int
) -> CoverageDimension:
    total = 0
    covered = 0
    gaps: list[CoverageItem] = []
    for item in doc.items:
        cases = _cases_for(buckets, item.id)
        for field in item.testable_fields:
            points, _ = boundary_points(field)
            if not points:
                continue
            observed = _observed_values(cases, field)
            for point in points:
                total += 1
                if point.value in observed:
                    covered += 1
                    continue
                if len(gaps) < max_gaps:
                    gaps.append(
                        CoverageItem(
                            requirement_id=item.id,
                            requirement_title=item.title,
                            target=f"{field.display_name} {point.label}",
                            detail=f"期望取值：{_display(point.value)}",
                        )
                    )
    note = ""
    if total == 0:
        note = "该需求的字段没有数值区间/长度区间/枚举/必填约束，没有边界点可取。"
    return CoverageDimension(
        key="boundary",
        label="边界覆盖",
        total=total,
        covered=covered,
        ratio=_ratio(covered, total),
        note=note,
        gaps=gaps,
    )


def _observed_values(cases: list[TestCase], field: FieldConstraint) -> set[str]:
    values: set[str] = set()
    for case in cases:
        for key in (field.name, field.label):
            if key in case.test_data:
                values.add(case.test_data[key])
    return values


def _display(value: str) -> str:
    if value == "":
        return "空值"
    return f"「{truncate(value, 24)}」"


# --------------------------------------------------------------------------- #
# 维度三：规则 / 流程
# --------------------------------------------------------------------------- #


def _rule_dimension(
    doc: RequirementDoc, buckets: dict[str, list[TestCase]], *, max_gaps: int
) -> CoverageDimension:
    total = 0
    covered = 0
    gaps: list[CoverageItem] = []
    unlabeled = 0
    for item in doc.items:
        bucket = _cases_for(buckets, item.id)
        for label, rule in iter_rules(item):
            total += 1
            if not bucket:
                unlabeled += 1
            if any(case_mentions_rule(case, rule) for case in bucket):
                covered += 1
                continue
            if len(gaps) < max_gaps:
                gaps.append(
                    CoverageItem(
                        requirement_id=item.id,
                        requirement_title=item.title,
                        target=truncate(rule, 60),
                        detail=label,
                    )
                )
    note = ""
    if total == 0:
        note = "该需求没有业务规则/流程描述，规则覆盖率不适用。"
    elif unlabeled:
        note = (
            f"有 {unlabeled} 条规则所在的需求条目没有任何用例关联（用例未标注 requirement_ids），"
            "这部分按未覆盖计入。"
        )
    return CoverageDimension(
        key="rule",
        label="规则覆盖",
        total=total,
        covered=covered,
        ratio=_ratio(covered, total),
        note=note,
        gaps=gaps,
    )


def iter_rules(item: RequirementItem) -> list[tuple[str, str]]:
    """列出该需求条目下的全部「规则」（业务规则 / 主流程 / 备选流 / 异常流）。"""
    result: list[tuple[str, str]] = []
    for label, bucket in (
        ("业务规则", item.business_rules),
        ("主流程", item.main_flow),
        ("备选流", item.alternative_flows),
        ("异常流", item.exceptions),
    ):
        for text in bucket:
            cleaned = (text or "").strip()
            if cleaned:
                result.append((label, cleaned))
    return result


def case_mentions_rule(case: TestCase, rule: str) -> bool:
    """用例文本是否提到该规则（用归一化后的连续子串匹配）。"""
    key = normalize_text(rule)
    if len(key) < MIN_RULE_KEY:
        return False
    haystack = normalize_text(
        " ".join(
            [
                case.title,
                case.expected_result,
                case.remarks,
                *case.tags,
                *[step.action for step in case.steps],
                *[step.expected for step in case.steps],
            ]
        )
    )
    if key in haystack:
        return True
    # 用例里常把长规则截断展示（标题截 40 字），因此再用前缀探测一次。
    prefix = key[: max(MIN_RULE_KEY, len(key) // 2)]
    return prefix in haystack


def normalize_text(text: str) -> str:
    return _NORMALIZE_RE.sub("", text or "").lower()


# --------------------------------------------------------------------------- #
# 公共
# --------------------------------------------------------------------------- #


def _index_cases_by_requirement(suite: TestCaseSuite) -> dict[str, list[TestCase]]:
    buckets: dict[str, list[TestCase]] = {}
    for case in suite.cases:
        for requirement_id in case.requirement_ids:
            buckets.setdefault(requirement_id, []).append(case)
    return buckets


def _cases_for(buckets: dict[str, list[TestCase]], requirement_id: str) -> list[TestCase]:
    return buckets.get(requirement_id, [])


def _ratio(covered: int, total: int) -> float:
    return round(covered / total, 4) if total else 0.0


def _overall_ratio(dimensions: list[CoverageDimension]) -> float:
    total = sum(item.total for item in dimensions)
    covered = sum(item.covered for item in dimensions)
    return _ratio(covered, total)


def _summary(dimensions: list[CoverageDimension], overall: float) -> str:
    parts = [
        f"{item.label} {item.covered}/{item.total}（{item.ratio:.0%}）"
        for item in dimensions
        if item.total
    ]
    if not parts:
        return "没有可统计的覆盖目标：该需求未解析出字段，也没有规则与流程描述。"
    return f"综合覆盖率 {overall:.0%}；" + "；".join(parts)


__all__ = [
    "DEFAULT_MAX_GAPS",
    "analyze_coverage",
    "case_covers_field",
    "case_mentions_rule",
    "iter_rules",
    "normalize_text",
]
