"""V2.0 新增设计方法回归：判定表、因果图、正交实验。"""
from __future__ import annotations

import pytest

from app.design.base import DesignContext
from app.design.cause_effect import (
    CONSTRAINT_EXCLUSIVE,
    CONSTRAINT_INCLUSION,
    CONSTRAINT_MASK,
    CauseEffectStrategy,
    classify_constraint,
    extract_causal_rules,
    split_causal_text,
)
from app.design.coverage import analyze_coverage
from app.design.decision_table import (
    ACCEPT_ACTION,
    DecisionTableStrategy,
    build_conditions,
    compress_rules,
    order_first_action,
    reduce_patterns,
    try_merge,
)
from app.design.engine import DesignEngine
from app.design.orthogonal import OrthogonalStrategy, build_covering_array, build_factors
from app.llm.null_provider import NullProvider
from app.schemas.common import DataType, DesignMethod, Priority
from app.schemas.requirement import FieldConstraint, RequirementDoc, RequirementItem
from app.schemas.testcase import TestCaseSuite


@pytest.fixture
def context(settings) -> DesignContext:
    return DesignContext(settings=settings, llm=NullProvider(settings), use_llm=False)


def multi_condition_item() -> RequirementItem:
    return RequirementItem(
        id="REQ-001",
        title="会员注册",
        module="会员中心",
        priority=Priority.P1,
        fields=[
            FieldConstraint(name="phone", label="手机号", required=True, min_length=11, max_length=11),
            FieldConstraint(name="age", label="年龄", data_type=DataType.INTEGER, min_value=18, max_value=120),
            FieldConstraint(name="level", label="会员等级", data_type=DataType.ENUM, enum_values=["普通", "白银", "黄金"]),
        ],
        business_rules=[
            "若手机号已注册则提示直接登录",
            "不允许使用黑名单渠道注册",
        ],
        exceptions=["短信通道异常"],
    )


# --------------------------------------------------------------------------- #
# 判定表
# --------------------------------------------------------------------------- #


class TestDecisionTable:
    def test_build_conditions_skips_unconstrained_fields(self) -> None:
        item = RequirementItem(
            id="REQ-1",
            title="t",
            fields=[
                FieldConstraint(name="备注", label="备注", data_type=DataType.OTHER),
                FieldConstraint(name="年龄", label="年龄", min_value=1, max_value=10),
            ],
        )
        conditions = build_conditions(item)
        assert [condition.key for condition in conditions] == ["年龄"]

    def test_cap_conditions_at_five(self) -> None:
        item = RequirementItem(
            id="REQ-1",
            title="t",
            fields=[FieldConstraint(name=f"f{i}", label=f"字段{i}", min_value=0, max_value=9) for i in range(8)],
        )
        assert len(build_conditions(item)) == 5

    def test_try_merge_only_when_single_difference(self) -> None:
        assert try_merge([True, False], [True, True]) == [True, None]
        assert try_merge([None, True], [True, True]) == [None, True]
        assert try_merge([True, False, True], [False, True, False]) is None

    def test_reduce_patterns_compresses_cube(self) -> None:
        patterns = [[True, True], [True, False], [False, True], [False, False]]
        reduced = reduce_patterns(patterns)
        assert reduced == [[None, None]]

    def test_compress_yields_n_plus_one_rules(self) -> None:
        conditions = build_conditions(multi_condition_item())
        rules, total = compress_rules(conditions, lambda combo: order_first_action(combo, conditions))
        assert total == 2 ** len(conditions)
        # 按条件顺序短路的动作语义下，2^n 应压缩为「1 条放行 + n 条拒绝」。
        assert len(rules) == len(conditions) + 1
        accepted = [rule for rule in rules if rule.action_key.startswith("0-")]
        assert len(accepted) == 1
        assert all(condition is True for condition in accepted[0].conditions)

    async def test_generate_marks_dont_care_and_records_compression(self, context) -> None:
        item = multi_condition_item()
        cases = await DecisionTableStrategy(context).generate(item)
        assert len(cases) == 4
        assert all(case.design_method is DesignMethod.DECISION_TABLE for case in cases)
        assert any("无关项" in case.title or "任意" in case.remarks for case in cases)
        assert any("无关项合并后保留" in warning for warning in context.warnings), context.warnings

    async def test_valid_rule_uses_conforming_values(self, context) -> None:
        cases = await DecisionTableStrategy(context).generate(multi_condition_item())
        accepted = next(case for case in cases if ACCEPT_ACTION in case.expected_result)
        assert accepted.test_data["phone"]
        assert 18 <= int(accepted.test_data["age"]) <= 120
        assert accepted.test_data["level"] in {"普通", "白银", "黄金"}

    async def test_not_applicable_below_two_conditions(self, context) -> None:
        item = RequirementItem(
            id="REQ-1", title="单一条件", fields=[FieldConstraint(name="年龄", label="年龄", min_value=1, max_value=10)]
        )
        strategy = DecisionTableStrategy(context)
        assert strategy.is_applicable(item) is False
        assert await strategy.generate(item) == []


