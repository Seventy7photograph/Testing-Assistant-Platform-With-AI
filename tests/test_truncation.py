"""单条需求用例上限的口径回归。

两个曾经出错的地方：
  1. 截断按「先到先得」，排在后面的方法（判定表 / 因果图 / 正交实验）会被饿死；
  2. 告警说「已截断到 60」，界面却只显示 48 条 —— 因为截断发生在去重之前，
     两个口径混在一句话里自相矛盾。
"""
from __future__ import annotations

import pytest

from app.design.base import DesignContext
from app.design.engine import DesignEngine, fair_share_trim
from app.llm.null_provider import NullProvider
from app.schemas.common import CaseType, DesignMethod, Priority
from app.schemas.requirement import FieldConstraint, RequirementDoc, RequirementItem
from app.schemas.testcase import TestCase

ALL_METHODS = ["equivalence", "boundary", "scenario", "decision_table", "cause_effect", "orthogonal"]


def make_case(method: DesignMethod, index: int) -> TestCase:
    return TestCase(
        title=f"{method.value}-{index}",
        design_method=method,
        case_type=CaseType.FUNCTIONAL,
        priority=Priority.P2,
        requirement_ids=["REQ-001"],
        test_data={f"f{index}": str(index)},
    )


def wide_item() -> RequirementItem:
    """字段足够多，保证六种方法都能产出足量用例。"""
    return RequirementItem(
        id="REQ-001",
        title="大表单",
        fields=[
            FieldConstraint(name=f"f{i}", label=f"字段{i}", min_value=0, max_value=100) for i in range(6)
        ]
        + [
            FieldConstraint(name="状态", label="状态", enum_values=["A", "B", "C"]),
            FieldConstraint(name="渠道", label="渠道", enum_values=["X", "Y", "Z"]),
        ],
        business_rules=["若 f0 不合法则拒绝提交", "不允许 f1 为空"],
        main_flow=["进入页面", "填写", "提交"],
        alternative_flows=["数据已存在时提示"],
        exceptions=["接口超时"],
    )


class TestFairShareTrim:
    def test_every_method_survives_the_cut(self) -> None:
        cases = [make_case(method, index) for method in DesignMethod for index in range(20)]
        kept, totals, kept_counts = fair_share_trim(cases, 12)
        assert len(kept) == 12
        # 六种方法各留 2 条：没有任何一种被整体饿死。
        assert set(kept_counts.values()) == {2}
        assert set(totals.values()) == {20}
        assert {case.design_method for case in kept} == set(DesignMethod)

    def test_preserves_original_order(self) -> None:
        cases = [make_case(method, index) for method in DesignMethod for index in range(4)]
        kept, _, _ = fair_share_trim(cases, 6)
        assert kept == [case for case in cases if case in kept]

    def test_no_trim_when_within_limit(self) -> None:
        cases = [make_case(DesignMethod.EQUIVALENCE, index) for index in range(3)]
        kept, _, _ = fair_share_trim(cases, 10)
        assert len(kept) == 3


class TestEngineTruncation:
    async def test_cap_keeps_all_methods_and_reports_both_counts(self, settings) -> None:
        doc = RequirementDoc(doc_id="DOC-1", title="大表单需求", items=[wide_item()])
        suite = await DesignEngine(settings).generate(
            doc, ALL_METHODS, llm=NullProvider(settings), use_llm=False, max_cases_per_item=24
        )
        assert suite.stats.total <= 24
        # 六种方法都要在结果里出现，而不是只有排在前面的那几种。
        assert {case.design_method.value for case in suite.cases} == set(ALL_METHODS)
        truncation = [w for w in suite.generation_meta.warnings if "按方法轮转保留" in w]
        assert len(truncation) == 1
        assert "去重合并后本需求" in truncation[0]

    async def test_no_warning_when_under_the_cap(self, settings) -> None:
        doc = RequirementDoc(doc_id="DOC-1", title="小需求", items=[wide_item()])
        suite = await DesignEngine(settings).generate(
            doc, ["equivalence"], llm=NullProvider(settings), use_llm=False, max_cases_per_item=500
        )
        assert not [w for w in suite.generation_meta.warnings if "超过单条需求上限" in w]

    async def test_default_cap_is_a_safety_net_not_a_daily_limit(self, settings) -> None:
        """默认上限必须高于正常需求的自然产出，否则护栏会天天误报。"""
        assert settings.max_cases_per_requirement >= 120
        doc = RequirementDoc(doc_id="DOC-1", title="大表单需求", items=[wide_item()])
        suite = await DesignEngine(settings).generate(
            doc, ALL_METHODS, llm=NullProvider(settings), use_llm=False
        )
        assert not [w for w in suite.generation_meta.warnings if "超过单条需求上限" in w]


class TestEquivalenceWithOldBehaviour:
    def test_sequential_trim_would_starve_later_methods(self) -> None:
        """反证：按顺序取前 N 条时，最后一种方法的用例会被整体丢掉。"""
        cases = [make_case(method, index) for method in DesignMethod for index in range(20)]
        naive = cases[:12]
        assert len({case.design_method for case in naive}) < len(DesignMethod)
        fair, _, _ = fair_share_trim(cases, 12)
        assert len({case.design_method for case in fair}) == len(DesignMethod)


class TestRequestOverride:
    def test_api_accepts_cap_and_applies_it(self, client) -> None:
        text = "\n".join(
            f"## 模块{i}\n手机号：11位数字，必填\n年龄：18~120\n状态：待支付/已支付/已取消\n" for i in range(1, 3)
        )
        response = client.post(
            "/api/v1/testcases/generate",
            json={
                "text": text,
                "methods": ["equivalence", "boundary"],
                "use_llm": False,
                "max_cases_per_requirement": 12,
            },
        )
        assert response.status_code == 200, response.text
        suite = response.json()["data"]
        assert suite["stats"]["total"] <= 24
        per_requirement = set(suite["stats"]["requirement_coverage"].values())
        assert per_requirement and max(per_requirement) <= 12, per_requirement

    def test_api_rejects_absurd_cap(self, client) -> None:
        response = client.post(
            "/api/v1/testcases/generate",
            json={"text": "# 模块\n年龄：18~120\n", "methods": ["boundary"], "max_cases_per_requirement": 99999},
        )
        assert response.status_code == 422

    def test_health_exposes_effective_limits(self, client) -> None:
        limits = client.get("/api/v1/health").json()["data"]["limits"]
        assert limits.get("max_cases_per_requirement", 0) >= 120


def test_context_records_truncation_without_warning_early() -> None:
    """引擎先记事实、去重后再报警：告警里必须能写出去重后的真实条数。"""
    context = DesignContext(settings=None, llm=None)  # type: ignore[arg-type]
    assert context.truncations == []
    assert context.warnings == []
