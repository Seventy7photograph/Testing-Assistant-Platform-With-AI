"""设计策略单测：等价类、边界值、场景法、优化器、未实现占位。"""
from __future__ import annotations

import re

import pytest

from app.core.exceptions import FeatureNotAvailableError, NotFoundError
from app.design.base import DesignContext
from app.design.boundary import BoundaryStrategy
from app.design.engine import DesignEngine
from app.design.equivalence import EquivalenceStrategy
from app.design.optimizer import assign_case_ids, deduplicate, fingerprint, optimize, overlap_key, sort_cases
from app.design.scenario import ScenarioStrategy, describe_test_data_issues, repair_test_data
from app.llm.fake_provider import FakeProvider
from app.llm.prompts import TASK_SCENARIO_ENRICHMENT
from app.llm.null_provider import NullProvider
from app.schemas.common import CaseType, DataType, DesignMethod, Priority, ValueCharset
from app.schemas.requirement import FieldConstraint, RequirementDoc, RequirementItem
from app.schemas.testcase import TestCase, TestStep


@pytest.fixture
def context(settings) -> DesignContext:
    return DesignContext(settings=settings, llm=NullProvider(settings), use_llm=False)


@pytest.fixture
def llm_context(settings) -> DesignContext:
    return DesignContext(settings=settings, llm=FakeProvider(settings), use_llm=True)


# --------------------------------------------------------------------------- #
# 等价类
# --------------------------------------------------------------------------- #
async def test_equivalence_partitions_numeric_range(context, sample_item) -> None:
    cases = await EquivalenceStrategy(context).generate(sample_item)
    age_cases = [case for case in cases if "age" in case.test_data]
    values = {case.test_data["age"] for case in age_cases}
    assert {"69", "17", "121"} <= values  # 有效代表值 + 上界外 + 下界外
    types = {case.case_type for case in age_cases}
    assert CaseType.EXCEPTION in types and CaseType.FUNCTIONAL in types


async def test_equivalence_covers_enum_and_required(context, sample_item) -> None:
    cases = await EquivalenceStrategy(context).generate(sample_item)
    status_values = {case.test_data["status"] for case in cases if "status" in case.test_data}
    assert {"待激活", "已激活", "已冻结"} <= status_values
    phone_cases = [case for case in cases if "phone" in case.test_data]
    assert any(case.test_data["phone"] == "" for case in phone_cases)
    assert any(case.priority is Priority.P1 for case in phone_cases if case.test_data["phone"] == "")


async def test_equivalence_falls_back_to_item_level(context) -> None:
    item = RequirementItem(id="REQ-001", title="导出报表", description="用户可以导出报表。")
    cases = await EquivalenceStrategy(context).generate(item)
    assert len(cases) == 2
    assert any("异常输入" in case.title for case in cases)
    assert context.warnings


# --------------------------------------------------------------------------- #
# 边界值
# --------------------------------------------------------------------------- #
async def test_boundary_numeric_points(context, sample_item) -> None:
    cases = await BoundaryStrategy(context).generate(sample_item)
    values = {case.test_data["age"] for case in cases if "age" in case.test_data}
    assert values == {"17", "18", "19", "119", "120", "121"}
    invalid = {case.test_data["age"] for case in cases if case.test_data.get("age") in {"17", "121"}}
    assert invalid == {"17", "121"}
    assert all(
        case.case_type is CaseType.EXCEPTION for case in cases if case.test_data.get("age") in {"17", "121"}
    )


async def test_boundary_length_points(context, sample_item) -> None:
    cases = await BoundaryStrategy(context).generate(sample_item)
    lengths = {len(case.test_data["phone"]) for case in cases if "phone" in case.test_data}
    assert {10, 11, 12} <= lengths


