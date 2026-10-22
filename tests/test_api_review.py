"""V2.2：接口用例的大模型只读复核回归。"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.exceptions import ConflictError
from app.design.api_cases import generate_api_cases
from app.design.api_review import review_api_cases
from app.llm.fake_provider import FakeProvider
from app.llm.prompt_registry import PROMPT_API_CASE_REVIEW
from app.llm.prompts import TASK_API_CASE_REVIEW
from app.parsers.openapi_parser import parse_openapi
from app.repository import Repository
from app.schemas.api_testing import ApiReviewMeta, ApiReviewResult
from app.services.api_service import ApiService

FIXTURE = Path(__file__).parent / "fixtures" / "openapi" / "petstore.yaml"


def petstore_spec():
    return parse_openapi(
        FIXTURE.read_bytes(),
        filename="petstore.yaml",
        spec_id="API-review-test",
    )


@pytest.mark.asyncio
async def test_review_is_optional_and_never_rewrites_generated_cases(settings) -> None:
    spec = petstore_spec()
    generated = generate_api_cases(spec)
    before = [case.model_dump(mode="json") for case in generated.cases]
    provider = FakeProvider(
        settings,
        scripted={
            TASK_API_CASE_REVIEW: {
                "findings": [
                    {
                        "severity": "warning",
                        "kind": "case_gap",
                        "operation_id": "createPet",
                        "target": "request.body.status",
                        "issue": "规范允许的状态迁移需要人工确认。",
                        "suggestion": "补充重复创建与状态变化场景。",
                        "source_ref": "paths./pets.post",
                        "claim_status": "verified",
                        "uncertainty_reason": "OpenAPI 未声明业务状态机。",
                    },
                    {
                        "severity": "warning",
                        "operation_id": "not-in-spec",
                        "issue": "悬空意见",
                        "source_ref": "paths./missing.post",
                    },
                ]
            }
        },
    )

    review = await review_api_cases(spec, generated.cases, provider)

    assert review.meta.used is True
    assert review.meta.status == "completed"
    assert review.meta.llm_calls == 1
    assert review.meta.provider == "fake"
    assert review.meta.prompt_id == PROMPT_API_CASE_REVIEW.prompt_id
    assert len(review.findings) == 1
    assert review.findings[0].claim_status == "inferred", "模型意见不能自行标成已验证事实"
    assert any("悬空" in item for item in review.meta.warnings)
    assert [case.model_dump(mode="json") for case in generated.cases] == before


@pytest.mark.asyncio
async def test_review_prompt_has_strict_readonly_boundary(settings) -> None:
    spec = petstore_spec()
    cases = generate_api_cases(spec).cases
    provider = FakeProvider(settings)
    await review_api_cases(spec, cases, provider)
    prompt = "\n".join(str(message.content) for message in provider.calls[0])
    assert TASK_API_CASE_REVIEW in prompt
    assert "不得改写接口路径" in prompt
    assert "不要输出可直接执行的新用例" in prompt
    assert "allowed_source_refs" in prompt


@pytest.mark.asyncio
async def test_running_review_is_persisted_and_duplicate_calls_are_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        storage_dir=tmp_path,
        storage_backend="json",
        llm_provider="none",
        llm_api_key="",
    )
    settings.ensure_dirs()
    service = ApiService(settings, Repository(settings))
    imported = service.import_spec(filename="petstore.yaml", data=FIXTURE.read_bytes())
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_review(spec, cases, llm):  # noqa: ANN001, ARG001
        started.set()
        await release.wait()
        return ApiReviewResult(
            spec_id=spec.spec_id,
            meta=ApiReviewMeta(used=True, status="completed", provider=llm.name),
        )

    monkeypatch.setattr("app.services.api_service.review_api_cases", fake_review)
    provider = FakeProvider(settings)
    task = asyncio.create_task(service.review_spec(imported.spec.spec_id, provider))
    await asyncio.wait_for(started.wait(), timeout=2)

    persisted = Repository(settings).api_specs.get(imported.spec.spec_id)
    assert persisted.ai_review is not None
    assert persisted.ai_review.meta.status == "running"
    with pytest.raises(ConflictError, match="正在执行"):
        await service.review_spec(imported.spec.spec_id, provider)

    release.set()
    result = await asyncio.wait_for(task, timeout=2)
    assert result.meta.status == "completed"
    assert service.get_spec(imported.spec.spec_id).ai_review.meta.status == "completed"
