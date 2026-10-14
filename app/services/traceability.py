"""需求差异对比与需求-用例双向追溯（V2.0 S5 落地实现）。

**差异对比**：匹配顺序是「先 ID、后标题相似度」。只用 ID 匹配会把「改标题」
误判成「删一条 + 加一条」；只用标题匹配又会把「同一标题下内容大改」当成没变。
两者结合，才能在报告里如实区分「新增 / 删除 / 修改」。

**追溯矩阵**：正向（需求 -> 用例）回答「这条需求测了吗」，反向（用例 -> 需求）
回答「这条用例为什么存在」。两个方向共用同一份索引，因此不会出现
「正向说有 3 条、反向只找到 2 条」这类自相矛盾。
"""
from __future__ import annotations

from collections.abc import Iterable
from difflib import SequenceMatcher

from app.schemas.requirement import FieldConstraint, RequirementDoc, RequirementItem
from app.schemas.testcase import TestCaseSuite
from app.schemas.traceability import (
    CaseTrace,
    FieldChange,
    RequirementChange,
    RequirementDiff,
    RequirementTrace,
    TraceabilityMatrix,
    TraceCase,
)

#: 标题相似度阈值：低于它就不认为是「同一条需求改了」，而是删+增。
TITLE_MATCH_THRESHOLD = 0.6

#: 参与对比的字段属性（顺序即报告中的展示顺序）。
FIELD_ATTRIBUTES: tuple[str, ...] = (
    "data_type",
    "required",
    "nullable",
    "min_value",
    "max_value",
    "min_length",
    "max_length",
    "enum_values",
    "pattern",
    "default",
    "unit",
)

#: 参与对比的非字段部分。
SECTION_ATTRIBUTES: tuple[tuple[str, str], ...] = (
    ("title", "标题"),
    ("description", "需求描述"),
    ("module", "所属模块"),
    ("priority", "优先级"),
    ("requirement_type", "需求类型"),
    ("business_rules", "业务规则"),
    ("preconditions", "前置条件"),
    ("main_flow", "主流程"),
    ("alternative_flows", "备选流程"),
    ("exceptions", "异常场景"),
    ("acceptance_criteria", "验收标准"),
)

FIELD_ADDED = "(字段)"


# --------------------------------------------------------------------------- #
# 差异对比
# --------------------------------------------------------------------------- #


def diff_requirements(older: RequirementDoc, newer: RequirementDoc) -> RequirementDiff:
    """对比两版需求模型，输出新增 / 删除 / 修改清单。"""
    pairs, added_items, removed_items = match_items(older.items, newer.items)

    added = [
        RequirementChange(
            kind="added",
            requirement_id=item.id,
            title=item.title,
            detail=f"新增需求条目（{len(item.fields)} 个字段，{len(item.business_rules)} 条业务规则）",
        )
        for item in added_items
    ]
    removed = [
        RequirementChange(
            kind="removed",
            requirement_id=item.id,
            title=item.title,
            detail=f"需求条目已删除（原 {len(item.fields)} 个字段）",
        )
        for item in removed_items
    ]

    modified: list[RequirementChange] = []
    unchanged = 0
    for old_item, new_item in pairs:
        field_changes = diff_fields(old_item, new_item)
        changed_sections = diff_sections(old_item, new_item)
        if not field_changes and not changed_sections:
            unchanged += 1
            continue
        detail_parts: list[str] = []
        if field_changes:
            detail_parts.append(f"{len(field_changes)} 处字段约束变更")
        if changed_sections:
            detail_parts.append("变更部分：" + "、".join(changed_sections))
        modified.append(
            RequirementChange(
                kind="modified",
                requirement_id=new_item.id,
                title=new_item.title,
                detail="；".join(detail_parts),
                field_changes=field_changes,
                changed_sections=changed_sections,
            )
        )

    diff = RequirementDiff(
        doc_id=newer.doc_id,
        older_doc_id=older.doc_id,
        newer_doc_id=newer.doc_id,
        older_title=older.title,
        newer_title=newer.title,
        added=added,
        removed=removed,
        modified=modified,
        unchanged=unchanged,
    )
    diff.summary = (
        f"新增 {len(added)} 条，删除 {len(removed)} 条，修改 {len(modified)} 条，未变 {unchanged} 条"
    )
    return diff


def match_items(
    older: list[RequirementItem], newer: list[RequirementItem]
) -> tuple[list[tuple[RequirementItem, RequirementItem]], list[RequirementItem], list[RequirementItem]]:
    """把两版条目配对；返回 (配对列表, 新增条目, 删除条目)。"""
    unmatched_new = list(newer)
    pairs: list[tuple[RequirementItem, RequirementItem]] = []
    remaining_old: list[RequirementItem] = []

    # 第一轮：ID 完全相同。
    by_id = {item.id: item for item in unmatched_new}
    for old_item in older:
        found = by_id.pop(old_item.id, None)
        if found is None:
            remaining_old.append(old_item)
            continue
        pairs.append((old_item, found))
        unmatched_new = [item for item in unmatched_new if item is not found]

    # 第二轮：标题相似度（应对「改了标题」或「拆分后重新编号」）。
    still_unmatched: list[RequirementItem] = []
    for old_item in remaining_old:
        best: RequirementItem | None = None
        best_score = 0.0
        for candidate in unmatched_new:
            score = title_similarity(old_item.title, candidate.title)
            if score > best_score:
                best, best_score = candidate, score
        if best is not None and best_score >= TITLE_MATCH_THRESHOLD:
            pairs.append((old_item, best))
            unmatched_new = [item for item in unmatched_new if item is not best]
            continue
        still_unmatched.append(old_item)

    return pairs, unmatched_new, still_unmatched