async def test_boundary_fixed_length_out_of_range_is_invalid(context) -> None:
    """min_length == max_length（如「6位验证码」）时，超出上限的取值必须判为越界。

    历史缺陷：等长字段的 max+1 与 min+1 是同一个取值，去重时按"先出现的边界"保留了
    "最小长度+1=有效"，导致越界数据被标成有效用例。
    """
    field = FieldConstraint(name="code", label="验证码", min_length=6, max_length=6)
    item = RequirementItem(id="REQ-001", title="验证码校验", fields=[field])
    cases = await BoundaryStrategy(context).generate(item)

    over = next(c for c in cases if len(c.test_data.get("code", "")) == 7)
    assert over.case_type is CaseType.EXCEPTION, over.title
    assert "最大长度+1" in over.title

    under = next(c for c in cases if len(c.test_data.get("code", "")) == 5)
    assert under.case_type is CaseType.EXCEPTION, under.title

    exact = next(c for c in cases if len(c.test_data.get("code", "")) == 6)
    assert exact.case_type is CaseType.BOUNDARY, exact.title


async def test_boundary_enum_first_last(context, sample_item) -> None:
    cases = await BoundaryStrategy(context).generate(sample_item)
    status_values = {case.test_data["status"] for case in cases if "status" in case.test_data}
    assert {"待激活", "已冻结", "ILLEGAL_ENUM"} <= status_values


async def test_boundary_skips_item_without_constraints(context) -> None:
    item = RequirementItem(id="REQ-001", title="纯描述需求", description="系统应支持查询。")
    cases = await BoundaryStrategy(context).generate(item)
    assert cases == []
    assert context.warnings


async def test_boundary_truncates_when_limit_exceeded(settings) -> None:
    many_fields = [
        FieldConstraint(name=f"f{i}", label=f"字段{i}", min_value=0, max_value=1000) for i in range(10)
    ]
    item = RequirementItem(id="REQ-001", title="大表单", fields=many_fields)
    ctx = DesignContext(settings=settings, llm=NullProvider(settings), max_cases_per_item=5)
    cases = await BoundaryStrategy(ctx).generate(item)
    assert len(cases) == 5
    # 措辞要能区分「单方法上限」与「单条需求用例上限」——两者同值但口径不同，
    # 早期只说「超过上限 5」会让人误以为是自己设的那条上限生效了。
    assert any("单方法产出" in warning and "单方法上限" in warning for warning in ctx.warnings), ctx.warnings


# --------------------------------------------------------------------------- #
# 场景法
# --------------------------------------------------------------------------- #
async def test_scenario_rule_cases(context, sample_item) -> None:
    cases = await ScenarioStrategy(context).generate(sample_item)
    titles = [case.title for case in cases]
    assert any("主流程" in title for title in titles)
    assert any("备选流" in title for title in titles)
    assert any("异常场景" in title for title in titles)
    assert any("业务规则" in title for title in titles)
    main = next(case for case in cases if "主流程" in case.title)
    assert len(main.steps) == 3
    assert main.case_type is CaseType.SCENARIO
    assert main.expected_result == "注册成功后自动登录"


async def test_scenario_llm_enrichment(llm_context, sample_item) -> None:
    strategy = ScenarioStrategy(llm_context)
    cases = await strategy.generate(sample_item)
    llm_cases = [case for case in cases if case.source.value == "llm"]
    assert llm_cases, "FakeProvider 应产出 LLM 增强用例"
    assert all(case.title.startswith("[场景-LLM]") for case in llm_cases)
    assert llm_context.llm_call_count == 1


async def test_scenario_llm_overlong_valid_data_is_repaired(settings, sample_item) -> None:
    """LLM 在正常/边界用例里给出越界数据时，应修正为满足约束的值并记录告警。"""
    scripted = {
        TASK_SCENARIO_ENRICHMENT: {
            "cases": [
                {
                    "title": "手机号边界组合",
                    "case_type": "边界",
                    "priority": "P1",
                    "test_data": {"phone": "13800138000123"},
                }
            ]
        }
    }
    context = DesignContext(
        settings=settings, llm=FakeProvider(settings, scripted=scripted), use_llm=True
    )
    cases = await ScenarioStrategy(context).generate(sample_item)
    llm_case = next(case for case in cases if case.source.value == "llm")
    assert re.fullmatch(r"^1[3-9]\d{9}$", llm_case.test_data["phone"])
    assert describe_test_data_issues(sample_item, llm_case.test_data, CaseType.BOUNDARY) == []
    assert any("已按约束修正" in warning for warning in context.warnings)


