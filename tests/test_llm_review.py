"""生成阶段的大模型参与方式（scenario / review / enhance）回归。

核心原则要守住：**模型不重写规则产出**。规则用例必须逐条原样保留，
模型只能"提意见"或"追加带来源标记的补充用例"。
"""
from __future__ import annotations

import pytest

from app.core.exceptions import LLMError
from app.design.base import DEFAULT_LLM_DESIGN_MODE, LLM_DESIGN_MODES
from app.design.engine import DesignEngine, normalize_llm_design_mode
from app.design.enrichment import TITLE_PREFIX, sanitize_test_data
from app.llm.fake_provider import FakeProvider
from app.llm.null_provider import NullProvider
from app.llm.prompts import TASK_GENERATION_REVIEW
from app.schemas.common import CaseType, DataType, DesignMethod, Priority
from app.schemas.requirement import FieldConstraint, RequirementDoc, RequirementItem

METHODS = ["equivalence", "boundary", "decision_table"]


def registration_item() -> RequirementItem:
    return RequirementItem(
        id="REQ-001",
        title="用户注册",
        module="用户中心",
        priority=Priority.P1,
        fields=[
            FieldConstraint(name="phone", label="手机号", data_type=DataType.STRING, required=True),
            FieldConstraint(name="age", label="年龄", data_type=DataType.INTEGER, min_value=18, max_value=120),
        ],
        business_rules=["同一手机号不可重复注册"],
        main_flow=["进入注册页", "提交注册"],
    )


def make_doc(items: list[RequirementItem] | None = None) -> RequirementDoc:
    return RequirementDoc(doc_id="DOC-1", title="注册需求", items=items or [registration_item()])


async def generate(settings, *, mode: str = DEFAULT_LLM_DESIGN_MODE, llm=None, doc=None, use_llm=True):
    provider = llm if llm is not None else FakeProvider(settings)
    return await DesignEngine(settings).generate(
        doc or make_doc(),
        METHODS,
        llm=provider,
        use_llm=use_llm,
        llm_design_mode=mode,
    )


class TestModeNormalisation:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("review", "review"),
            ("ENHANCE", "enhance"),
            ("scenario", "scenario"),
            ("", "scenario"),
            ("magic", "scenario"),
            (None, "scenario"),
        ],
    )
    def test_unknown_mode_falls_back(self, raw, expected) -> None:
        assert normalize_llm_design_mode(raw) == expected

    def test_default_mode_keeps_v1_behaviour(self) -> None:
        assert DEFAULT_LLM_DESIGN_MODE == "scenario"
        assert set(LLM_DESIGN_MODES) == {"scenario", "review", "enhance"}


class TestOffAndScenario:
    async def test_off_mode_makes_no_calls(self, settings) -> None:
        provider = FakeProvider(settings)
        suite = await generate(settings, llm=provider, use_llm=False)
        assert provider.calls == []
        assert suite.generation_meta.llm_calls == 0
        assert suite.generation_meta.llm_used is False
        assert suite.generation_meta.review_findings == []

    async def test_scenario_mode_keeps_old_behaviour(self, settings) -> None:
        """默认模式必须与 V1.0 完全一致：只由场景法补充用例，不走统一复核。"""
        provider = FakeProvider(settings)
        suite = await generate(settings, mode="scenario", llm=provider)
        prompts = "\n".join(str(message.content) for call in provider.calls for message in call)
        assert TASK_GENERATION_REVIEW not in prompts
        assert suite.generation_meta.review_findings == []
        assert suite.generation_meta.llm_calls == 0