def title_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left or "", right or "").ratio()


def diff_fields(old_item: RequirementItem, new_item: RequirementItem) -> list[FieldChange]:
    """字段级差异：新增字段 / 删除字段 / 属性变更。"""
    changes: list[FieldChange] = []
    old_fields = {field.name: field for field in old_item.fields}
    new_fields = {field.name: field for field in new_item.fields}

    for name, old_field in old_fields.items():
        if name not in new_fields:
            changes.append(
                FieldChange(
                    field=name,
                    attribute=FIELD_ADDED,
                    before=describe_field(old_field),
                    after="已删除",
                )
            )
    for name, new_field in new_fields.items():
        if name not in old_fields:
            changes.append(
                FieldChange(
                    field=name,
                    attribute=FIELD_ADDED,
                    before="（新增）",
                    after=describe_field(new_field),
                )
            )

    for name, old_field in old_fields.items():
        new_field = new_fields.get(name)
        if new_field is None:
            continue
        for attribute in FIELD_ATTRIBUTES:
            before = attribute_text(getattr(old_field, attribute, None))
            after = attribute_text(getattr(new_field, attribute, None))
            if before != after:
                changes.append(
                    FieldChange(field=name, attribute=attribute, before=before, after=after)
                )
    return changes


def diff_sections(old_item: RequirementItem, new_item: RequirementItem) -> list[str]:
    """非字段部分（描述 / 流程 / 规则 / 验收标准）的变更标签。"""
    changed: list[str] = []
    for attribute, label in SECTION_ATTRIBUTES:
        before = attribute_text(getattr(old_item, attribute, None))
        after = attribute_text(getattr(new_item, attribute, None))
        if before != after:
            changed.append(label)
    return changed


def attribute_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " | ".join(str(item) for item in value)
    if isinstance(value, float) and float(value).is_integer():
        # 报告里出现 "120.0 -> 150.0" 会让人以为改了精度；整数就按整数展示。
        return str(int(value))
    return str(value)


def describe_field(field: FieldConstraint) -> str:
    constraint = field.describe_constraint()
    suffix = f"，{constraint}" if constraint else ""
    return f"{field.display_name}（{field.data_type.value}{suffix}）"


# --------------------------------------------------------------------------- #
# 追溯矩阵
# --------------------------------------------------------------------------- #


def build_traceability_matrix(
    doc: RequirementDoc,
    suites: Iterable[TestCaseSuite],
    *,
    max_cases_per_requirement: int = 200,
) -> TraceabilityMatrix:
    """构建需求-用例双向追溯矩阵。"""
    suite_list = list(suites)
    known_ids = {item.id for item in doc.items}

    forward: dict[str, list[TraceCase]] = {item.id: [] for item in doc.items}
    reverse: list[CaseTrace] = []

    for suite in suite_list:
        for case in suite.cases:
            trace = CaseTrace(
                case_id=case.case_id,
                title=case.title,
                design_method=case.design_method.label,
                suite_id=suite.suite_id,
                requirement_ids=list(case.requirement_ids),
                resolved_requirement_ids=[rid for rid in case.requirement_ids if rid in known_ids],
                missing_requirement_ids=[rid for rid in case.requirement_ids if rid not in known_ids],
            )
            reverse.append(trace)
            for requirement_id in trace.resolved_requirement_ids:
                bucket = forward.setdefault(requirement_id, [])
                if len(bucket) < max_cases_per_requirement:
                    bucket.append(
                        TraceCase(
                            case_id=case.case_id,
                            title=case.title,
                            design_method=case.design_method.label,
                            case_type=case.case_type.value,
                            priority=case.priority.value,
                        )
                    )

    requirements = [
        RequirementTrace(
            requirement_id=item.id,
            requirement_title=item.title,
            module=item.module,
            case_count=len(forward.get(item.id, [])),
            cases=forward.get(item.id, []),
        )
        for item in doc.items
    ]
    uncovered = [trace.requirement_id for trace in requirements if trace.case_count == 0]
    orphans = sorted(
        {
            trace.case_id
            for trace in reverse
            if trace.missing_requirement_ids and not trace.resolved_requirement_ids
        }
    )

    matrix = TraceabilityMatrix(
        doc_id=doc.doc_id,
        doc_title=doc.title,
        suite_ids=[suite.suite_id for suite in suite_list],
        requirements=requirements,
        cases=reverse,
        uncovered_requirement_ids=uncovered,
        orphan_case_ids=orphans,
    )
    covered = len(requirements) - len(uncovered)
    matrix.summary = (
        f"需求 {len(requirements)} 条，其中 {covered} 条有用例覆盖（未覆盖 {len(uncovered)} 条）；"
        f"用例 {len(reverse)} 条，其中 {len(orphans)} 条关联不到任何需求条目。"
    )
    return matrix


__all__ = [
    "FIELD_ATTRIBUTES",
    "SECTION_ATTRIBUTES",
    "TITLE_MATCH_THRESHOLD",
    "attribute_text",
    "build_traceability_matrix",
    "describe_field",
    "diff_fields",
    "diff_requirements",
    "diff_sections",
    "match_items",
    "title_similarity",
]