async def test_scenario_llm_failure_degrades(settings, sample_item) -> None:
    class BrokenProvider(FakeProvider):
        async def complete(self, *args, **kwargs):  # type: ignore[override]
            from app.core.exceptions import LLMError

            raise LLMError("模拟网络故障")

    ctx = DesignContext(settings=settings, llm=BrokenProvider(settings), use_llm=True)
    cases = await ScenarioStrategy(ctx).generate(sample_item)
    assert cases, "LLM 失败时仍应保留规则用例"
    assert all(case.source.value == "rule" for case in cases)
    assert any("LLM" in warning for warning in ctx.warnings)


# --------------------------------------------------------------------------- #
# 优化器
# --------------------------------------------------------------------------- #
def _case(title: str, **kwargs) -> TestCase:
    defaults = dict(
        title=title,
        design_method=DesignMethod.EQUIVALENCE,
        case_type=CaseType.FUNCTIONAL,
        priority=Priority.P2,
        steps=[TestStep(no=1, action="操作")],
    )
    defaults.update(kwargs)
    return TestCase(**defaults)


def test_deduplicate_merges_requirement_ids() -> None:
    first = _case("用例A", requirement_ids=["REQ-001"], test_data={"a": "1"})
    second = _case("用例A ", requirement_ids=["REQ-002"], test_data={"a": "1"})
    unique, duplicates = deduplicate([first, second])
    assert duplicates == 1
    assert len(unique) == 1
    assert unique[0].requirement_ids == ["REQ-001", "REQ-002"]


def test_deduplicate_keeps_different_test_data() -> None:
    unique, duplicates = deduplicate(
        [_case("用例A", test_data={"a": "1"}), _case("用例A", test_data={"a": "2"})]
    )
    assert (len(unique), duplicates) == (2, 0)


def test_sort_and_assign_ids() -> None:
    cases = [
        _case("B用例", priority=Priority.P2, design_method=DesignMethod.SCENARIO),
        _case("A用例", priority=Priority.P0, design_method=DesignMethod.EQUIVALENCE),
        _case("C用例", priority=Priority.P1, design_method=DesignMethod.BOUNDARY),
    ]
    ordered, _ = optimize(cases)
    assert [case.title for case in ordered] == ["A用例", "C用例", "B用例"]
    assert [case.case_id for case in ordered] == ["TC-EQ-001", "TC-BV-001", "TC-SC-001"]


def test_sort_cases_is_stable_by_module() -> None:
    cases = [_case("a", module="B模块"), _case("b", module="A模块")]
    sorted_cases = sort_cases(cases)
    assert [case.module for case in sorted_cases] == ["A模块", "B模块"]


def test_assign_case_ids_increments_per_method() -> None:
    cases = [_case("t1"), _case("t2")]
    assign_case_ids(cases)
    assert [case.case_id for case in cases] == ["TC-EQ-001", "TC-EQ-002"]


# --------------------------------------------------------------------------- #
# 引擎
# --------------------------------------------------------------------------- #
async def test_engine_generates_suite(settings, sample_item) -> None:
    doc = RequirementDoc(doc_id="DOC-1", title="订单需求", items=[sample_item])
    engine = DesignEngine(settings)
    suite = await engine.generate(
        doc, ["equivalence", "boundary", "scenario"], llm=NullProvider(settings), use_llm=True
    )
    assert suite.stats.total > 0
    assert suite.stats.total == len(suite.cases)
    assert suite.stats.requirement_coverage.get("REQ-001") == suite.stats.total
    assert len({case.case_id for case in suite.cases}) == suite.stats.total
    assert suite.generation_meta.fallback_used is True
    assert any("未启用大模型" in warning for warning in suite.generation_meta.warnings)


