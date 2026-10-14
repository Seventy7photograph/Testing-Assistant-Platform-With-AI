"""判定表设计策略（V2.0 S1 落点）。

算法（条件桩 -> 动作桩 -> 无关项合并）：

  1. **条件桩**：从需求条目的字段约束里挑出「可判定」的条件 —— 枚举取值、
     布尔、数值区间、长度区间、必填、格式。无约束的纯文本字段不构成条件，
     把它塞进判定表只会产出一堆无效列。条件数上限 5：2^n 是全组合规模，
     超过 5 个条件时表的规模会盖过收益（32 列已足够人工复核）。

  2. **动作桩**：采用「按条件顺序短路」的语义 —— 任一条件不满足即拒绝，
     提示首个不满足的约束；全部满足则放行。这与真实系统里按字段顺序逐项
     校验的行为一致，产出的列才有执行意义。

  3. **无关项合并**：先展开 2^n 条组合，再做「同一动作、仅一个条件不同」的
     相邻立方体合并（把该条件记为无关项 ``-``）。n 个条件最终压缩为 n+1 条
     等价规则，压缩比写入告警，方便人工核对是否漏场景。

为什么这一层值得单独实现：判定表的价值不在「穷举组合」，而在**证明**穷举之后
哪些组合是等价的 —— 用例数从 2^n 降到 n+1，且每条规则都能说清「哪些条件无关」。
这正是等价类/边界值覆盖不到的多条件组合缺陷。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import product

from app.core.utils import truncate
from app.design.base import (
    DesignStrategy,
    bump_priority,
    fill_value,
    format_number,
    length_sample,
    pattern_sample,
)
from app.schemas.common import CaseType, DataType, DesignMethod
from app.schemas.requirement import FieldConstraint, RequirementItem
from app.schemas.testcase import TestCase, TestStep

#: 条件桩数量上限：2^5 = 32 列，再多就失去了人工复核的价值。
MAX_CONDITIONS = 5

#: 全部条件满足时的动作文案。
ACCEPT_ACTION = "接受并继续处理"

#: 「放行」动作的排序键，保证压缩后第一条永远是放行规则。
ACCEPT_KEY = "0-ACCEPT"

ILLEGAL_ENUM_VALUE = "ILLEGAL_ENUM"
NORMAL_VALUE = "正常值"

#: 动作桩解析器：入参为「每个条件是否成立」，返回 (动作标识, 动作文案)。
ActionResolver = Callable[[tuple[bool, ...]], "tuple[str, str]"]


@dataclass(slots=True)
class Condition:
    """一个条件桩：条件成立 / 不成立时各自对应的代表取值。"""

    key: str
    label: str
    valid_value: str
    invalid_value: str
    invalid_reason: str
    required: bool = False

    def describe_valid(self) -> str:
        return f"{self.label} 满足约束（{describe_value(self.valid_value)}）"

    def describe_invalid(self) -> str:
        return f"{self.label} 不满足约束（{self.invalid_reason}）"


@dataclass(slots=True)
class TableRule:
    """压缩后的一条规则列：``conditions[i]`` 为 None 表示该条件是无项。"""

    conditions: tuple[bool | None, ...]
    action_key: str
    action_text: str

    def is_dont_care(self, index: int) -> bool:
        return self.conditions[index] is None


# --------------------------------------------------------------------------- #
# 条件桩
# --------------------------------------------------------------------------- #


def build_conditions(item: RequirementItem, *, limit: int = MAX_CONDITIONS) -> list[Condition]:
    """从字段约束构造条件桩（保持文档顺序，顺序即校验优先级）。"""
    conditions: list[Condition] = []
    for field in item.testable_fields:
        condition = condition_for_field(field)
        if condition is None:
            continue
        conditions.append(condition)
        if len(conditions) >= limit:
            break
    return conditions


def condition_for_field(field: FieldConstraint) -> Condition | None:
    """把一个字段转成条件桩；字段没有可判定约束时返回 None。"""
    valid = valid_value(field)
    invalid = invalid_value(field)
    if valid is None or invalid is None or valid == invalid:
        return None
    return Condition(
        key=field.name,
        label=field.display_name,
        valid_value=valid,
        invalid_value=invalid,
        invalid_reason=invalid_reason(field),
        required=field.required,
    )


def valid_value(field: FieldConstraint) -> str | None:
    """该字段的一个合法取值；字段本身无约束时返回 None。"""
    if field.enum_values:
        return field.enum_values[0]
    if field.data_type is DataType.BOOLEAN:
        return "true"
    if field.has_numeric_range:
        sample = pattern_sample(field.pattern)
        if sample is not None and _in_numeric_range(field, sample):
            return sample
        if field.min_value is not None and field.max_value is not None:
            low, high = field.min_value, field.max_value
            if float(low).is_integer() and float(high).is_integer():
                return format_number(int(low + (high - low) // 2))
            return format_number(round((low + high) / 2, 2))
        if field.min_value is not None:
            return format_number(field.min_value)
        return format_number(field.max_value or 0)
    if field.has_length_range:
        length = field.min_length or min(field.max_length or 1, 8)
        return length_sample(field, max(length, 1))
    if field.pattern:
        return pattern_sample(field.pattern) or NORMAL_VALUE
    if field.required:
        return NORMAL_VALUE
    return None


def invalid_value(field: FieldConstraint) -> str | None:
    """该字段的一个非法取值；字段本就无约束时返回 None。"""
    if field.required:
        return ""
    if field.enum_values:
        return ILLEGAL_ENUM_VALUE
    if field.data_type is DataType.BOOLEAN:
        return "也许"
    if field.has_numeric_range:
        if field.max_value is not None:
            return format_number(field.max_value + 1)
        if field.min_value is not None:
            return format_number(field.min_value - 1)
    if field.has_length_range:
        if field.max_length is not None:
            return fill_value(field.max_length + 1, field.data_charset)
        if field.min_length is not None and field.min_length - 1 >= 0:
            return fill_value(field.min_length - 1, field.data_charset)
    if field.pattern:
        return "格式错误的内容"
    return None


def invalid_reason(field: FieldConstraint) -> str:
    if field.required:
        return "必填字段留空"
    if field.enum_values:
        return "取值落在枚举范围之外"
    if field.data_type is DataType.BOOLEAN:
        return "取值不是布尔值"
    if field.has_numeric_range:
        return "取值超出允许范围"
    if field.has_length_range:
        return "长度超出允许范围"
    if field.pattern:
        return f"取值不满足格式 {field.pattern}"
    return "取值不满足字段约束"


def describe_value(value: str) -> str:
    if value == "":
        return "空值"
    if value == ILLEGAL_ENUM_VALUE:
        return "非法枚举值"
    return f"「{truncate(value, 20)}」"


# --------------------------------------------------------------------------- #
# 无关项合并
# --------------------------------------------------------------------------- #


def compress_rules(
    conditions: list[Condition],
    action_for: ActionResolver,
    *,
    limit: int = MAX_CONDITIONS,
) -> tuple[list[TableRule], int]:
    """展开 2^n 条组合后做无关项合并；返回 (压缩后的规则, 展开前的组合数)。

    :param action_for: 入参为「每个条件是否成立」的布尔元组，返回
        ``(动作标识, 动作文案)``。只有动作标识相同才会被合并 —— 文案相同但
        标识不同的组合必须分开保留，否则会把「同样的结论、不同的原因」抹掉。
    """
    active = conditions[:limit]
    size = len(active)
    if size == 0:
        return [], 0

    expanded: dict[str, list[list[bool | None]]] = {}
    action_texts: dict[str, str] = {}
    for combo in product((True, False), repeat=size):
        key, text = action_for(combo)
        expanded.setdefault(key, []).append(list(combo))
        action_texts[key] = text

    total_combinations = 2**size
    rules: list[TableRule] = []
    for key, patterns in expanded.items():
        for pattern in reduce_patterns(patterns):
            rules.append(
                TableRule(conditions=tuple(pattern), action_key=key, action_text=action_texts[key])
            )
    rules.sort(key=lambda rule: rule.action_key)
    return rules, total_combinations


def reduce_patterns(patterns: list[list[bool | None]]) -> list[list[bool | None]]:
    """把同动作的组合立方体做相邻合并（Quine-McCluskey 的化简步骤）。"""
    working = [list(pattern) for pattern in patterns]
    changed = True
    while changed:
        changed = False
        index = 0
        while index < len(working):
            cursor = index + 1
            while cursor < len(working):
                merged = try_merge(working[index], working[cursor])
                if merged is None:
                    cursor += 1
                    continue
                working[index] = merged
                del working[cursor]
                changed = True
            index += 1
    return working


def try_merge(left: list[bool | None], right: list[bool | None]) -> list[bool | None] | None:
    """两个立方体若仅有一处不同，则合并为该位无关项。

    合并结果必须是两者的**并集本身**（不能多出任何组合），因此要求差异位恰好
    一个：``(True, False)`` 合并为 ``None``，``(None, True)`` 也合并为 ``None``
    （前者已包含后者）。
    """
    if len(left) != len(right):
        return None
    diff = [i for i, (a, b) in enumerate(zip(left, right)) if a != b]
    if len(diff) != 1:
        return None
    merged = list(left)
    merged[diff[0]] = None
    return merged


# --------------------------------------------------------------------------- #
# 策略
# --------------------------------------------------------------------------- #


def order_first_action(combo: tuple[bool, ...], conditions: list[Condition]) -> tuple[str, str]:
    """动作桩：按条件顺序短路 —— 首个不满足的条件决定拒绝原因。"""
    for position, satisfied in enumerate(combo):
        if not satisfied:
            return f"{position + 1}-{conditions[position].key}", conditions[position].describe_invalid()
    return ACCEPT_KEY, f"全部条件满足：{ACCEPT_ACTION}"


def rule_condition_text(conditions: list[Condition], rule: TableRule) -> str:
    parts: list[str] = []
    for position, condition in enumerate(conditions):
        state = rule.conditions[position]
        if state is None:
            parts.append(f"{condition.label}=任意（无关项）")
        elif state:
            parts.append(f"{condition.label}=满足")
        else:
            parts.append(f"{condition.label}=不满足")
    return "，".join(parts)


class DecisionTableStrategy(DesignStrategy):
    method = DesignMethod.DECISION_TABLE
    description = "按条件桩/动作桩生成判定表，展开 2^n 后合并无关项，输出等价规则用例"

    def is_applicable(self, item: RequirementItem) -> bool:
        return len(build_conditions(item)) >= 2

    async def generate(self, item: RequirementItem) -> list[TestCase]:
        conditions = build_conditions(item)
        if len(conditions) < 2:
            self.context.warn(
                f"需求「{item.title}」只有 {len(conditions)} 个可判定条件，"
                "判定表至少需要 2 个条件桩，已跳过。"
            )
            return []

        resolver = lambda combo: order_first_action(combo, conditions)  # noqa: E731
        rules, total = compress_rules(conditions, resolver)
        self.context.warn(
            f"「判定表」需求「{item.title}」：{len(conditions)} 个条件展开 {total} 种组合，"
            f"无关项合并后保留 {len(rules)} 条等价规则。"
        )
        cases = [
            self._case(item, conditions, rule, index, len(rules))
            for index, rule in enumerate(rules, start=1)
        ]
        return self.too_many(cases)

    def _case(
        self,
        item: RequirementItem,
        conditions: list[Condition],
        rule: TableRule,
        index: int,
        total_rules: int = 0,
    ) -> TestCase:
        accepted = rule.action_key == ACCEPT_KEY
        test_data: dict[str, str] = {}
        for position, condition in enumerate(conditions):
            state = rule.conditions[position]
            keep = True if state is None else state
            test_data[condition.key] = condition.valid_value if keep else condition.invalid_value

        condition_text = rule_condition_text(conditions, rule)
        steps = [
            TestStep(no=1, action=f"构造条件组合：{condition_text}", expected=""),
            TestStep(
                no=2,
                action="按该组合提交输入",
                expected="" if accepted else rule.action_text,
            ),
        ]
        remarks = (
            f"判定表规则 {index}/{total_rules or index}；"
            + "；".join(
                f"{condition.label}="
                + ("-" if rule.is_dont_care(position) else ("满足" if rule.conditions[position] else "不满足"))
                for position, condition in enumerate(conditions)
            )
        )
        return self.build_case(
            item,
            title=f"[判定表] {item.title}｜规则 {index}：{truncate(condition_text, 48)}",
            case_type=CaseType.FUNCTIONAL if accepted else CaseType.EXCEPTION,
            priority=item.priority if accepted else bump_priority(item.priority),
            steps=steps,
            expected_result=(
                f"全部条件满足，{ACCEPT_ACTION}。"
                if accepted
                else f"{rule.action_text}，不产生脏数据。"
            ),
            test_data=test_data,
            remarks=remarks,
            tags=["判定表", "无关项合并"],
        )


def _in_numeric_range(field: FieldConstraint, value: str) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    if field.min_value is not None and number < field.min_value:
        return False
    if field.max_value is not None and number > field.max_value:
        return False
    return True


__all__ = [
    "ACCEPT_ACTION",
    "ACCEPT_KEY",
    "MAX_CONDITIONS",
    "ActionResolver",
    "Condition",
    "DecisionTableStrategy",
    "TableRule",
    "build_conditions",
    "compress_rules",
    "condition_for_field",
    "describe_value",
    "invalid_reason",
    "invalid_value",
    "order_first_action",
    "reduce_patterns",
    "rule_condition_text",
    "try_merge",
    "valid_value",
]
