"""V2.3.2 自动化受控 AI 增强、应用引擎与派生资产回归。"""
from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.core.config import Settings
from app.core.exceptions import BadRequestError, ConflictError
from app.core.utils import new_id, now_iso
from app.llm.fake_provider import FakeProvider
from app.llm.prompts import (
    TASK_AUTOMATION_FAILURE_ASSERTION,
    TASK_AUTOMATION_FIXTURE_RECIPE,
    TASK_AUTOMATION_OPERATION_GAP,
)
from app.repository import Repository
from app.schemas.automation_ai import AutomationAIRequest
from app.schemas.execution import AutomationCreateRequest, CaseResult, TestRun
from app.services.api_service import ApiService
from app.services.automation_ai_service import AutomationAIService
from app.services.execution_service import ExecutionService

API = "/api/v1"
FIXTURE = Path(__file__).parent / "fixtures" / "openapi" / "petstore.yaml"


def _setup(tmp_path: Path):
    settings = Settings(
        storage_dir=tmp_path,
        storage_backend="json",
        llm_provider="fake",
        llm_api_key="",
    )
    settings.ensure_dirs()
    repository = Repository(settings)
    imported = ApiService(settings, repository).import_spec(
        filename="petstore.yaml",
        data=FIXTURE.read_bytes(),
    )
    cases = repository.api_cases.list_recent(
        1000, predicate=lambda item: item.spec_id == imported.spec.spec_id
    )
    positive = next(
        item for item in cases
        if item.operation_id == "listPets" and item.category == "positive"
    )
    artifact = ExecutionService(settings, repository).create_artifact(
        AutomationCreateRequest(
            spec_id=imported.spec.spec_id,
            case_ids=[positive.case_id],
        )
    )
    return settings, repository, imported.spec, positive, artifact


@pytest.mark.asyncio
async def test_operation_gap_and_script_review_are_readonly(tmp_path: Path) -> None:
    settings, repository, spec, positive, artifact = _setup(tmp_path)
    service = AutomationAIService(settings, repository)
    provider = FakeProvider(settings)
    artifact_before = artifact.model_dump(mode="json")
    case_before = positive.model_dump(mode="json")

    gap = await service.create_review(
        AutomationAIRequest(
            kind="operation_gap",
            spec_id=spec.spec_id,
            artifact_id=artifact.artifact_id,
        ),
        provider,
    )
    assert gap.status == "completed"
    assert gap.meta.used is True
    assert gap.findings
    assert all(item.claim_status == "inferred" for item in gap.findings)

    script = await service.create_review(
        AutomationAIRequest(
            kind="script_review",
            spec_id=spec.spec_id,
            artifact_id=artifact.artifact_id,
        ),
        provider,
    )
    assert script.status == "completed"
    assert script.findings
    assert script.findings[0].source_ref == "tests/test_api_cases.py"
    assert repository.automation_artifacts.get(artifact.artifact_id).model_dump(mode="json") == artifact_before
    assert repository.api_cases.get(positive.case_id).model_dump(mode="json") == case_before

    accepted = service.set_finding_disposition(
        gap.review_id,
        gap.findings[0].finding_id,
        "accepted",
    )
    assert accepted.findings[0].disposition == "accepted"
    assert repository.automation_artifacts.get(artifact.artifact_id).model_dump(mode="json") == artifact_before


@pytest.mark.asyncio
async def test_apply_operation_gap_creates_new_case_and_asset_version(tmp_path: Path) -> None:
    settings, repository, spec, positive, artifact = _setup(tmp_path)
    service = AutomationAIService(settings, repository)
    source_before = artifact.model_dump(mode="json")
    source_case_before = positive.model_dump(mode="json")

    review = await service.create_review(
        AutomationAIRequest(
            kind="operation_gap",
            spec_id=spec.spec_id,
            artifact_id=artifact.artifact_id,
        ),
        FakeProvider(settings),
    )
    assert review.findings[0].proposed_case is not None
    service.set_finding_disposition(
        review.review_id,
        review.findings[0].finding_id,
        "accepted",
    )
    derived = service.apply_review(review.review_id)

    assert derived.revision == artifact.revision + 1
    assert derived.parent_artifact_id == artifact.artifact_id
    assert derived.source_review_id == review.review_id
    assert derived.status == "validated"
    assert len(derived.case_ids) == 2
    new_case_ids = [item for item in derived.case_ids if item != positive.case_id]
    assert len(new_case_ids) == 1
    new_case = repository.api_cases.get(new_case_ids[0])
    assert new_case.operation_id == "createPet"
    assert "AI补充" in new_case.tags
    assert repository.automation_artifacts.get(artifact.artifact_id).model_dump(mode="json") == source_before
    assert repository.api_cases.get(positive.case_id).model_dump(mode="json") == source_case_before
    cases_file = next(item for item in derived.files if item.path == "cases.json")
    assert new_case.case_id in cases_file.content
    assert service.get_review(review.review_id).applied_artifact_id == derived.artifact_id
    with pytest.raises(ConflictError, match="已经生成"):
        service.apply_review(review.review_id)