async def test_engine_accepts_v2_methods(settings) -> None:
    """V2.0 起判定表 / 因果图 / 正交实验都是已实现方法，不再抛 501。"""
    engine = DesignEngine(settings)
    resolved = engine.resolve_methods(["decision_table", "cause_effect", "orthogonal"])
    assert [method.value for method in resolved] == [
        "decision_table",
        "cause_effect",
        "orthogonal",
    ]


def test_engine_rejects_unknown_method(settings) -> None:
    engine = DesignEngine(settings)
    with pytest.raises(NotFoundError):
        engine.resolve_methods(["not_a_method"])


def test_engine_lists_all_methods_as_implemented(settings) -> None:
    engine = DesignEngine(settings)
    methods = {item["name"]: item["implemented"] for item in engine.available_methods()}
    assert methods["equivalence"] is True
    assert methods["decision_table"] is True
    assert methods["cause_effect"] is True
    assert methods["orthogonal"] is True


# --------------------------------------------------------------------------- #
# 缺陷回归：数字串字段的测试数据必须是数字
# --------------------------------------------------------------------------- #
def _digit_field() -> FieldConstraint:
    return FieldConstraint(
        name="phone",
        label="手机号",
        data_type=DataType.STRING,
        required=True,
        nullable=False,
        min_length=11,
        max_length=11,
        pattern=r"^1[3-9]\d{9}$",
        value_charset=ValueCharset.DIGITS,
    )


async def test_digit_charset_field_uses_digits(context) -> None:
    """「11位数字」字段的有效/边界数据都必须是数字，不能填成 A。"""
    item = RequirementItem(id="REQ-001", title="注册", fields=[_digit_field()])

    eq_cases = await EquivalenceStrategy(context).generate(item)
    valid = [case.test_data["phone"] for case in eq_cases if case.case_type is CaseType.FUNCTIONAL]
    for value in valid:
        assert value.isdigit(), f"有效等价类出现非数字数据：{value!r}"
    assert any(value == "13800138000" for value in valid), "应使用符合手机号正则的样例值"

    bv_cases = await BoundaryStrategy(context).generate(item)
    for case in bv_cases:
        value = case.test_data.get("phone", "")
        assert value == "" or value.isdigit(), f"边界数据出现非数字：{value!r}"


async def test_text_charset_field_keeps_alpha_filler(context) -> None:
    """普通文本长度字段仍按字母填充，保持既有行为。"""
    field = FieldConstraint(name="nickname", label="昵称", min_length=2, max_length=20)
    item = RequirementItem(id="REQ-001", title="注册", fields=[field])
    cases = await BoundaryStrategy(context).generate(item)
    values = {case.test_data["nickname"] for case in cases if "nickname" in case.test_data}
    assert "AA" in values


# --------------------------------------------------------------------------- #
# 去重：跨方法「同一测试点」合并（缺陷回归）
# --------------------------------------------------------------------------- #
def _point(title: str, method: DesignMethod, data: dict[str, str], **kwargs) -> TestCase:
    defaults = dict(
        title=title,
        design_method=method,
        case_type=CaseType.EXCEPTION,
        requirement_ids=["REQ-001"],
        test_data=data,
        steps=[TestStep(no=1, action="提交")],
    )
    defaults.update(kwargs)
    return TestCase(**defaults)


def test_deduplicate_merges_cross_method_same_test_point() -> None:
    """同一需求下，等价类与边界值对「必填留空」各产一条，应合并为一条并记录覆盖方法。"""
    eq = _point("[等价类] 注册｜手机号 无效等价类（必填字段留空）", DesignMethod.EQUIVALENCE, {"手机号": ""})
    bv = _point("[边界值] 注册｜手机号 必填边界（留空）", DesignMethod.BOUNDARY, {"手机号": ""})

    unique, duplicates = deduplicate([eq, bv])

    assert (len(unique), duplicates) == (1, 1)
    assert unique[0].design_method is DesignMethod.EQUIVALENCE
    assert {method.value for method in unique[0].covered_methods} == {"equivalence", "boundary"}