# --------------------------------------------------------------------------- #
# 因果图
# --------------------------------------------------------------------------- #


class TestCauseEffect:
    def test_split_causal_text_extracts_cause_and_effect(self) -> None:
        pairs = split_causal_text("若手机号已注册则提示直接登录")
        assert pairs == [("手机号已注册", "提示直接登录")]

    def test_masking_rule_without_connective(self) -> None:
        cause, effect = split_causal_text("不允许昵称包含敏感词")[0]
        assert "不允许" in cause
        assert "阻断" in effect

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("不允许使用黑名单渠道", CONSTRAINT_MASK),
            ("注册渠道只能取其一", CONSTRAINT_EXCLUSIVE),
            ("若 A 则 B", CONSTRAINT_INCLUSION),
        ],
    )
    def test_classify_constraint(self, text: str, expected: str) -> None:
        assert classify_constraint(text) == expected

    def test_rules_are_deduplicated(self) -> None:
        rules = extract_causal_rules(multi_condition_item())
        keys = {(rule.cause, rule.effect) for rule in rules}
        assert len(keys) == len(rules)
        assert len(rules) >= 2

    async def test_masking_produces_dont_care(self, context) -> None:
        cases = await CauseEffectStrategy(context).generate(multi_condition_item())
        assert cases
        assert all(case.design_method is DesignMethod.CAUSE_EFFECT for case in cases)
        assert any("屏蔽型因果生效" in case.expected_result for case in cases)
        # 屏蔽规则会把其它因变成无关项，从而出现「任意」。
        assert any(
            "无关项" in case.remarks or "任意" in case.steps[0].action for case in cases
        )

    async def test_field_backed_cause_lands_in_test_data(self, context) -> None:
        item = RequirementItem(
            id="REQ-1",
            title="校验",
            fields=[
                FieldConstraint(name="phone", label="手机号", required=True, min_length=11, max_length=11),
                FieldConstraint(name="age", label="年龄", min_value=18, max_value=120),
            ],
            business_rules=["若 phone 不满足格式则拒绝提交"],
        )
        cases = await CauseEffectStrategy(context).generate(item)
        assert any(case.test_data.get("phone") for case in cases)

    async def test_not_applicable_without_causes(self, context) -> None:
        item = RequirementItem(id="REQ-1", title="纯描述", description="系统应支持查询。")
        assert CauseEffectStrategy(context).is_applicable(item) is False


# --------------------------------------------------------------------------- #
# 正交实验
# --------------------------------------------------------------------------- #


def four_factor_item() -> RequirementItem:
    return RequirementItem(
        id="REQ-1",
        title="下单参数组合",
        fields=[
            FieldConstraint(name="channel", label="渠道", data_type=DataType.ENUM, enum_values=["APP", "小程序", "Web"]),
            FieldConstraint(name="level", label="会员等级", data_type=DataType.ENUM, enum_values=["普通", "白银", "黄金"]),
            FieldConstraint(name="pay", label="支付方式", data_type=DataType.ENUM, enum_values=["余额", "微信", "支付宝"]),
            FieldConstraint(name="delivery", label="配送方式", data_type=DataType.ENUM, enum_values=["自提", "快递", "同城"]),
        ],
    )


