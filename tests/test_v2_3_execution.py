"""V2.3 自动化资产、JUnit 回收与 API 闭环回归。"""
from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from app.automation.validators import validate_generated_files
from app.core.config import Settings
from app.execution.junit_parser import JUnitParseError, parse_junit_xml
from app.repository import Repository
from app.schemas.execution import AutomationCreateRequest, GeneratedFile
from app.services.api_service import ApiService
from app.services.execution_service import ExecutionService

API = "/api/v1"
FIXTURES = Path(__file__).parent / "fixtures" / "openapi"


def petstore_bytes() -> bytes:
    return (FIXTURES / "petstore.yaml").read_bytes()


class TestArtifactGeneration:
    def test_petstore_artifact_is_versioned_validated_and_downloadable(self) -> None:
        with TemporaryDirectory() as directory:
            settings = Settings(
                storage_dir=Path(directory),
                storage_backend="json",
                llm_provider="none",
                llm_api_key="",
            )
            settings.ensure_dirs()
            repository = Repository(settings)
            imported = ApiService(settings, repository).import_spec(
                filename="petstore.yaml",
                data=petstore_bytes(),
            )
            service = ExecutionService(settings, repository)

            first = service.create_artifact(
                AutomationCreateRequest(spec_id=imported.spec.spec_id)
            )
            second = service.create_artifact(
                AutomationCreateRequest(spec_id=imported.spec.spec_id)
            )
            assert first.status == "validated"
            assert first.validation_errors == []
            assert first.revision == 1
            assert second.revision == 2
            assert {
                "README.md",
                "pytest.ini",
                "requirements.txt",
                ".env.example",
                "conftest.py",
                "cases.json",
                "tests/test_api_cases.py",
            } == {item.path for item in first.files}
            assert "Authorization: Bearer sk-" not in "\n".join(
                item.content for item in first.files
            )

            content, filename = service.artifact_download(first.artifact_id)
            assert filename.endswith(".zip")
            with ZipFile(BytesIO(content)) as archive:
                assert archive.namelist() == [item.path for item in first.files]
                cases = json.loads(archive.read("cases.json"))
                assert len(cases) == len(first.case_ids)
                assert all(item["case_id"] for item in cases)

    def test_validator_rejects_dangerous_code_and_secret(self) -> None:
        dangerous = validate_generated_files(
            [
                GeneratedFile(
                    path="tests/test_bad.py",
                    content=(
                        "import subprocess\n"
                        "def test_bad():\n"
                        "    eval('1 + 1')\n"
                        "    subprocess.run(['whoami'])\n"
                    ),
                ),
                GeneratedFile(path=".env.example", content="TOKEN=sk-live-secret-value-123456\n"),
            ]
        )
        codes = {issue.code for issue in dangerous.errors}
        assert {"FORBIDDEN_IMPORT", "FORBIDDEN_CALL", "POSSIBLE_SECRET"} <= codes
        assert dangerous.ok is False


class TestJUnitParser:
    def test_pytest_dialect_maps_failure_error_skip_and_properties(self) -> None:
        data = b"""\
<testsuites>
  <testsuite name="pytest" time="2.5">
    <testcase classname="tests.test_api" name="[API-PASS-001] ok" time="0.1"/>
    <testcase classname="tests.test_api" name="[API-FAIL-002] bad" time="0.2">
      <failure message="expected 200">trace</failure>
    </testcase>
    <testcase classname="tests.test_api" name="error case" time="0.3">
      <properties><property name="case_id" value="API-ERROR-003"/></properties>
      <error message="connection reset"/>
    </testcase>
    <testcase classname="tests.test_api" name="[API-SKIP-004] optional" time="0.1">
      <skipped message="not configured"/>
    </testcase>
  </testsuite>
</testsuites>
"""
        cases, duration_ms, warnings = parse_junit_xml(data)
        assert [item.status for item in cases] == ["passed", "failed", "error", "skipped"]
        assert [item.case_id for item in cases] == [
            "API-PASS-001",
            "API-FAIL-002",
            "API-ERROR-003",
            "API-SKIP-004",
        ]
        assert duration_ms == 2500
        assert warnings == []

    def test_malformed_or_wrong_root_is_rejected(self) -> None:
        try:
            parse_junit_xml(b"<root/>")
        except JUnitParseError as exc:
            assert "testsuite" in exc.message
        else:
            raise AssertionError("unexpected acceptance of unsupported root")

        try:
            parse_junit_xml(b"<testsuite>")
        except JUnitParseError as exc:
            assert "格式不合法" in exc.message
        else:
            raise AssertionError("unexpected acceptance of malformed XML")