def test_deduplicate_merges_out_of_range_length_points() -> None:
    """越界长度在两种方法下测试数据完全相同，也应合并。"""
    eq = _point("[等价类] 注册｜手机号 无效等价类（长度小于最小长度 11）", DesignMethod.EQUIVALENCE, {"手机号": "1111111111"})
    bv = _point("[边界值] 注册｜手机号 长度10（最小长度-1）", DesignMethod.BOUNDARY, {"手机号": "1111111111"})
    unique, duplicates = deduplicate([eq, bv])
    assert (len(unique), duplicates) == (1, 1)


def test_deduplicate_never_merges_empty_test_data_cases() -> None:
    """场景法用例 test_data 为空，绝不能按"数据相同"互相合并。"""
    main = _point("[场景] 注册｜主流程（正常场景）", DesignMethod.SCENARIO, {}, case_type=CaseType.SCENARIO)
    alt = _point("[场景] 注册｜备选流 1：手机号已注册", DesignMethod.SCENARIO, {}, case_type=CaseType.SCENARIO)
    assert overlap_key(main) is None

    unique, duplicates = deduplicate([main, alt])

    assert (len(unique), duplicates) == (2, 0)


def test_deduplicate_keeps_cases_of_different_requirements() -> None:
    """不同需求条目下的相同数据不是重复用例，不能合并。"""
    first = _point("t1", DesignMethod.EQUIVALENCE, {"手机号": ""}, requirement_ids=["REQ-001"])
    second = _point("t2", DesignMethod.BOUNDARY, {"手机号": ""}, requirement_ids=["REQ-002"])
    unique, duplicates = deduplicate([first, second])
    assert (len(unique), duplicates) == (2, 0)


def test_deduplicate_keeps_different_case_types() -> None:
    """数据类型相同但用例类型不同（正常 vs 异常），预期行为不同，不能合并。"""
    functional = _point("t1", DesignMethod.EQUIVALENCE, {"手机号": "1"}, case_type=CaseType.FUNCTIONAL)
    exception = _point("t2", DesignMethod.BOUNDARY, {"手机号": "1"}, case_type=CaseType.EXCEPTION)
    unique, duplicates = deduplicate([functional, exception])
    assert (len(unique), duplicates) == (2, 0)


def test_deduplicate_marks_hybrid_source() -> None:
    """规则用例与 LLM 用例指向同一测试点时，来源应标记为 hybrid。"""
    from app.schemas.common import CaseSource

    rule = _point("t1", DesignMethod.BOUNDARY, {"手机号": ""}, source=CaseSource.RULE)
    llm = _point("t2", DesignMethod.BOUNDARY, {"手机号": ""}, source=CaseSource.LLM)
    unique, duplicates = deduplicate([rule, llm])
    assert (len(unique), duplicates) == (1, 1)
    assert unique[0].source is CaseSource.HYBRID


def test_optimize_populates_covered_methods() -> None:
    """优化后每条用例都应带 covered_methods，便于导出与展示。"""
    ordered, _ = optimize([_point("t1", DesignMethod.EQUIVALENCE, {"a": "1"}, case_type=CaseType.FUNCTIONAL)])
    assert [method.value for method in ordered[0].covered_methods] == ["equivalence"]


def test_fingerprint_stable_but_overlap_ignores_title() -> None:
    """精确指纹含标题；重叠键只关心模块/类型/数据，因此跨方法可命中。"""
    eq = _point("[等价类] 注册｜手机号 无效等价类（必填字段留空）", DesignMethod.EQUIVALENCE, {"手机号": ""})
    bv = _point("[边界值] 注册｜手机号 必填边界（留空）", DesignMethod.BOUNDARY, {"手机号": ""})
    assert fingerprint(eq) != fingerprint(bv)
    assert overlap_key(eq) == overlap_key(bv)


