"""等价类划分策略。

算法：
  对每个字段按数据类型与约束划分「有效等价类 / 无效等价类」，
  每个等价类取一个代表值生成一条用例（等价类内部对缺陷的暴露能力等价，
  因此只取代表值即可，避免用例爆炸）。

覆盖的等价类维度：
    枚举值 / 布尔 / 数值范围 / 长度范围 / 必填与可空 / 正则格式 / 无约束普通值
"""
from __future__ import annotations

from app.core.utils import truncate
from app.design.base import (
    DesignStrategy,
    bump_priority,
    field_constraint_text,
    fill_value,
    format_number,
    length_sample,
    make_single_step,
    pattern_sample,
)
from app.schemas.common import CaseType, DesignMethod
from app.schemas.requirement import FieldConstraint, RequirementItem
from app.schemas.testcase import TestCase

ILLEGAL_ENUM_VALUE = "ILLEGAL_ENUM"


class EquivalenceStrategy(DesignStrategy):
    method = DesignMethod.EQUIVALENCE
    description = "对每个字段划分有效/无效等价类，每类取代表值生成用例"

    MAX_ENUM_CASES = 5

    def is_applicable(self, item: RequirementItem) -> bool:
        return bool(item.testable_fields) or bool(item.description or item.acceptance_criteria)

    async def generate(self, item: RequirementItem) -> list[TestCase]:
        cases: list[TestCase] = []
        for field in item.testable_fields:
            cases.extend(self._field_cases(item, field))
        if not cases:
            cases.extend(self._item_level_cases(item))
        return self.too_many(cases)

    # ------------------------------------------------------------------ #
    # 字段级
    # ------------------------------------------------------------------ #
    def _field_cases(self, item: RequirementItem, field: FieldConstraint) -> list[TestCase]:
        valid_values, invalid_values = self._partition(field)
        constraint = field_constraint_text(field)
        cases: list[TestCase] = []

        for value in valid_values:
            cases.append(
                self.build_case(
                    item,
                    title=f"[等价类] {item.title}｜{field.display_name} 有效等价类（{describe_value(value)}）",
                    case_type=CaseType.FUNCTIONAL,
                    steps=make_single_step(
                        action=f"在「{item.title}」中，{field.display_name} 输入 {describe_value(value)} 后提交",
                        expected=f"{field.display_name} 校验通过并被正常接收",
                    ),
                    expected_result=f"{field.display_name} 校验通过，业务继续正常处理。约束：{constraint}",
                    test_data={field.name: value},
                    remarks=f"有效等价类。字段约束：{constraint}",
                    tags=[field.name, "有效等价类"],
                )
            )

        for value, reason in invalid_values:
            cases.append(
                self.build_case(
                    item,
                    title=f"[等价类] {item.title}｜{field.display_name} 无效等价类（{reason}）",
                    case_type=CaseType.EXCEPTION,
                    priority=bump_priority(item.priority) if field.required else item.priority,
                    steps=make_single_step(
                        action=f"在「{item.title}」中，{field.display_name} {action_for(reason)} 后提交",
                        expected=f"提交被拒绝，并提示「{reason}」",
                    ),
                    expected_result=(
                        f"系统拦截该请求并给出明确错误提示（{reason}），不产生脏数据。约束：{constraint}"
                    ),
                    test_data={field.name: value},
                    remarks=f"无效等价类：{reason}。字段约束：{constraint}",
                    tags=[field.name, "无效等价类"],
                )
            )
        return cases

    def _partition(self, field: FieldConstraint) -> tuple[list[str], list[tuple[str, str]]]:
        """返回 (有效等价类代表值, [(无效代表值, 原因)])。"""
        valid: list[str] = []
        invalid: list[tuple[str, str]] = []

        if field.enum_values:
            valid.extend(field.enum_values[: self.MAX_ENUM_CASES])
            if len(field.enum_values) > self.MAX_ENUM_CASES:
                self.context.warn(
                    f"字段「{field.display_name}」枚举取值共 {len(field.enum_values)} 个，"
                    f"已仅取前 {self.MAX_ENUM_CASES} 个生成用例，其余请人工补充。"
                )
            invalid.append((ILLEGAL_ENUM_VALUE, "取枚举范围之外的非法值"))
        elif field.data_type.value == "boolean":
            valid.extend(["true", "false"])
        elif field.has_numeric_range:
            valid.append(self._numeric_representative(field))
            if field.min_value is not None:
                invalid.append((format_number(field.min_value - 1), f"取值低于最小值 {format_number(field.min_value)}"))
            if field.max_value is not None:
                invalid.append((format_number(field.max_value + 1), f"取值高于最大值 {format_number(field.max_value)}"))
        elif field.has_length_range:
            valid.append(self._length_representative(field))
            if field.min_length is not None:
                invalid.append(
                    (
                        fill_value(field.min_length - 1, field.data_charset),
                        f"长度小于最小长度 {field.min_length}",
                    )
                )
            if field.max_length is not None:
                invalid.append(
                    (
                        fill_value(field.max_length + 1, field.data_charset),
                        f"长度大于最大长度 {field.max_length}",
                    )
                )
        else:
            valid.append("正常文本值")

        if field.required:
            invalid.insert(0, ("", "必填字段留空"))
        elif field.nullable:
            valid.append("")

        if field.pattern:
            invalid.append(("不符合格式的内容", f"不满足格式要求 {field.pattern}"))

        return dedup(valid), dedup_pairs(invalid)

    @staticmethod
    def _numeric_representative(field: FieldConstraint) -> str:
        # 有内置样例且落在取值范围内时优先采用（如金额 100.00），
        # 否则中点可能超出精度约束（25000.005 违反「最多两位小数」）。
        sample = pattern_sample(field.pattern)
        if sample is not None and _value_in_numeric_range(field, sample):
            return sample
        if field.min_value is not None and field.max_value is not None:
            low, high = field.min_value, field.max_value
            if float(low).is_integer() and float(high).is_integer():
                # 整数区间必须取整，否则「查询页码 1~1000」会产出 500.5 这类非法值。
                return format_number(low + (high - low) // 2)
            decimals = min(max(_decimals(low), _decimals(high)), 6)
            return format_number(round((low + high) / 2, decimals))
        if field.min_value is not None:
            return format_number(field.min_value)
        return format_number(field.max_value or 0)

    @staticmethod
    def _length_representative(field: FieldConstraint) -> str:
        if field.min_length is not None:
            return length_sample(field, max(field.min_length, 1))
        if field.max_length is not None:
            return length_sample(field, min(field.max_length, 20))
        return "正常长度文本"

    # ------------------------------------------------------------------ #
    # 条目级兜底（没有字段信息时，按需求描述划分正常/异常两类）
    # ------------------------------------------------------------------ #
    def _item_level_cases(self, item: RequirementItem) -> list[TestCase]:
        self.context.warn(
            f"需求「{item.title}」未解析出字段级约束，等价类降级为「正常输入/异常输入」两类，建议复核。"
        )
        acceptance = item.acceptance_criteria[0] if item.acceptance_criteria else "业务按需求描述正常执行"
        return [
            self.build_case(
                item,
                title=f"[等价类] {item.title}｜正常输入（有效等价类）",
                case_type=CaseType.FUNCTIONAL,
                steps=make_single_step(
                    action=f"按需求描述「{truncate(item.description or item.title, 80)}」执行正常业务流程",
                    expected="流程执行成功",
                ),
                expected_result=acceptance,
                remarks="条目级等价类：有效等价类（正常输入）",
                tags=["有效等价类"],
            ),
            self.build_case(
                item,
                title=f"[等价类] {item.title}｜异常输入（无效等价类）",
                case_type=CaseType.EXCEPTION,
                priority=bump_priority(item.priority),
                steps=make_single_step(
                    action="输入不符合需求的异常数据并提交",
                    expected="系统拒绝并给出明确错误提示",
                ),
                expected_result="系统拦截异常输入，给出可读错误提示且不产生脏数据。",
                remarks="条目级等价类：无效等价类（异常输入）",
                tags=["无效等价类"],
            ),
        ]


# --------------------------------------------------------------------------- #
# 模块级小工具
# --------------------------------------------------------------------------- #

def _decimals(value: float) -> int:
    """返回数值的小数位数（用于把代表值对齐到字段允许的精度）。"""
    text = repr(float(value))
    if "e" in text or "E" in text:
        return 6
    return len(text.split(".", 1)[1]) if "." in text else 0


def _value_in_numeric_range(field: FieldConstraint, value: str) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    if field.min_value is not None and number < field.min_value:
        return False
    if field.max_value is not None and number > field.max_value:
        return False
    return True


def describe_value(value: str) -> str:
    if value == "":
        return "空值"
    if value == ILLEGAL_ENUM_VALUE:
        return "非法枚举值"
    return f"「{truncate(value, 24)}」"


def action_for(reason: str) -> str:
    return {
        "必填字段留空": "留空（不填写）",
        "取枚举范围之外的非法值": "输入枚举范围外的值",
    }.get(reason, "输入非法值")


def dedup(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def dedup_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for value, reason in pairs:
        if value not in seen:
            seen.add(value)
            result.append((value, reason))
    return result