class TestReviewMode:
    async def test_review_gives_findings_without_touching_rule_cases(self, settings) -> None:
        rule_only = await generate(settings, llm=NullProvider(settings), use_llm=False)
        provider = FakeProvider(settings)
        reviewed = await generate(settings, mode="review", llm=provider)

        assert reviewed.generation_meta.review_findings, "复核模式必须产出意见"
        assert reviewed.generation_meta.llm_used is True
        assert reviewed.generation_meta.llm_calls >= 1
        # 规则用例逐条原样保留：复核只提意见，不改写、不追加。
        assert [case.title for case in reviewed.cases] == [case.title for case in rule_only.cases]
        assert not [case for case in reviewed.cases if case.title.startswith(TITLE_PREFIX)]

    async def test_one_call_per_requirement_not_per_method(self, settings) -> None:
        """成本口径：一次生成按「需求条数」计费，而不是按方法数。"""
        doc = make_doc([registration_item(), registration_item(), registration_item()])
        provider = FakeProvider(settings)
        suite = await generate(settings, mode="review", llm=provider, doc=doc)
        assert len(provider.calls) == 3, f"3 条需求应只调用 3 次，实际 {len(provider.calls)}"
        assert suite.generation_meta.llm_calls == 3

    async def test_review_asks_for_findings_only(self, settings) -> None:
        provider = FakeProvider(settings)
        await generate(settings, mode="review", llm=provider)
        prompt = str(provider.calls[0][0].content)
        assert "不需要补充用例" in prompt

    async def test_budget_caps_calls(self, settings) -> None:
        doc = make_doc([registration_item() for _ in range(4)])
        provider = FakeProvider(settings)
        engine = DesignEngine(settings)
        context_doc = doc
        suite = await engine.generate(
            context_doc, METHODS, llm=provider, use_llm=True, llm_design_mode="review"
        )
        assert suite.generation_meta.llm_calls == 4  # 默认预算 20 > 4，不受限

        # 把预算压到 2：只复核前两条，并如实告警。
        engine.settings.llm_max_calls_per_generation = 2
        try:
            provider2 = FakeProvider(settings)
            limited = await engine.generate(
                doc, METHODS, llm=provider2, use_llm=True, llm_design_mode="review"
            )
        finally:
            engine.settings.llm_max_calls_per_generation = 20
        assert len(provider2.calls) == 2
        assert any("调用上限" in warning for warning in limited.generation_meta.warnings)


class TestEnhanceMode:
    async def test_enhance_appends_marked_cases(self, settings) -> None:
        provider = FakeProvider(settings)
        suite = await generate(settings, mode="enhance", llm=provider)
        extra = [case for case in suite.cases if case.title.startswith(TITLE_PREFIX)]
        assert extra, "enhance 模式应补充用例"
        for case in extra:
            assert case.source.value == "llm"
            assert "LLM补充" in case.tags and "需复核" in case.tags
            assert case.requirement_ids == ["REQ-001"]
            assert case.remarks.startswith("大模型在复核")
        # 补充用例必须挂到模型指定的方法上，而不是一律塞进场景法。
        assert {case.design_method.value for case in extra} & {"cause_effect", "scenario"}

    async def test_enhance_keeps_rule_cases_intact(self, settings) -> None:
        rule_only = await generate(settings, llm=NullProvider(settings), use_llm=False)
        enhanced = await generate(settings, mode="enhance", llm=FakeProvider(settings))
        rule_titles = {case.title for case in rule_only.cases}
        assert rule_titles <= {case.title for case in enhanced.cases}
        assert enhanced.stats.total > rule_only.stats.total

    async def test_enhance_respects_case_cap(self, settings) -> None:
        engine = DesignEngine(settings)
        provider = FakeProvider(settings)
        suite = await engine.generate(
            make_doc(), METHODS, llm=provider, use_llm=True, llm_design_mode="enhance"
        )
        extra = [case for case in suite.cases if case.title.startswith(TITLE_PREFIX)]
        assert len(extra) <= 5


