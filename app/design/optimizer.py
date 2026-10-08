"""用例优化：去重、编号、排序。

去重分两层，解决两类不同的重复：

  1. **精确指纹**（设计方法 + 归一化标题 + 测试数据）
     同一策略/同一需求条目重复产出同一条用例时去掉（如文档里出现了重复章节）。

  2. **语义重叠**（同模块 + 同用例类型 + 完全相同的测试数据 + 需求范围相交）
     等价类与边界值会对"同一个测试点"各产一条：例如必填字段留空，
     等价类叫「无效等价类（必填字段留空）」，边界值叫「必填边界（留空）」，
     测试数据都是 `{"字段": ""}`，用例类型都是"异常"。这类跨方法重复会合并为一条，
     并在 `covered_methods` 中记录全部覆盖方法，避免用例集虚高。

为什么只有「字段级」方法参与第 2 层：
    场景法用例的 `test_data` 为空，且一条用例覆盖整条业务流程；
    若按"数据相同"合并，同一需求下的主流程/备选流会被误并成一条。
    因此重叠合并只在等价类 / 边界值之间生效，其余一律走精确指纹。
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from app.core.utils import short_hash
from app.schemas.common import CaseSource, DesignMethod
from app.schemas.testcase import TestCase

# 用例编号前缀（保持人类可读，便于在禅道/Jira 中检索）
ID_PREFIX: dict[str, str] = {
    DesignMethod.EQUIVALENCE.value: "EQ",
    DesignMethod.BOUNDARY.value: "BV",
    DesignMethod.SCENARIO.value: "SC",
}

_NORMALIZE_RE = re.compile(r"[\s　,，。.:：;；\-—_/\\|]+")

_METHOD_ORDER = {
    DesignMethod.EQUIVALENCE.value: 0,
    DesignMethod.BOUNDARY.value: 1,
    DesignMethod.SCENARIO.value: 2,
}

# 参与「语义重叠」合并的方法：只有字段级设计方法之间才存在"同一个测试点"。
_OVERLAP_METHODS = frozenset({DesignMethod.EQUIVALENCE, DesignMethod.BOUNDARY})


def _normalize(value: object, *, lower: bool = False) -> str:
    """去掉空白与标点，避免"格式差异"被当成不同用例。"""
    text = _NORMALIZE_RE.sub("", str(value))
    return text.lower() if lower else text


def _data_signature(case: TestCase) -> str:
    return "&".join(f"{key}={_normalize(value)}" for key, value in sorted(case.test_data.items()))


def fingerprint(case: TestCase) -> str:
    """精确指纹：设计方法 + 归一化标题 + 测试数据。"""
    return short_hash(case.design_method.value, _normalize(case.title, lower=True), _data_signature(case))


def overlap_key(case: TestCase) -> tuple[str, str, str] | None:
    """语义重叠键；返回 None 表示该用例不参与重叠合并。

    只有同时满足以下条件的用例才参与：
      - 属于字段级设计方法（等价类 / 边界值）；
      - 携带测试数据（空 test_data 的场景用例不参与，避免误合并）。
    """
    if case.design_method not in _OVERLAP_METHODS or not case.test_data:
        return None
    return (case.module or "", case.case_type.value, _data_signature(case))


def _find_overlap(candidates: Iterable[TestCase], case: TestCase) -> TestCase | None:
    """在候选集中找「需求范围相交」的同一测试点。

    两个用例只要关联到同一条需求（或任一方未标注需求），就认为是同一个测试点，
    这样既能把同一需求下跨方法的重复合并，也不会把不同需求的用例错误合并。
    """
    scope = set(case.requirement_ids)
    for candidate in candidates:
        other = set(candidate.requirement_ids)
        if not scope or not other or scope & other:
            return candidate
    return None


def _absorb(kept: TestCase, dropped: TestCase) -> None:
    """把被剔除的重复用例的信息合并进保留项，确保信息不丢失。"""
    for req_id in dropped.requirement_ids:
        if req_id not in kept.requirement_ids:
            kept.requirement_ids.append(req_id)

    if dropped.design_method is not kept.design_method and dropped.design_method not in kept.covered_methods:
        kept.covered_methods.append(dropped.design_method)

    sources = {kept.source, dropped.source}
    if CaseSource.HYBRID in sources or {CaseSource.RULE, CaseSource.LLM} <= sources:
        kept.source = CaseSource.HYBRID


def _ensure_covered_methods(cases: list[TestCase]) -> None:
    """保证每条用例都记录了自身的设计方法（导出/展示依赖该字段）。"""
    for case in cases:
        methods = {case.design_method, *case.covered_methods}
        case.covered_methods = sorted(methods, key=lambda method: _METHOD_ORDER.get(method.value, 99))


def deduplicate(cases: list[TestCase]) -> tuple[list[TestCase], int]:
    """两层去重；返回 (保留的用例, 被剔除的重复数)。"""
    kept: list[TestCase] = []
    exact: dict[str, TestCase] = {}
    buckets: dict[tuple[str, str, str], list[TestCase]] = {}
    duplicates = 0

    for case in cases:
        key = fingerprint(case)
        case.checksum = key

        existing = exact.get(key)
        if existing is not None:
            duplicates += 1
            _absorb(existing, case)
            continue

        bucket_key = overlap_key(case)
        target = _find_overlap(buckets.get(bucket_key, []), case) if bucket_key else None
        if target is not None:
            duplicates += 1
            _absorb(target, case)
            continue

        exact[key] = case
        if bucket_key is not None:
            buckets.setdefault(bucket_key, []).append(case)
        kept.append(case)

    _ensure_covered_methods(kept)
    return kept, duplicates


def sort_cases(cases: list[TestCase]) -> list[TestCase]:
    """排序：优先级 -> 模块 -> 设计方法 -> 标题，保证输出稳定可 diff。"""
    return sorted(
        cases,
        key=lambda case: (
            case.priority.rank,
            case.module or "",
            _METHOD_ORDER.get(case.design_method.value, 99),
            case.title,
        ),
    )


def assign_case_ids(cases: list[TestCase]) -> None:
    """按设计方法分组编号，如 TC-EQ-001 / TC-BV-012 / TC-SC-003。"""
    counters: dict[str, int] = {}
    for case in cases:
        prefix = ID_PREFIX.get(case.design_method.value, case.design_method.value[:2].upper())
        counters[prefix] = counters.get(prefix, 0) + 1
        case.case_id = f"TC-{prefix}-{counters[prefix]:03d}"


def optimize(cases: list[TestCase]) -> tuple[list[TestCase], int]:
    """完整优化流水线：去重 -> 排序 -> 编号。"""
    unique, duplicates = deduplicate(cases)
    ordered = sort_cases(unique)
    assign_case_ids(ordered)
    return ordered, duplicates


__all__ = [
    "ID_PREFIX",
    "assign_case_ids",
    "deduplicate",
    "fingerprint",
    "optimize",
    "overlap_key",
    "sort_cases",
]