class TestOrthogonal:
    def test_factors_from_constraints(self) -> None:
        factors, _ = build_factors(four_factor_item())
        assert len(factors) == 4
        assert all(len(factor.levels) == 3 for factor in factors)

    def test_numeric_range_gives_three_levels(self) -> None:
        item = RequirementItem(
            id="REQ-1",
            title="t",
            fields=[FieldConstraint(name="age", label="年龄", min_value=18, max_value=120)],
        )
        factors, _ = build_factors(item)
        assert factors == [] or factors[0].levels == ["18", "69", "120"]

    def test_boolean_field_is_two_level_factor(self) -> None:
        item = RequirementItem(
            id="REQ-1",
            title="t",
            fields=[
                FieldConstraint(name="auto", label="自动续费", data_type=DataType.BOOLEAN),
                FieldConstraint(name="level", label="等级", enum_values=["A", "B"]),
            ],
        )
        factors, _ = build_factors(item)
        assert factors[0].levels == ["true", "false"]

    def test_covering_array_covers_all_pairs_and_is_small(self) -> None:
        factors, _ = build_factors(four_factor_item())
        array = build_covering_array(factors)
        assert array.total_combinations == 81
        assert array.uncovered_pairs == []
        # 验收标准：用例数不超过全组合的 30%，且覆盖全部因子水平对。
        assert array.row_count <= 0.3 * array.total_combinations
        assert array.pair_count == 6 * 9  # C(4,2) * 3 * 3

    def test_covering_array_is_deterministic(self) -> None:
        factors, _ = build_factors(four_factor_item())
        assert build_covering_array(factors).rows == build_covering_array(factors).rows

    async def test_generate_reports_compression(self, context) -> None:
        item = four_factor_item()
        cases = await OrthogonalStrategy(context).generate(item)
        assert cases
        assert all(case.design_method is DesignMethod.ORTHOGONAL for case in cases)
        assert all(len(case.test_data) == 4 for case in cases)
        # 提示要一行说清「因子 → 全组合 → 两两覆盖」，而不是连着刷三条。
        assert any(
            "全组合" in warning and "两两覆盖" in warning and "水平对" in warning
            for warning in context.warnings
        ), context.warnings
        assert not any("收益有限" in warning for warning in context.warnings)
        assert not any("仍有" in warning and "未被覆盖" in warning for warning in context.warnings)

    async def test_not_applicable_with_single_factor(self, context) -> None:
        item = RequirementItem(
            id="REQ-1",
            title="单因子",
            fields=[FieldConstraint(name="level", label="等级", enum_values=["A", "B", "C"])],
        )
        assert OrthogonalStrategy(context).is_applicable(item) is False

    async def test_truncation_warns_coverage_lost(self, settings) -> None:
        item = four_factor_item()
        ctx = DesignContext(settings=settings, llm=NullProvider(settings), max_cases_per_item=2)
        cases = await OrthogonalStrategy(ctx).generate(item)
        assert len(cases) == 2
        assert any("两两覆盖保证不再成立" in warning for warning in ctx.warnings)


# --------------------------------------------------------------------------- #
# 引擎集成
# --------------------------------------------------------------------------- #


async def test_engine_generates_v2_methods_together(settings) -> None:
    doc = RequirementDoc(doc_id="DOC-1", title="会员注册", items=[multi_condition_item()])
    suite = await DesignEngine(settings).generate(
        doc,
        ["equivalence", "boundary", "decision_table", "cause_effect", "orthogonal"],
        llm=NullProvider(settings),
        use_llm=False,
    )
    methods = {case.design_method for case in suite.cases}
    assert DesignMethod.DECISION_TABLE in methods
    assert DesignMethod.CAUSE_EFFECT in methods
    # 编号前缀必须能区分新方法，落在 Excel 里才认得出来是谁生成的。
    prefixes = {case.case_id.split("-")[1] for case in suite.cases}
    assert {"DT", "CE"} <= prefixes
    assert suite.stats.total == len(suite.cases)


async def test_v2_case_ids_and_ordering(settings) -> None:
    doc = RequirementDoc(doc_id="DOC-1", title="会员注册", items=[four_factor_item()])
    suite = await DesignEngine(settings).generate(
        doc, ["orthogonal"], llm=NullProvider(settings), use_llm=False
    )
    assert all(case.case_id.startswith("TC-OR-") for case in suite.cases)


def test_coverage_report_available_for_v2_suite(settings) -> None:
    """覆盖率分析要能吃下新方法产出的用例（口径一致，不因方法新增而失效）。"""
    import asyncio

    item = multi_condition_item()
    doc = RequirementDoc(doc_id="DOC-1", title="会员注册", items=[item])
    suite = asyncio.run(
        DesignEngine(settings).generate(
            doc, ["decision_table", "orthogonal"], llm=NullProvider(settings), use_llm=False
        )
    )
    report = analyze_coverage(doc, suite)
    assert report.dimensions
    assert report.summary
    assert isinstance(suite, TestCaseSuite)