async def test_engine_deduplicates_across_methods(settings) -> None:
    """端到端：仅带必填约束的字段，等价类与边界值的留空用例应合并。"""
    item = RequirementItem(
        id="REQ-001",
        title="注册",
        fields=[FieldConstraint(name="手机号", label="手机号", required=True)],
    )
    doc = RequirementDoc(doc_id="DOC-1", title="注册需求", items=[item])
    suite = await DesignEngine(settings).generate(
        doc, ["equivalence", "boundary"], llm=NullProvider(settings), use_llm=False
    )

    blanks = [case for case in suite.cases if case.test_data.get("手机号") == ""]
    assert len(blanks) == 1, "留空用例应只保留一条"
    assert suite.stats.duplicate_removed >= 1
    assert {method.value for method in blanks[0].covered_methods} == {"equivalence", "boundary"}
    # 合并后的用例应在「按覆盖方法」统计中计入两种方法
    assert suite.stats.by_covered_method.get("等价类划分", 0) >= 1
    assert suite.stats.by_covered_method.get("边界值分析", 0) >= 1


# --------------------------------------------------------------------------- #
# 缺陷回归：有效测试数据必须满足字段自身约束
# --------------------------------------------------------------------------- #
async def test_integer_range_representative_is_integral(context) -> None:
    """「查询页码 1~1000」这类数值区间，有效代表值必须是整数（不能是 500.5）。"""
    field = FieldConstraint(name="查询页码", label="查询页码", min_value=1, max_value=1000)
    item = RequirementItem(id="REQ-001", title="订单查询", fields=[field])
    cases = await EquivalenceStrategy(context).generate(item)
    # 只取「非空代表值」：可空字段额外的空值等价类是另一维度，不代表数值区间的有效取值。
    valid = [
        case.test_data["查询页码"]
        for case in cases
        if case.case_type is CaseType.FUNCTIONAL and case.test_data["查询页码"]
    ]
    assert valid == ["500"], valid


async def test_money_representative_respects_pattern(context) -> None:
    """金额字段的有效代表值必须满足自身正则（不能出现 25000.005）。"""
    field = FieldConstraint(
        name="订单金额",
        label="订单金额",
        data_type=DataType.FLOAT,
        min_value=0.01,
        max_value=50000,
        pattern=r"^\d+(\.\d{1,2})?$",
    )
    item = RequirementItem(id="REQ-001", title="下单", fields=[field])
    cases = await EquivalenceStrategy(context).generate(item)
    valid = [
        case.test_data["订单金额"]
        for case in cases
        if case.case_type is CaseType.FUNCTIONAL and case.test_data["订单金额"]
    ]
    assert valid and all(re.fullmatch(field.pattern or "", value) for value in valid), valid


async def test_boundary_valid_data_satisfies_pattern(context) -> None:
    """边界值分析的「边界内」数据必须满足字段正则（手机号不能是 111…）。"""
    field = FieldConstraint(
        name="phone",
        label="手机号",
        data_type=DataType.STRING,
        required=True,
        nullable=False,
        min_length=11,
        max_length=11,
        pattern=r"^1[3-9]\d{9}$",
    )
    item = RequirementItem(id="REQ-001", title="注册", fields=[field])
    cases = await BoundaryStrategy(context).generate(item)
    valid = [
        case.test_data["phone"]
        for case in cases
        if case.case_type in (CaseType.BOUNDARY, CaseType.FUNCTIONAL)
    ]
    assert valid and all(re.fullmatch(field.pattern or "", value) for value in valid), valid


async def test_digit_only_pattern_without_sample_uses_digits(context) -> None:
    """LLM 常给出 ^\\d{11}$ 这类无内置样例的正则，构造出的数据仍必须是数字。"""
    field = FieldConstraint(
        name="phone",
        label="手机号",
        data_type=DataType.STRING,
        required=True,
        nullable=False,
        min_length=11,
        max_length=11,
        pattern=r"^\d{11}$",
    )
    item = RequirementItem(id="REQ-001", title="注册", fields=[field])
    eq_valid = [
        case.test_data["phone"]
        for case in await EquivalenceStrategy(context).generate(item)
        if case.case_type is CaseType.FUNCTIONAL
    ]
    bv_values = [case.test_data.get("phone", "") for case in await BoundaryStrategy(context).generate(item)]
    assert all(value.isdigit() for value in eq_valid), eq_valid
    assert all(value == "" or value.isdigit() for value in bv_values), bv_values