@pytest.mark.asyncio
async def test_cross_operation_source_reference_is_rejected(tmp_path: Path) -> None:
    settings, repository, spec, _positive, artifact = _setup(tmp_path)
    provider = FakeProvider(
        settings,
        scripted={
            TASK_AUTOMATION_OPERATION_GAP: {
                "summary": "越界来源",
                "findings": [
                    {
                        "severity": "warning",
                        "operation_id": "createPet",
                        "target": "request.body",
                        "issue": "越界来源测试",
                        "suggestion": "不应被接受",
                        "rationale": "source_ref 属于另一个 operation",
                        "source_ref": "paths./pets/{petId}.get",
                        "claim_status": "inferred",
                    }
                ],
            }
        },
    )
    review = await AutomationAIService(settings, repository).create_review(
        AutomationAIRequest(
            kind="operation_gap",
            spec_id=spec.spec_id,
            artifact_id=artifact.artifact_id,
        ),
        provider,
    )
    assert review.status == "completed"
    assert review.findings == []
    assert any("丢弃" in warning for warning in review.meta.warnings)


@pytest.mark.asyncio
async def test_failure_assertion_proposal_requires_manual_decision(tmp_path: Path) -> None:
    settings, repository, spec, positive, artifact = _setup(tmp_path)
    source_ref = next(
        (item.source_ref for item in positive.assertions if item.source_ref),
        positive.source_ref,
    )
    run = TestRun(
        run_id=new_id("RUN-"),
        artifact_id=artifact.artifact_id,
        spec_id=spec.spec_id,
        source_file="junit.xml",
        total=1,
        failed=1,
        matched=1,
        cases=[
            CaseResult(
                case_id=positive.case_id,
                name=positive.title,
                status="failed",
                message="expected 200, got 500",
                operation_id=positive.operation_id,
            )
        ],
        created_at=now_iso(),
    )
    repository.test_runs.save(run)
    provider = FakeProvider(
        settings,
        scripted={
            TASK_AUTOMATION_FAILURE_ASSERTION: {
                "summary": "需要确认响应结构断言。",
                "findings": [
                    {
                        "severity": "warning",
                        "case_id": positive.case_id,
                        "operation_id": positive.operation_id,
                        "target": "response error envelope",
                        "issue": "现有断言只覆盖成功状态。",
                        "suggestion": "人工确认后补充错误响应字段断言。",
                        "rationale": "失败消息只有状态码差异。",
                        "source_ref": source_ref,
                        "claim_status": "verified",
                        "proposed_assertion": {
                            "kind": "json",
                            "path": "$.code",
                            "operator": "exists",
                            "expected": True,
                            "description": "错误响应含 code",
                            "source_ref": source_ref,
                        },
                    }
                ],
            }
        },
    )
    service = AutomationAIService(settings, repository)
    review = await service.create_review(
        AutomationAIRequest(
            kind="failure_assertion",
            spec_id=spec.spec_id,
            artifact_id=artifact.artifact_id,
            run_id=run.run_id,
        ),
        provider,
    )
    assert review.status == "completed"
    finding = review.findings[0]
    assert finding.disposition == "pending"
    assert finding.claim_status == "inferred"
    assert finding.proposed_assertion is not None
    assert finding.proposed_assertion.path == "$.code"

    decided = service.set_finding_disposition(review.review_id, finding.finding_id, "rejected")
    assert decided.findings[0].disposition == "rejected"
    assert repository.automation_artifacts.get(artifact.artifact_id).model_dump(mode="json") == artifact.model_dump(mode="json")


