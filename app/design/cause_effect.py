"""因果图设计策略（V2.0 S2 落点）。

链路：**因 / 果 / 约束 -> 因果图 -> 判定表 -> 用例**。

  1. **提取因果**：从业务规则、异常场景、验收标准里抽取「若/如果/当 A 则 B」形式的
     因果关系；没有显式连词但含「禁止 / 不允许 / 不得」的条款按**屏蔽型**因果处理
     （因成立即强行指定结果，不受其它因影响）。
  2. **标注约束**：三种经典约束按文本特征识别并写入备注，便于人工复核：
     ``E`` 异或（互斥）、``I`` 包含（若 A 则必然 B）、``M`` 屏蔽（A 成立则屏蔽其它）。
  3. **转判定表**：因果组合空间为 2^n，直接照搬会爆量，因此复用判定表的
     无关项合并：同一结果、仅一个因不同的组合合并为该因无关。屏蔽型因果尤其
     适合合并 —— 这正对应因果图里「屏蔽」约束的语义。
  4. **生成用例**：每条压缩规则一条用例；能落到字段上的因会写进测试数据，
     纯文本因只写进步骤与预期，避免污染 test_data 与去重指纹。

与判定表的区别：判定表的条件来自字段约束、动作是「接受 / 拒绝」；因果图的条件
来自业务规则文本、动作是规则声明的结果，因此两者互补而非重复。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.utils import truncate
from app.design.base import DesignStrategy, bump_priority
from app.design.decision_table import (
    ACCEPT_KEY,
    MAX_CONDITIONS,
    Condition,
    TableRule,
    build_conditions,
    compress_rules,
    condition_for_field,
)
from app.schemas.common import CaseType, DesignMethod
from app.schemas.requirement import FieldConstraint, RequirementItem
from app.schemas.testcase import TestCase, TestStep

#: 「若/如果/当 A 则/就 B」形式的因果连词。
CAUSE_EFFECT_RE = re.compile(
    r"(?:若|如果|当|如遇|只要|一旦)\s*(?P<cause>.{2,60}?)\s*"
    r"(?:则|就|应|须|需|必须|要|会|将)\s*(?P<effect>.{2,80})"
)

#: 屏蔽型约束：因成立即强行指定结果，与其它因无关。
MASKING_HINTS: tuple[str, ...] = (
    "禁止",
    "不允许",
    "不得",
    "不能",
    "不可",
    "拒绝",
    "拦截",
    "屏蔽",
)

#: 异或型约束：多个取值互斥，只能成立其一。
EXCLUSIVE_HINTS: tuple[str, ...] = ("之一", "只能", "仅可", "互斥", "任选其一", "不可同时")

CONSTRAINT_MASK = "M"
CONSTRAINT_EXCLUSIVE = "E"
CONSTRAINT_INCLUSION = "I"

CONSTRAINT_LABELS: dict[str, str] = {
    CONSTRAINT_MASK: "屏蔽（M）",
    CONSTRAINT_EXCLUSIVE: "异或（E）",
    CONSTRAINT_INCLUSION: "包含（I）",
}

DEFAULT_EFFECT = "无因果规则命中，业务按默认路径处理（放行）"
DEFAULT_KEY = "9-DEFAULT"

MASKED_EFFECT_SUFFIX = "（屏蔽型因果生效：其余因不影响该结果）"


@dataclass(slots=True)
class CausalRule:
    """一条因果关系：因成立则果发生。"""

    index: int
    cause: str
    effect: str
    constraint: str
    field: FieldConstraint | None = None

    @property
    def constraint_label(self) -> str:
        return CONSTRAINT_LABELS.get(self.constraint, self.constraint)

    @property
    def condition_key(self) -> str:
        return self.field.name if self.field is not None else f"cause{self.index}"

    def to_condition(self) -> Condition:
        if self.field is not None:
            condition = condition_for_field(self.field)
            if condition is not None:
                return condition
        return Condition(
            key=self.condition_key,
            label=truncate(self.cause, 24),
            valid_value="成立",
            invalid_value="不成立",
            invalid_reason=f"前置条件「{truncate(self.cause, 30)}」不成立",
            required=False,
        )


class CauseEffectStrategy(DesignStrategy):
    method = DesignMethod.CAUSE_EFFECT
    description = "从业务规则提取因/果与异或·包含·屏蔽约束，折算判定表并合并无关项后生成用例"

    def is_applicable(self, item: RequirementItem) -> bool:
        rules = extract_causal_rules(item)
        if len(rules) >= 2:
            return True
        return len(rules) + len(build_conditions(item)) >= 2

    async def generate(self, item: RequirementItem) -> list[TestCase]:
        causal = extract_causal_rules(item)[:MAX_CONDITIONS]
        conditions: list[Condition] = []
        field_backed: set[str] = set()

        for rule in causal:
            condition = rule.to_condition()
            if any(existing.key == condition.key for existing in conditions):
                # 两条因果规则落在同一个字段上时只能算一个「因」，
                # 否则同一个条件会出现两列，其中一列永远为假。
                continue
            conditions.append(condition)
            if rule.field is not None:
                field_backed.add(condition.key)

        if len(conditions) < MAX_CONDITIONS:
            existing = {condition.key for condition in conditions}
            for field_condition in build_conditions(item):
                if len(conditions) >= MAX_CONDITIONS:
                    break
                if field_condition.key in existing:
                    continue
                conditions.append(field_condition)
                field_backed.add(field_condition.key)

        if len(conditions) < 2:
            self.context.warn(
                f"需求「{item.title}」只识别出 {len(conditions)} 个「因」，"
                "因果图至少需要 2 个因，已跳过。"
            )
            return []

        rules, total = compress_rules(
            conditions, lambda combo: resolve_effect(combo, causal, conditions)
        )
        # 原本这里会连着输出两条（一条讲识别到几条规则、一条讲折算后剩几条），
        # 5 条需求就是 10 行。合并成一行后信息量不变，噪声减半。
        supplement = "" if len(causal) >= 2 else "，因果规则不足已用字段约束补齐（建议人工确认）"
        self.context.warn(
            f"「因果图」需求「{item.title}」：{len(causal)} 条因果规则（"
            + "、".join(summarize_constraints(causal))
            + f"）{supplement}；{len(conditions)} 个因展开 {total} 种组合 → 合并无关项后 {len(rules)} 条规则。"
        )
        cases = [
            self._case(item, conditions, rule, index, len(rules), field_backed)
            for index, rule in enumerate(rules, start=1)
        ]
        return self.too_many(cases)

    def _case(
        self,
        item: RequirementItem,
        conditions: list[Condition],
        rule: TableRule,
        index: int,
        total_rules: int,
        field_backed: set[str],
    ) -> TestCase:
        test_data: dict[str, str] = {}
        for position, condition in enumerate(conditions):
            if condition.key not in field_backed:
                continue
            state = rule.conditions[position]
            keep = True if state is None else state
            test_data[condition.key] = condition.valid_value if keep else condition.invalid_value

        cause_text = "，".join(
            f"{condition.label}="
            + ("任意" if rule.is_dont_care(position) else ("成立" if rule.conditions[position] else "不成立"))
            for position, condition in enumerate(conditions)
        )
        blocked = rule.action_key not in (ACCEPT_KEY, DEFAULT_KEY)
        dont_cares = [
            condition.label for position, condition in enumerate(conditions) if rule.is_dont_care(position)
        ]
        return self.build_case(
            item,
            title=f"[因果图] {item.title}｜规则 {index}/{total_rules}：{truncate(rule.action_text, 40)}",
            case_type=CaseType.EXCEPTION if blocked else CaseType.FUNCTIONAL,
            priority=bump_priority(item.priority) if blocked else item.priority,
            steps=[
                TestStep(no=1, action=f"构造因果组合：{cause_text}", expected=""),
                TestStep(no=2, action="触发该组合下的一次完整业务操作", expected=rule.action_text),
            ],
            expected_result=f"预期结果：{rule.action_text}",
            test_data=test_data,
            remarks=(
                f"因果图折算判定表：规则 {index}/{total_rules}，因={len(conditions)}；"
                + ("无关项：" + "、".join(dont_cares) if dont_cares else "全部因均已确定")
            ),
            tags=["因果图", *(["无关项合并"] if dont_cares else [])],
        )


# --------------------------------------------------------------------------- #
# 因 / 果 提取
# --------------------------------------------------------------------------- #


def extract_causal_rules(item: RequirementItem) -> list[CausalRule]:
    """从需求条目里抽取因果关系。"""
    texts: list[str] = []
    for bucket in (
        item.business_rules,
        item.exceptions,
        item.alternative_flows,
        item.acceptance_criteria,
    ):
        texts.extend(bucket)

    rules: list[CausalRule] = []
    seen: set[str] = set()
    for text in texts:
        for cause, effect in split_causal_text(text):
            key = f"{cause}|{effect}"
            if key in seen:
                continue
            seen.add(key)
            rules.append(
                CausalRule(
                    index=len(rules) + 1,
                    cause=cause,
                    effect=effect,
                    constraint=classify_constraint(f"{cause} {effect}"),
                    field=match_field(item, cause),
                )
            )
    return rules


def split_causal_text(text: str) -> list[tuple[str, str]]:
    """把一条规则文本拆成 (因, 果)；无显式连词时按整条规则处理。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    matched = CAUSE_EFFECT_RE.search(cleaned)
    if matched:
        cause = matched.group("cause").strip(" ，,。;；")
        effect = matched.group("effect").strip(" ，,。;；")
        if cause and effect:
            return [(cause, effect)]
    if any(hint in cleaned for hint in MASKING_HINTS):
        return [(cleaned, "系统按该规则阻断本次操作并给出明确提示")]
    return [(cleaned, "系统按该规则校验并给出对应处理结果")]