class TestGuards:
    def test_unknown_fields_are_dropped(self) -> None:
        kept, dropped = sanitize_test_data(registration_item(), {"phone": "13800000000", "user_id": "42"})
        assert kept == {"phone": "13800000000"}
        assert dropped == ["user_id"]

    async def test_made_up_field_is_dropped_with_warning(self, settings) -> None:
        scripted = {
            TASK_GENERATION_REVIEW: {
                "findings": [],
                "cases": [
                    {
                        "title": "编造字段的用例",
                        "method": "equivalence",
                        "case_type": "功能",
                        "test_data": {"user_id": "42", "phone": "13800000000"},
                    }
                ],
            }
        }
        suite = await generate(settings, mode="enhance", llm=FakeProvider(settings, scripted=scripted))
        extra = [case for case in suite.cases if case.title.startswith(TITLE_PREFIX)]
        assert extra and "user_id" not in extra[0].test_data
        assert any("需求里没有的字段" in warning for warning in suite.generation_meta.warnings)

    async def test_valid_case_data_is_repaired_to_constraints(self, settings) -> None:
        """正常/边界用例的数据必须满足字段约束，否则会产生"断言成功、实际被拒"的假用例。"""
        scripted = {
            TASK_GENERATION_REVIEW: {
                "findings": [],
                "cases": [
                    {
                        "title": "年龄越界的正常用例",
                        "method": "equivalence",
                        "case_type": "功能",
                        "test_data": {"age": "999"},
                    }
                ],
            }
        }
        suite = await generate(settings, mode="enhance", llm=FakeProvider(settings, scripted=scripted))
        extra = [case for case in suite.cases if case.title.startswith(TITLE_PREFIX)]
        assert extra, suite.generation_meta.warnings
        # 999 越界且用例类型是「功能」→ 应被纠正回合法值（或至少不再越界）。
        assert extra[0].test_data.get("age") in {"", "18", "69", "120"} or not extra[0].test_data

    async def test_llm_failure_degrades_quietly(self, settings) -> None:
        class BrokenProvider(FakeProvider):
            async def complete(self, *args, **kwargs):  # type: ignore[override]
                raise LLMError("模拟网络故障")

        rule_only = await generate(settings, llm=NullProvider(settings), use_llm=False)
        suite = await generate(settings, mode="enhance", llm=BrokenProvider(settings))
        assert [case.title for case in suite.cases] == [case.title for case in rule_only.cases]
        assert any("大模型复核失败" in warning for warning in suite.generation_meta.warnings)
        assert suite.generation_meta.review_findings == []

    async def test_empty_findings_do_not_add_noise(self, settings) -> None:
        scripted = {TASK_GENERATION_REVIEW: {"findings": [], "cases": []}}
        suite = await generate(settings, mode="review", llm=FakeProvider(settings, scripted=scripted))
        assert suite.generation_meta.review_findings == []
        assert suite.generation_meta.llm_calls == 1
        assert not [w for w in suite.generation_meta.warnings if "复核共给出" in w]


class TestApi:
    def test_review_mode_via_http(self, client) -> None:
        response = client.post(
            "/api/v1/testcases/generate",
            json={
                "text": "# 注册\n## 用户注册\n手机号：11位数字，必填\n年龄：18~120\n",
                "methods": ["equivalence", "boundary"],
                "use_llm": False,
                "use_llm_in_design": True,
                "llm_design_mode": "review",
            },
        )
        assert response.status_code == 200, response.text
        meta = response.json()["data"]["generation_meta"]
        assert meta["review_findings"], "HTTP 链路也要能拿到复核意见"
        assert meta["llm_calls"] >= 1
        assert meta["llm_provider"] == "fake"

    def test_unknown_mode_falls_back_not_500(self, client) -> None:
        response = client.post(
            "/api/v1/testcases/generate",
            json={
                "text": "# 注册\n## 用户注册\n年龄：18~120\n",
                "methods": ["boundary"],
                "use_llm": False,
                "use_llm_in_design": True,
                "llm_design_mode": "aggressive",
            },
        )
        assert response.status_code == 200
        assert response.json()["data"]["generation_meta"]["review_findings"] == []


def test_case_type_mapping_is_shared_with_scenario() -> None:
    """功能/边界/异常/场景 的映射与场景法共用一套，避免两处口径漂移。"""
    from app.design.scenario import to_case_type

    assert to_case_type("异常") is CaseType.EXCEPTION
    assert to_case_type("边界") is CaseType.BOUNDARY
    assert to_case_type("功能") is CaseType.FUNCTIONAL