@pytest.mark.asyncio
async def test_apply_failure_assertion_to_derived_case_only(tmp_path: Path) -> None:
    settings, repository, spec, positive, artifact = _setup(tmp_path)
    source_ref = next(
        (item.source_ref for item in positive.assertions if item.source_ref),
        positive.source_ref,
    )
    run = TestRun(
        run_id=new_id("RUN-"),
        artifact_id=artifact.artifact_id,
        spec_id=spec.spec_id,
        source_file="junit.xml",
        total=1,
        failed=1,
        matched=1,
        cases=[
            CaseResult(
                case_id=positive.case_id,
                name=positive.title,
                status="failed",
                message="expected 200, got 500",
                operation_id=positive.operation_id,
            )
        ],
    )
    repository.test_runs.save(run)
    service = AutomationAIService(settings, repository)
    provider = FakeProvider(
        settings,
        scripted={
            TASK_AUTOMATION_FAILURE_ASSERTION: {
                "summary": "补充错误码断言",
                "findings": [
                    {
                        "severity": "warning",
                        "case_id": positive.case_id,
                        "operation_id": positive.operation_id,
                        "target": "$.code",
                        "issue": "错误响应缺诊断码断言",
                        "suggestion": "人工确认后补充",
                        "rationale": "失败只显示状态码差异",
                        "source_ref": source_ref,
                        "claim_status": "inferred",
                        "proposed_assertion": {
                            "kind": "json",
                            "path": "$.code",
                            "operator": "exists",
                            "expected": True,
                            "description": "错误响应含错误码",
                            "source_ref": source_ref,
                        },
                    }
                ],
            }
        },
    )
    review = await service.create_review(
        AutomationAIRequest(
            kind="failure_assertion",
            spec_id=spec.spec_id,
            artifact_id=artifact.artifact_id,
            run_id=run.run_id,
        ),
        provider,
    )
    service.set_finding_disposition(
        review.review_id,
        review.findings[0].finding_id,
        "accepted",
    )
    derived = service.apply_review(review.review_id)
    new_case_id = next(item for item in derived.case_ids if item != positive.case_id)
    new_case = repository.api_cases.get(new_case_id)
    assert any(item.path == "$.code" and item.operator == "exists" for item in new_case.assertions)
    assert all(item.path != "$.code" for item in repository.api_cases.get(positive.case_id).assertions)
    assert new_case.case_id != positive.case_id
    assert derived.status == "validated"


@pytest.mark.asyncio
async def test_fixture_recipe_is_structured_and_rejects_plaintext_secret(tmp_path: Path) -> None:
    settings, repository, spec, positive, artifact = _setup(tmp_path)
    service = AutomationAIService(settings, repository)
    recipe = await service.create_review(
        AutomationAIRequest(
            kind="fixture_recipe",
            spec_id=spec.spec_id,
            artifact_id=artifact.artifact_id,
        ),
        FakeProvider(settings),
    )
    assert recipe.status == "completed"
    assert recipe.recipe is not None
    assert recipe.recipe.environment_variables
    assert all(item.placeholder != "sk-test" for item in recipe.recipe.environment_variables)
    content, filename = service.recipe_download(recipe.review_id)
    assert filename.endswith(".json")
    assert b"disclaimer" in content

    leaking = FakeProvider(
        settings,
        scripted={
            TASK_AUTOMATION_FIXTURE_RECIPE: {
                "summary": "泄漏测试",
                "recipe": {
                    "summary": "bad",
                    "environment_variables": [
                        {
                            "name": "AUTH_TOKEN",
                            "description": "bad",
                            "secret": True,
                            "placeholder": "sk-live-plaintext-secret-123456",
                        }
                    ],
                    "fixtures": [],
                    "test_data": [],
                    "preconditions": [],
                    "execution_notes": [],
                    "warnings": [],
                },
            }
        },
    )
    failed = await service.create_review(
        AutomationAIRequest(
            kind="fixture_recipe",
            spec_id=spec.spec_id,
            artifact_id=artifact.artifact_id,
        ),
        leaking,
    )
    assert failed.status == "failed"
    assert failed.recipe is None
    assert any("失败" in item for item in failed.meta.warnings)

    executable = FakeProvider(
        settings,
        scripted={
            TASK_AUTOMATION_FIXTURE_RECIPE: {
                "summary": "可执行代码测试",
                "recipe": {
                    "summary": "bad",
                    "environment_variables": [],
                    "fixtures": [
                        {
                            "name": "bad_fixture",
                            "purpose": "bad",
                            "setup": ["eval('1 + 1')"],
                            "data": {},
                        }
                    ],
                    "test_data": [],
                    "preconditions": [],
                    "execution_notes": [],
                    "warnings": [],
                },
            }
        },
    )
    unsafe = await service.create_review(
        AutomationAIRequest(
            kind="fixture_recipe",
            spec_id=spec.spec_id,
            artifact_id=artifact.artifact_id,
        ),
        executable,
    )
    assert unsafe.status == "failed"
    assert unsafe.recipe is None

    artifact.status = "rejected"
    repository.automation_artifacts.save(artifact)
    with pytest.raises(BadRequestError, match="安全校验"):
        await service.create_review(
            AutomationAIRequest(
                kind="script_review",
                spec_id=spec.spec_id,
                artifact_id=artifact.artifact_id,
            ),
            FakeProvider(settings),
        )


