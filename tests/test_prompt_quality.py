"""V2.1 fixed adversarial Prompt regression set.

The suite is deterministic and uses FakeProvider or local scripted providers.
It measures unsupported fields, dangling findings, JSON success, call counts and
elapsed time without spending model quota.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.core.exceptions import LLMResponseFormatError
from app.design.base import DesignContext
from app.design.engine import DesignEngine
from app.design.enrichment import review_item
from app.design.optimizer import optimize
from app.design.scenario import ScenarioStrategy
from app.llm.base import LLMProvider, LLMResponse, system
from app.llm.fake_provider import FakeProvider
from app.llm.prompt_registry import ALL_PROMPTS
from app.llm.prompts import TASK_GENERATION_REVIEW, TASK_SCENARIO_ENRICHMENT
from app.schemas.common import DesignMethod, Priority
from app.schemas.requirement import RequirementItem
from app.schemas.testcase import TestCase
from app.services import requirement_service
from app.services.evidence import detect_prompt_injection, gate_requirement_payload
from app.services.requirement_service import RequirementService, _LLMField

FIXTURE = Path(__file__).parent / "fixtures" / "prompts" / "cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))


class _RawProvider(LLMProvider):
    """Provider that returns a fixed raw string and counts calls."""

    name = "raw"

    def __init__(self, raw: str) -> None:
        super().__init__()
        self.raw = raw
        self.calls = 0

    @property
    def available(self) -> bool:
        return True

    async def complete(self, messages, **kwargs) -> LLMResponse:  # type: ignore[override]
        self.calls += 1
        return LLMResponse(content=self.raw, model="raw-model", finish_reason="stop")


def _item(source: str = "手机号：必填", *, priority: Priority = Priority.P1) -> RequirementItem:
    return RequirementItem(
        id="REQ-001",
        title="手机号",
        raw_text=source,
        priority=priority,
        fields=[],
    )


def test_fixture_count_and_prompt_registry() -> None:
    assert len(CASES) >= 20
    assert len({case["id"] for case in CASES}) == len(CASES)
    assert {spec.prompt_id for spec in ALL_PROMPTS} == {
        "requirement.extract",
        "design.scenario_enrichment",
        "design.generation_review",
        "report.summarize",
        "api.case_review",
        "automation.operation_gap",
        "automation.failure_assertion",
        "automation.fixture_recipe",
        "automation.script_review",
    }
    assert all(spec.version in {"2.1.0", "2.2.0", "2.3.1", "2.3.2"} for spec in ALL_PROMPTS)


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
async def test_fixed_adversarial_case(case: dict, settings) -> None:
    started = time.perf_counter()
    kind = case["kind"]
    expect = case["expect"]

    if kind in {"injection"}:
        warnings = detect_prompt_injection(case["source"])
        assert bool(warnings) is expect["injected"]
        assert len(warnings) >= expect.get("injection_min", 0)
        return

    if kind == "field_normalize":
        field = RequirementService._to_field(_LLMField(**case["payload"]), [])
        assert field.pattern is expect["pattern"]
        assert field.min_length == expect["min_length"]
        assert field.max_length == expect["max_length"]
        return

    if kind == "invalid_json":
        provider = _RawProvider(case["payload"]["raw"])
        with pytest.raises(LLMResponseFormatError):
            await provider.complete_json([system("输出 JSON")], retries=0)
        assert provider.calls == 1
        return

    if kind == "duplicate":
        duplicate = [
            TestCase(title=title, design_method=DesignMethod.EQUIVALENCE)
            for title in case["payload"]["titles"]
        ]
        kept, removed = optimize(duplicate)
        assert len(kept) == 1
        assert removed == expect["duplicate_removed"]
        return

    if kind == "review":
        scripted = {TASK_GENERATION_REVIEW: case["payload"]}
        provider = FakeProvider(settings, scripted=scripted)
        context = DesignContext(
            settings=settings,
            llm=provider,
            use_llm=True,
            llm_review_mode="review",
            max_llm_calls=5,
        )
        extra, findings = await review_item(
            _item(case["source"]),
            [TestCase(title="手机号有效", design_method=DesignMethod.EQUIVALENCE)],
            context=context,
            methods=[DesignMethod.EQUIVALENCE],
            allow_cases=False,
        )
        assert not extra
        assert len([item for item in findings if item.claim_status.value == "verified"]) == expect[
            "verified_findings"
        ]
        assert len([item for item in findings if item.claim_status.value == "inferred"]) == expect[
            "inferred_findings"
        ]
        assert len(provider.calls) <= 2
        return

    if kind == "scenario":
        provider = FakeProvider(settings, scripted={TASK_SCENARIO_ENRICHMENT: case["payload"]})
        context = DesignContext(
            settings=settings,
            llm=provider,
            use_llm=True,
            llm_review_mode="scenario",
            max_cases_per_item=20,
        )
        cases = await ScenarioStrategy(context).generate(_item(case["source"]))
        llm_cases = [entry for entry in cases if entry.title.startswith("[场景-LLM]")]
        assert len(llm_cases) == expect["llm_cases"]
        assert len([entry for entry in llm_cases if entry.claim_status.value == "inferred"]) == expect[
            "inferred_cases"
        ]
        return

    if kind == "merge":
        payload = case["payload"]
        llm_item = RequirementItem(
            id="REQ-LLM",
            title=payload["llm_title"],
            module="订单",
            source_ref=payload["llm_anchor"],
        )
        rule_item = RequirementItem(
            id="REQ-RULE",
            title=payload["rule_title"],
            module="订单",
            source_ref=payload["rule_anchor"],
        )
        rule_item.fields = [
            requirement_service.RequirementService._to_field(
                requirement_service._LLMField(name="订单号", label="订单号"), []
            )
        ]
        RequirementService._merge_rule_fields([llm_item], [rule_item])
        assert bool(llm_item.fields) is expect["merged"]
        return

    if kind == "budget":
        items = [
            RequirementItem(id=f"REQ-{index}", title=f"需求 {index}", priority=Priority(priority))
            for index, priority in enumerate(case["payload"]["priorities"])
        ]
        provider = FakeProvider(settings)
        settings.llm_max_calls_per_generation = case["payload"]["budget"]
        suite = await DesignEngine(settings).generate(
            requirement_service.RequirementDoc(doc_id="DOC-1", title="预算", items=items),
            ["equivalence"],
            llm=provider,
            use_llm=True,
            llm_design_mode="review",
        )
        assert suite.generation_meta.llm_calls == case["payload"]["budget"]
        assert len(suite.generation_meta.unreviewed_requirements) == len(expect["unreviewed"])
        assert expect["unreviewed"][0] in suite.generation_meta.unreviewed_requirements[0]
        return

    if kind == "requirement":
        gate = gate_requirement_payload(case["payload"], case["source"])
        counts = gate.counts
        assert bool(gate.injection_warnings) is expect["injected"]
        if "verified_min" in expect:
            assert counts["verified"] >= expect["verified_min"]
        if "verified_max" in expect:
            assert counts["verified"] <= expect["verified_max"]
        if "inferred_min" in expect:
            assert counts["inferred"] >= expect["inferred_min"]
        if "rejected_min" in expect:
            assert counts["rejected"] >= expect["rejected_min"]
        if "rejected_max" in expect:
            assert counts["rejected"] <= expect["rejected_max"]
        if not expect.get("critical", False):
            assert not gate.critical_errors or counts["verified"] > 0
        return

    raise AssertionError(f"未处理的回归样本类型：{kind}")


def test_regression_suite_is_fast_enough() -> None:
    started = time.perf_counter()
    for case in CASES:
        if case["kind"] == "requirement":
            gate_requirement_payload(case["payload"], case["source"])
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert elapsed_ms < 500


def test_prompt_registry_endpoint(client) -> None:
    response = client.get("/api/v1/llm/prompts")
    assert response.status_code == 200
    items = response.json()["data"]
    assert {item["prompt_id"] for item in items} == {
        "requirement.extract",
        "design.scenario_enrichment",
        "design.generation_review",
        "report.summarize",
        "api.case_review",
        "automation.operation_gap",
        "automation.failure_assertion",
        "automation.fixture_recipe",
        "automation.script_review",
    }
    assert all(item["version"] in {"2.1.0", "2.2.0", "2.3.1", "2.3.2"} for item in items)
