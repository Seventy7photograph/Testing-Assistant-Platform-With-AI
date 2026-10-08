"""边界值分析策略。

算法：
  对每个字段取边界点集合：min-1 / min / min+1 / max-1 / max / max+1
  （数值取数值边界，字符串取长度边界，枚举取首尾取值），
  并显式区分「边界内(有效)」与「越界(无效)」，越界用例类型记为异常。

依据：软件缺陷高发于输入域的边界及其两侧（-1 / 边界 / +1）。
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.utils import truncate
from app.design.base import (
    DesignStrategy,
    bump_priority,
    field_constraint_text,
    format_number,
    length_sample,
    make_single_step,
)
from app.schemas.common import CaseType, DataType, DesignMethod
from app.schemas.requirement import FieldConstraint, RequirementItem
from app.schemas.testcase import TestCase

MAX_POINTS_PER_FIELD = 12

# 「全空格边界」只对文本类字段有意义；布尔/枚举/日期等类型没有长度概念，
# 补一个空格只会产出无意义的噪声用例。
_SPACE_BOUNDARY_TYPES = frozenset({DataType.STRING, DataType.OTHER})


@dataclass(slots=True)
class BoundaryPoint:
    value: str
    label: str
    valid: bool


class BoundaryStrategy(DesignStrategy):
    method = DesignMethod.BOUNDARY
    description = "对数值/长度/枚举边界取点（min-1、min、min+1、max-1、max、max+1）"

    def is_applicable(self, item: RequirementItem) -> bool:
        return any(
            field.has_numeric_range or field.has_length_range or field.enum_values or field.required
            for field in item.testable_fields
        )

    async def generate(self, item: RequirementItem) -> list[TestCase]:
        cases: list[TestCase] = []
        for field in item.testable_fields:
            points = self._points(field)
            if not points:
                continue
            cases.extend(self._cases_for_field(item, field, points))
        if not cases:
            self.context.warn(f"需求「{item.title}」未解析出可做边界分析的约束，已跳过边界值方法。")
        return self.too_many(cases)

    # ------------------------------------------------------------------ #
    def _cases_for_field(
        self, item: RequirementItem, field: FieldConstraint, points: list[BoundaryPoint]
    ) -> list[TestCase]:
        constraint = field_constraint_text(field)
        labels = "、".join(f"{point.label}={describe(point.value)}" for point in points)
        cases: list[TestCase] = []
        for point in points:
            case_type = CaseType.BOUNDARY if point.valid else CaseType.EXCEPTION
            priority = bump_priority(item.priority) if not point.valid and field.required else item.priority
            cases.append(
                self.build_case(
                    item,
                    title=f"[边界值] {item.title}｜{field.display_name} {point.label}",
                    case_type=case_type,
                    priority=priority,
                    steps=make_single_step(
                        action=(
                            f"在「{item.title}」中，{field.display_name} 输入 {describe(point.value)}"
                            f"（{point.label}）后提交"
                        ),
                        expected=(
                            f"{field.display_name} 校验通过并被正常接收"
                            if point.valid
                            else f"提交被拒绝，提示取值超出允许范围（{point.label}）"
                        ),
                    ),
                    expected_result=(
                        f"{field.display_name} 处于允许范围内，业务正常处理。约束：{constraint}"
                        if point.valid
                        else f"系统拒绝越界取值（{point.label}）并给出明确错误提示。约束：{constraint}"
                    ),
                    test_data={field.name: point.value},
                    remarks=f"边界取点：{labels}",
                    tags=[field.name, "边界内" if point.valid else "越界"],
                )
            )
        return cases

    def _points(self, field: FieldConstraint) -> list[BoundaryPoint]:
        points: list[BoundaryPoint] = []

        if field.enum_values:
            points.append(BoundaryPoint(field.enum_values[0], "枚举首个取值", True))
            if len(field.enum_values) > 1:
                points.append(BoundaryPoint(field.enum_values[-1], "枚举末个取值", True))
            if field.required:
                points.append(BoundaryPoint("", "留空（边界外）", False))
            points.append(BoundaryPoint("ILLEGAL_ENUM", "枚举外取值（边界外）", False))
        elif field.has_numeric_range:
            points.extend(self._numeric_points(field))
        elif field.has_length_range:
            points.extend(self._length_points(field))

        if field.required and not any(point.value == "" for point in points):
            points.append(BoundaryPoint("", "必填边界（留空）", False))

        if not points and not field.required and field.data_type in _SPACE_BOUNDARY_TYPES:
            points.append(BoundaryPoint(" ", "全空格边界", False))

        points = dedupe_points(points)
        if len(points) > MAX_POINTS_PER_FIELD:
            self.context.warn(
                f"字段「{field.display_name}」边界取点 {len(points)} 个超过上限，已截断为 {MAX_POINTS_PER_FIELD} 个。"
            )
            points = points[:MAX_POINTS_PER_FIELD]
        return points

    @staticmethod
    def _numeric_points(field: FieldConstraint) -> list[BoundaryPoint]:
        points: list[BoundaryPoint] = []
        if field.min_value is not None:
            points.append(BoundaryPoint(format_number(field.min_value - 1), "最小值-1", False))
            points.append(BoundaryPoint(format_number(field.min_value), "最小值", True))
            points.append(BoundaryPoint(format_number(field.min_value + 1), "最小值+1", True))
        if field.max_value is not None:
            points.append(BoundaryPoint(format_number(field.max_value - 1), "最大值-1", True))
            points.append(BoundaryPoint(format_number(field.max_value), "最大值", True))
            points.append(BoundaryPoint(format_number(field.max_value + 1), "最大值+1", False))
        return points

    @staticmethod
    def _length_points(field: FieldConstraint) -> list[BoundaryPoint]:
        points: list[BoundaryPoint] = []
        if field.min_length is not None:
            if field.min_length - 1 >= 0:
                points.append(
                    BoundaryPoint(
                        length_sample(field, field.min_length - 1),
                        f"长度{field.min_length - 1}（最小长度-1）",
                        False,
                    )
                )
            points.append(
                BoundaryPoint(
                    length_sample(field, field.min_length), f"长度{field.min_length}（最小长度）", True
                )
            )
            points.append(
                BoundaryPoint(
                    length_sample(field, field.min_length + 1),
                    f"长度{field.min_length + 1}（最小长度+1）",
                    True,
                )
            )
        if field.max_length is not None:
            points.append(
                BoundaryPoint(
                    length_sample(field, field.max_length - 1),
                    f"长度{field.max_length - 1}（最大长度-1）",
                    True,
                )
            )
            points.append(
                BoundaryPoint(
                    length_sample(field, field.max_length), f"长度{field.max_length}（最大长度）", True
                )
            )
            points.append(
                BoundaryPoint(
                    length_sample(field, field.max_length + 1),
                    f"长度{field.max_length + 1}（最大长度+1）",
                    False,
                )
            )
        return points


def describe(value: str) -> str:
    if value == "":
        return "空值"
    if value == "ILLEGAL_ENUM":
        return "非法枚举值"
    if value.strip() == "" and value:
        return f"{len(value)} 个空格"
    if len(value) > 12:
        return f"长度 {len(value)} 的字符串"
    return f"「{truncate(value, 24)}」"


def dedupe_points(points: list[BoundaryPoint]) -> list[BoundaryPoint]:
    """按取值去重，并解决"同一取值被两条约束分别判为范围内/越界"的冲突。

    典型场景：最小长度 == 最大长度（如「11位数字」），此时 min+1 与 max+1 是同一个
    取值，但前者按"最小长度边界"判为有效、后者按"最大长度边界"判为越界。
    测试数据必须同时满足全部约束，因此冲突时一律以「越界」为准，
    否则会产出"断言成功、实际被系统拒绝"的错误用例。
    """
    merged: dict[str, BoundaryPoint] = {}
    for point in points:
        existing = merged.get(point.value)
        if existing is None:
            merged[point.value] = point
            continue
        if existing.valid and not point.valid:
            merged[point.value] = point
    return list(merged.values())
