"""正交实验设计策略（V2.0 S2 落点）。

算法（因子水平 -> 正交表 -> 用例）：

  1. **因子水平**：字段约束天然就是因子 —— 枚举取值是一个因子（水平=各枚举值）、
     布尔是二水平因子、数值/长度区间取「下界/中值/上界」三个代表水平。
     没有区间、没有枚举的字段（如纯文本备注）没有水平，不构成因子。
  2. **正交表**：目标是用尽量少的行覆盖**全部因子水平的两两组合**（Pairwise）。
     实现上用「全组合作为候选 + 贪心集合覆盖 + 冗余行剔除」求近优覆盖表：
     结果确定性可复现（不引入随机数），并在收尾处**自校验**是否真的覆盖了所有
     水平对 —— 覆盖表算错却当成正确结果交付，是这类方法最危险的失败模式。
  3. **生成用例**：每行一条用例，测试数据即该行的因子水平取值组合。

明确边界：本实现产出的是**两两覆盖表（covering array）**，不是严格的
正交表（orthogonal array）。严格正交表只在因子/水平数恰好匹配已知设计时才存在，
而两两覆盖对缺陷检出率的收益与正交表等价，且对任意因子数都可用，因此工程上取前者。
压缩收益写入告警：全组合数与实际用例数一并给出，收益不足时如实提示。
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import product

from app.design.base import DesignStrategy, format_number, length_sample
from app.schemas.common import CaseType, DataType, DesignMethod
from app.schemas.requirement import FieldConstraint, RequirementItem
from app.schemas.testcase import TestCase, TestStep

#: 因子数上限（受 2^n 条件空间与人工复核成本约束）。
MAX_FACTORS = 6

#: 单个因子的水平数上限。
MAX_LEVELS = 4

#: 候选全组合上限；超出时先削减水平最多的因子，保证贪心求解可控。
MAX_CANDIDATES = 4096

#: 压缩比高于该阈值时提示「收益有限」，避免让人误以为一定省了用例。
WEAK_REDUCTION_RATIO = 0.3


@dataclass(slots=True)
class Factor:
    """一个实验因子及其水平取值。"""

    name: str
    label: str
    levels: list[str]
    source: str = "constraint"

    def describe(self) -> str:
        """紧凑描述：水平取值可能是 20 个填充字符（如「AAAAAAAAAAAAAAAAAAAA」），
        原样铺开会把一条提示撑到几百字，把界面刷屏。这里只保留前两个水平各 8 个字符。
        """
        shown = " / ".join(_clip(level) for level in self.levels[:2])
        if len(self.levels) > 2:
            shown += f" / 等 {len(self.levels)} 个水平"
        return f"{self.label}[{shown}]"


def _clip(value: str, limit: int = 8) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass(slots=True)
class CoveringArray:
    """覆盖表结果与自校验信息。"""

    factors: list[Factor]
    rows: list[list[int]]
    total_combinations: int
    uncovered_pairs: list[str] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def pair_count(self) -> int:
        """需要覆盖的水平对总数。"""
        total = 0
        for i in range(len(self.factors)):
            for j in range(i + 1, len(self.factors)):
                total += len(self.factors[i].levels) * len(self.factors[j].levels)
        return total

    @property
    def reduction_ratio(self) -> float:
        if self.total_combinations <= 0:
            return 1.0
        return self.row_count / self.total_combinations


# --------------------------------------------------------------------------- #
# 因子构造
# --------------------------------------------------------------------------- #


def build_factors(
    item: RequirementItem, *, max_factors: int = MAX_FACTORS
) -> tuple[list[Factor], list[str]]:
    """从字段约束构造因子；返回 (因子列表, 告警)。"""
    warnings: list[str] = []
    factors: list[Factor] = []
    for constraint in item.testable_fields:
        factor = factor_for_field(constraint, warnings)
        if factor is None:
            continue
        factors.append(factor)
        if len(factors) >= max_factors:
            warnings.append(
                f"字段约束中可构成因子的超过 {max_factors} 个，已只取前 {max_factors} 个，"
                "其余字段建议用等价类/边界值方法覆盖。"
            )
            break
    return factors, warnings


def factor_for_field(field: FieldConstraint, warnings: list[str]) -> Factor | None:
    """把一个字段转成因子；水平不足 2 个时返回 None。"""
    levels: list[str] = []
    source = "constraint"
    if field.enum_values:
        levels = list(dict.fromkeys(field.enum_values))
        source = "enum"
        if len(levels) > MAX_LEVELS:
            warnings.append(
                f"字段「{field.display_name}」枚举取值 {len(levels)} 个，"
                f"正交实验只取前 {MAX_LEVELS} 个作为水平，其余由等价类方法覆盖。"
            )
            levels = levels[:MAX_LEVELS]
    elif field.data_type is DataType.BOOLEAN:
        levels = ["true", "false"]
        source = "boolean"
    elif field.has_numeric_range:
        levels = numeric_levels(field)
        source = "numeric"
    elif field.has_length_range:
        levels = length_levels(field)
        source = "length"

    levels = _dedupe(levels)
    if len(levels) < 2:
        return None
    return Factor(name=field.name, label=field.display_name, levels=levels, source=source)


def numeric_levels(field: FieldConstraint) -> list[str]:
    """数值区间取「下界 / 中值 / 上界」三个代表水平。"""
    if field.min_value is None:
        return [format_number(field.max_value - 1), format_number(field.max_value)]
    if field.max_value is None:
        return [format_number(field.min_value), format_number(field.min_value + 1)]
    low, high = field.min_value, field.max_value
    if float(low).is_integer() and float(high).is_integer():
        middle = int(low + (high - low) // 2)
        return [format_number(low), format_number(middle), format_number(high)]
    return [format_number(low), format_number(round((low + high) / 2, 2)), format_number(high)]


def length_levels(field: FieldConstraint) -> list[str]:
    """长度区间取「最小长度 / 中值长度 / 最大长度」三个代表水平。"""
    if field.min_length is None:
        top = field.max_length or 1
        sizes = [max(top - 1, 0), top]
    elif field.max_length is None:
        sizes = [field.min_length, field.min_length + 1]
    else:
        sizes = [field.min_length, (field.min_length + field.max_length) // 2, field.max_length]
    return [length_sample(field, max(size, 0)) for size in sizes if size >= 0]


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


# --------------------------------------------------------------------------- #
# 覆盖表
# --------------------------------------------------------------------------- #


def build_covering_array(
    factors: list[Factor], *, max_candidates: int = MAX_CANDIDATES
) -> CoveringArray:
    """求「两两覆盖」的近优覆盖表，并自校验覆盖完整性。"""
    active = list(factors)
    total = product_size(active)
    while active and total > max_candidates:
        # 因子水平数越多，全组合膨胀得越快：优先削掉水平最多的那个因子。
        victim = max(range(len(active)), key=lambda index: len(active[index].levels))
        active.pop(victim)
        total = product_size(active)

    if len(active) < 2:
        return CoveringArray(factors=active, rows=[], total_combinations=total)

    sizes = [len(factor.levels) for factor in active]
    candidates = list(product(*[range(size) for size in sizes]))
    pair_sets = [pair_set(candidate, len(active)) for candidate in candidates]
    required = required_pairs(sizes)

    remaining = set(required)
    chosen: list[int] = []
    while remaining:
        best_index = -1
        best_gain = 0
        for index, pairs in enumerate(pair_sets):
            gain = len(pairs & remaining)
            if gain > best_gain:
                best_gain, best_index = gain, index
                if gain == len(remaining):
                    break
        if best_index < 0:
            break
        chosen.append(best_index)
        remaining -= pair_sets[best_index]

    chosen = prune_rows(chosen, pair_sets, required)
    rows = [list(candidates[index]) for index in chosen]
    uncovered = describe_uncovered(remaining, active)
    return CoveringArray(
        factors=active,
        rows=rows,
        total_combinations=product_size(active),
        uncovered_pairs=uncovered,
    )


def product_size(factors: list[Factor]) -> int:
    total = 1
    for factor in factors:
        total *= len(factor.levels)
    return total if factors else 0


def pair_set(row: tuple[int, ...], factor_count: int) -> frozenset[tuple[int, int, int, int]]:
    pairs: list[tuple[int, int, int, int]] = []
    for i in range(factor_count):
        for j in range(i + 1, factor_count):
            pairs.append((i, j, row[i], row[j]))
    return frozenset(pairs)


def required_pairs(sizes: list[int]) -> set[tuple[int, int, int, int]]:
    required: set[tuple[int, int, int, int]] = set()
    for i in range(len(sizes)):
        for j in range(i + 1, len(sizes)):
            for left in range(sizes[i]):
                for right in range(sizes[j]):
                    required.add((i, j, left, right))
    return required


def prune_rows(
    chosen: list[int],
    pair_sets: list[frozenset[tuple[int, int, int, int]]],
    required: set[tuple[int, int, int, int]],
) -> list[int]:
    """剔除冗余行：去掉一行后若仍覆盖全部水平对，则该行可省。"""
    kept = list(chosen)
    index = 0
    while index < len(kept) and len(kept) > 1:
        others = set()
        for position, row_index in enumerate(kept):
            if position != index:
                others |= pair_sets[row_index]
        if required <= others:
            del kept[index]
            continue
        index += 1
    return kept


def describe_uncovered(
    remaining: set[tuple[int, int, int, int]], factors: list[Factor]
) -> list[str]:
    items: list[str] = []
    for i, j, left, right in sorted(remaining):
        items.append(
            f"{factors[i].label}={factors[i].levels[left]} × {factors[j].label}={factors[j].levels[right]}"
        )
    return items


# --------------------------------------------------------------------------- #
# 策略
# --------------------------------------------------------------------------- #


class OrthogonalStrategy(DesignStrategy):
    method = DesignMethod.ORTHOGONAL
    description = "把字段约束视为因子与水平，生成两两覆盖的正交表并按行输出用例"

    def is_applicable(self, item: RequirementItem) -> bool:
        factors, _ = build_factors(item)
        return len(factors) >= 2

    async def generate(self, item: RequirementItem) -> list[TestCase]:
        factors, warnings = build_factors(item)
        for message in warnings:
            self.context.warn(message)
        if len(factors) < 2:
            self.context.warn(
                f"需求「{item.title}」只有 {len(factors)} 个可用因子（需要至少 2 个），已跳过正交实验。"
            )
            return []

        array = build_covering_array(factors)
        if not array.rows:
            self.context.warn(f"需求「{item.title}」未能构造出有效的水平覆盖表，已跳过正交实验。")
            return []

        # 一行说清「用了哪些因子、压了多少、覆盖多少」。
        # 「本次压缩收益有限」原本是独立一条，因子少时几乎必然出现，纯属刷屏，合并进本行。
        compact = array.reduction_ratio > WEAK_REDUCTION_RATIO
        hint = "；因子或水平较少时，两两覆盖本身就接近全组合" if compact else ""
        self.context.warn(
            f"「正交实验」需求「{item.title}」：{len(array.factors)} 个因子（"
            + "、".join(factor.label for factor in array.factors)
            + f"），全组合 {array.total_combinations} 种 → 两两覆盖 {array.row_count} 条"
            f"（压缩比 {array.reduction_ratio:.0%}，覆盖 {array.pair_count} 个水平对）{hint}。"
        )
        if array.uncovered_pairs:
            self.context.warn(
                f"「正交实验」仍有 {len(array.uncovered_pairs)} 个水平对未被覆盖："
                + "、".join(array.uncovered_pairs[:5])
                + "，覆盖表生成异常，请人工复核。"
            )

        cases = [
            self._case(item, array, row, index)
            for index, row in enumerate(array.rows, start=1)
        ]
        limit = self.context.max_cases_per_item
        if limit and len(cases) > limit:
            self.context.warn(
                f"「正交实验」生成的覆盖表 {len(cases)} 条超过单条需求上限 {limit}，"
                "截断后**两两覆盖保证不再成立**，请人工补充被截断的水平对。"
            )
            return cases[:limit]
        return cases

    def _case(
        self,
        item: RequirementItem,
        array: CoveringArray,
        row: list[int],
        index: int,
    ) -> TestCase:
        test_data = {
            factor.name: factor.levels[level]
            for factor, level in zip(array.factors, row)
        }
        pairs = "，".join(
            f"{factor.label}={factor.levels[level]}"
            for factor, level in zip(array.factors, row)
        )
        acceptance = item.acceptance_criteria[0] if item.acceptance_criteria else ""
        return self.build_case(
            item,
            title=(
                f"[正交实验] {item.title}｜组合 {index}/{array.row_count}"
                f"（{len(array.factors)} 因子两两覆盖）"
            ),
            case_type=CaseType.FUNCTIONAL,
            steps=[
                TestStep(no=1, action=f"按下述组合设置各因子水平：{pairs}", expected=""),
                TestStep(no=2, action="提交并核对业务处理结果", expected=""),
            ],
            expected_result=acceptance or "该因子水平组合下业务正常处理，无异常与数据不一致。",
            test_data=test_data,
            remarks=(
                f"正交表（两两覆盖）：全组合 {array.total_combinations} 种，"
                f"本表 {array.row_count} 行，覆盖 {array.pair_count} 个水平对；因子水平："
                + "；".join(factor.describe() for factor in array.factors)
            ),
            tags=["正交实验", f"{len(array.factors)}因子", "两两覆盖"],
        )

__all__ = [
    "CoveringArray",
    "Factor",
    "MAX_FACTORS",
    "MAX_LEVELS",
    "OrthogonalStrategy",
    "build_covering_array",
    "build_factors",
    "factor_for_field",
    "prune_rows",
    "required_pairs",
]