async def test_boolean_field_has_no_space_boundary(context) -> None:
    """布尔字段没有长度概念，不应生成"全空格边界"噪声用例。"""
    field = FieldConstraint(name="记住登录", label="记住登录", data_type=DataType.BOOLEAN)
    item = RequirementItem(id="REQ-001", title="登录", fields=[field])
    cases = await BoundaryStrategy(context).generate(item)
    assert cases == []


# --------------------------------------------------------------------------- #
# 缺陷回归：LLM 增强用例的测试数据必须与字段约束一致
# --------------------------------------------------------------------------- #
def _refund_item() -> RequirementItem:
    return RequirementItem(
        id="REQ-001",
        title="退款申请",
        fields=[FieldConstraint(name="退款原因", label="退款原因", min_length=5, max_length=200)],
    )


def test_llm_valid_case_with_violating_data_is_flagged() -> None:
    """LLM 在正常/边界用例里塞入违反 min_length 的数据时，必须给出可读提示。"""
    issues = describe_test_data_issues(_refund_item(), {"退款原因": "不想要"}, CaseType.BOUNDARY)
    assert issues and "最小长度 5" in issues[0]


def test_llm_exception_case_is_not_flagged() -> None:
    """异常用例本就用越界数据，不应误报。"""
    assert describe_test_data_issues(_refund_item(), {"退款原因": "短"}, CaseType.EXCEPTION) == []


def test_llm_data_is_checked_against_pattern() -> None:
    item = RequirementItem(
        id="REQ-001",
        title="注册",
        fields=[FieldConstraint(name="手机号", label="手机号", pattern=r"^1[3-9]\d{9}$")],
    )
    assert describe_test_data_issues(item, {"手机号": "abc"}, CaseType.FUNCTIONAL)
    assert describe_test_data_issues(item, {"手机号": "13800138000"}, CaseType.FUNCTIONAL) == []


def test_repair_truncates_overlong_valid_data() -> None:
    """正常/边界用例数据超过 max_length 时，应被截断为合法值并给出说明。"""
    item = RequirementItem(
        id="REQ-001",
        title="注册",
        fields=[FieldConstraint(name="邀请码", label="邀请码", max_length=10)],
    )
    repaired, notes = repair_test_data(item, {"邀请码": "ABCDEFGHIJK"}, CaseType.BOUNDARY)
    assert repaired["邀请码"] == "ABCDEFGHIJ"
    assert notes and "最大长度 10" in notes[0]


def test_repair_pads_short_valid_data() -> None:
    """正常用例数据短于 min_length 时，应按字符集补足。"""
    repaired, notes = repair_test_data(_refund_item(), {"退款原因": "不想要"}, CaseType.BOUNDARY)
    assert len(repaired["退款原因"]) == 5
    assert notes and "最小长度 5" in notes[0]


def test_repair_rebuilds_data_violating_pattern() -> None:
    """数据不符合正则时，应替换为匹配该格式的样例值。"""
    item = RequirementItem(
        id="REQ-001",
        title="注册",
        fields=[FieldConstraint(name="手机号", label="手机号", pattern=r"^1[3-9]\d{9}$")],
    )
    repaired, notes = repair_test_data(item, {"手机号": "abc"}, CaseType.FUNCTIONAL)
    assert re.fullmatch(r"^1[3-9]\d{9}$", repaired["手机号"])
    assert notes


def test_repair_leaves_exception_data_untouched() -> None:
    """异常用例的越界数据是设计意图，不得被修正。"""
    repaired, notes = repair_test_data(_refund_item(), {"退款原因": "短"}, CaseType.EXCEPTION)
    assert repaired["退款原因"] == "短"
    assert notes == []