def classify_constraint(text: str) -> str:
    if any(hint in text for hint in MASKING_HINTS):
        return CONSTRAINT_MASK
    if any(hint in text for hint in EXCLUSIVE_HINTS):
        return CONSTRAINT_EXCLUSIVE
    return CONSTRAINT_INCLUSION


def match_field(item: RequirementItem, cause: str) -> FieldConstraint | None:
    """把「因」文本关联到具体字段（因里提到字段名或中文标签时）。"""
    for field in item.testable_fields:
        for name in (field.name, field.label):
            if name and name in cause:
                return field
    return None


def summarize_constraints(rules: list[CausalRule]) -> list[str]:
    counts: dict[str, int] = {}
    for rule in rules:
        counts[rule.constraint_label] = counts.get(rule.constraint_label, 0) + 1
    return [f"{label} {count} 条" for label, count in counts.items()] or ["无显式约束标注"]


# --------------------------------------------------------------------------- #
# 动作桩
# --------------------------------------------------------------------------- #


def resolve_effect(
    combo: tuple[bool, ...],
    causal: list[CausalRule],
    conditions: list[Condition],
) -> tuple[str, str]:
    """把一组「因」的成立情况折算为「果」。

    屏蔽型因果优先级最高：只要它的因成立，结果就被它指定，其余因一律无关 ——
    这既是因果图里「屏蔽」约束的定义，也是无关项合并的主要来源。
    """
    index_by_key = {condition.key: position for position, condition in enumerate(conditions)}
    firing: list[CausalRule] = []
    for rule in causal:
        position = index_by_key.get(rule.condition_key)
        if position is not None and combo[position]:
            firing.append(rule)

    masked = [rule for rule in firing if rule.constraint == CONSTRAINT_MASK]
    if masked:
        rule = masked[0]
        return f"1-M{rule.index:02d}", f"{rule.effect}{MASKED_EFFECT_SUFFIX}"
    if not firing:
        return DEFAULT_KEY, DEFAULT_EFFECT

    key = "2-" + "|".join(f"{rule.index:02d}" for rule in firing)
    return key, "；".join(rule.effect for rule in firing)


__all__ = [
    "CONSTRAINT_EXCLUSIVE",
    "CONSTRAINT_INCLUSION",
    "CONSTRAINT_MASK",
    "CausalRule",
    "CauseEffectStrategy",
    "classify_constraint",
    "extract_causal_rules",
    "match_field",
    "resolve_effect",
    "split_causal_text",
    "summarize_constraints",
]