@pytest.mark.asyncio
async def test_apply_recipe_generates_fixture_files_and_keeps_source_unchanged(tmp_path: Path) -> None:
    settings, repository, spec, _positive, artifact = _setup(tmp_path)
    service = AutomationAIService(settings, repository)
    source_files = {item.path: item.content for item in artifact.files}
    review = await service.create_review(
        AutomationAIRequest(
            kind="fixture_recipe",
            spec_id=spec.spec_id,
            artifact_id=artifact.artifact_id,
        ),
        FakeProvider(settings),
    )
    service.set_review_decision(review.review_id, "accepted")
    derived = service.apply_review(review.review_id)
    files = {item.path: item.content for item in derived.files}
    assert derived.status == "validated"
    assert derived.parent_artifact_id == artifact.artifact_id
    assert "fixtures.json" in files
    assert "test_data.json" in files
    assert "AUTH_TOKEN=" in files[".env.example"]
    assert "BASE_URL=" in files[".env.example"]
    assert json.loads(files["fixtures.json"])["fixtures"]
    assert json.loads(files["test_data.json"])["test_data"]
    assert "fixtures.json" not in source_files
    assert repository.automation_artifacts.get(artifact.artifact_id).model_dump(mode="json") == artifact.model_dump(mode="json")
    content, filename = ExecutionService(settings, repository).artifact_download(derived.artifact_id)
    assert filename.endswith(".zip")
    with ZipFile(BytesIO(content)) as archive:
        assert "fixtures.json" in archive.namelist()
        assert "test_data.json" in archive.namelist()


def test_automation_ai_routes_and_recipe_download(client) -> None:
    imported = client.post(
        f"{API}/api-specs/import",
        files={"file": ("petstore.yaml", FIXTURE.read_bytes(), "application/yaml")},
    ).json()["data"]
    spec = imported["spec"]
    positive = next(
        item for item in imported["cases"]
        if item["operation_id"] == "listPets" and item["category"] == "positive"
    )
    artifact = client.post(
        f"{API}/automation/artifacts",
        json={"spec_id": spec["spec_id"], "case_ids": [positive["case_id"]]},
    ).json()["data"]

    gap = client.post(
        f"{API}/automation/ai/reviews",
        json={
            "kind": "operation_gap",
            "spec_id": spec["spec_id"],
            "artifact_id": artifact["artifact_id"],
        },
    )
    assert gap.status_code == 200, gap.text
    gap_data = gap.json()["data"]
    assert gap_data["status"] == "completed"
    finding_id = gap_data["findings"][0]["finding_id"]
    decided = client.put(
        f"{API}/automation/ai/reviews/{gap_data['review_id']}/findings/{finding_id}",
        json={"disposition": "accepted"},
    )
    assert decided.status_code == 200
    assert decided.json()["data"]["findings"][0]["disposition"] == "accepted"
    applied = client.post(
        f"{API}/automation/ai/reviews/{gap_data['review_id']}/apply"
    )
    assert applied.status_code == 200, applied.text
    derived = applied.json()["data"]
    assert derived["parent_artifact_id"] == artifact["artifact_id"]
    assert derived["revision"] == artifact["revision"] + 1
    assert derived["status"] == "validated"

    fixture = client.post(
        f"{API}/automation/ai/reviews",
        json={
            "kind": "fixture_recipe",
            "spec_id": spec["spec_id"],
            "artifact_id": artifact["artifact_id"],
        },
    )
    assert fixture.status_code == 200, fixture.text
    fixture_data = fixture.json()["data"]
    assert fixture_data["recipe"]
    recipe_file = client.get(
        f"{API}/automation/ai/reviews/{fixture_data['review_id']}/recipe"
    )
    assert recipe_file.status_code == 200
    assert recipe_file.headers["content-type"].startswith("application/json")
    assert b"AI" in recipe_file.content

    listed = client.get(
        f"{API}/automation/ai/reviews",
        params={"artifact_id": artifact["artifact_id"]},
    ).json()["data"]
    assert len(listed) >= 2