class TestExecutionRoutes:
    def test_artifact_import_events_and_follow_up_work_item(self, client) -> None:
        imported = client.post(
            f"{API}/api-specs/import",
            files={"file": ("petstore.yaml", petstore_bytes(), "application/yaml")},
        )
        assert imported.status_code == 200, imported.text
        spec = imported.json()["data"]["spec"]
        cases = client.get(f"{API}/api-specs/{spec['spec_id']}/cases").json()["data"]["cases"]
        selected = cases[0]

        created = client.post(
            f"{API}/automation/artifacts",
            json={"spec_id": spec["spec_id"], "case_ids": [selected["case_id"]]},
        )
        assert created.status_code == 200, created.text
        artifact = created.json()["data"]
        assert artifact["status"] == "validated"
        assert artifact["case_ids"] == [selected["case_id"]]

        download = client.get(
            f"{API}/automation/artifacts/{artifact['artifact_id']}/download"
        )
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/zip"
        with ZipFile(BytesIO(download.content)) as archive:
            assert "tests/test_api_cases.py" in archive.namelist()

        xml = f"""\
<testsuite name="pytest" time="0.7">
  <testcase name="[{selected['case_id']}]" time="0.2">
    <failure message="status mismatch"/>
  </testcase>
  <testcase case_id="API-UNKNOWN-999" name="unknown" time="0.1"/>
</testsuite>
""".encode()
        run_response = client.post(
            f"{API}/automation/runs/import",
            files={"file": ("junit.xml", xml, "application/xml")},
            data={"artifact_id": artifact["artifact_id"]},
        )
        assert run_response.status_code == 200, run_response.text
        run = run_response.json()["data"]
        assert (run["total"], run["passed"], run["failed"], run["matched"], run["unmatched"]) == (
            2,
            1,
            1,
            1,
            1,
        )
        assert run["cases"][0]["case_id"] == selected["case_id"]
        assert run["cases"][0]["operation_id"] == selected["operation_id"]
        assert run["unmatched_cases"][0]["case_id"] == "API-UNKNOWN-999"

        events = client.get(
            f"{API}/automation/events", params={"run_id": run["run_id"]}
        ).json()["data"]
        assert any(event["action"] == "junit.import" for event in events)
        assert all("Authorization" not in event["message"] for event in events)

        follow_up = client.post(
            f"{API}/automation/runs/{run['run_id']}/follow-up",
            json={"priority": "P1"},
        )
        assert follow_up.status_code == 200, follow_up.text
        item = follow_up.json()["data"]
        assert item["item_type"] == "task"
        assert item["links"][0]["resource_type"] == "test_run"
        assert item["links"][0]["resource_id"] == run["run_id"]

        blocked_artifact_delete = client.delete(
            f"{API}/automation/artifacts/{artifact['artifact_id']}"
        )
        assert blocked_artifact_delete.status_code == 409
        deleted_run = client.delete(f"{API}/automation/runs/{run['run_id']}")
        assert deleted_run.status_code == 200
        assert client.get(
            f"{API}/automation/events", params={"run_id": run["run_id"]}
        ).json()["data"] == []
        deleted_artifact = client.delete(
            f"{API}/automation/artifacts/{artifact['artifact_id']}"
        )
        assert deleted_artifact.status_code == 200

    def test_import_rejects_bad_xml_without_creating_run(self, client) -> None:
        before = client.get(f"{API}/automation/runs").json()["data"]
        response = client.post(
            f"{API}/automation/runs/import",
            files={"file": ("broken.xml", b"<not-junit>", "application/xml")},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "JUNIT_PARSE_FAILED"
        after = client.get(f"{API}/automation/runs").json()["data"]
        assert len(after) == len(before)
