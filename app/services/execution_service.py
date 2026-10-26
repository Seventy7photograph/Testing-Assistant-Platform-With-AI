"""自动化资产生成、JUnit 回收与运行事件服务。"""
from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from app.automation.pytest_generator import build_pytest_artifact
from app.automation.validators import validate_generated_files
from app.core.config import Settings, get_settings
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError, PayloadTooLargeError
from app.core.logging import get_logger, sanitize_log_text
from app.core.utils import dump_json, new_id, now_iso
from app.execution.junit_parser import parse_junit_xml
from app.repository import Repository, get_repository
from app.schemas.execution import (
    AutomationArtifact,
    AutomationArtifactSummary,
    AutomationCreateRequest,
    JobEvent,
    TestRun,
    TestRunSummary,
)

logger = get_logger(__name__)


class ExecutionService:
    def __init__(
        self,
        settings: Settings | None = None,
        repository: Repository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or get_repository()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def add_event(
        self,
        *,
        trace_id: str,
        action: str,
        status: str,
        message: str = "",
        artifact_id: str | None = None,
        run_id: str | None = None,
        work_item_id: str | None = None,
    ) -> JobEvent:
        event = JobEvent(
            event_id=new_id("EVT-"),
            trace_id=trace_id,
            action=action,
            status=status,
            artifact_id=artifact_id,
            run_id=run_id,
            work_item_id=work_item_id,
            message=sanitize_log_text(message),
        )
        self.repository.job_events.save(event)
        logger.info(
            "任务事件 %s %s status=%s run=%s artifact=%s",
            event.trace_id,
            event.action,
            event.status,
            event.run_id or "-",
            event.artifact_id or "-",
        )
        return event

    def list_events(
        self,
        *,
        run_id: str | None = None,
        artifact_id: str | None = None,
        limit: int = 100,
    ) -> list[JobEvent]:
        items = self.repository.job_events.list_recent(
            min(max(limit, 1), 500),
            predicate=lambda event: (
                (run_id is None or event.run_id == run_id)
                and (artifact_id is None or event.artifact_id == artifact_id)
            ),
        )
        return items

    # ------------------------------------------------------------------
    # Artifacts
    # ------------------------------------------------------------------
    def create_artifact(self, request: AutomationCreateRequest) -> AutomationArtifact:
        trace_id = new_id("TRACE-")
        spec = self.repository.api_specs.get(request.spec_id)
        available = self.repository.api_cases.list_recent(
            limit=20_000, predicate=lambda item: item.spec_id == spec.spec_id
        )
        by_id = {item.case_id: item for item in available}
        if request.case_ids:
            missing = [case_id for case_id in request.case_ids if case_id not in by_id]
            if missing:
                raise BadRequestError(
                    "部分接口用例不存在或不属于该规范。",
                    detail={"missing_case_ids": missing[:50], "missing_count": len(missing)},
                )
            ordered = [by_id[case_id] for case_id in dict.fromkeys(request.case_ids)]
        else:
            ordered = available
        ordered.sort(key=lambda item: (item.operation_id, item.category != "positive", item.case_id))
        if not ordered:
            raise BadRequestError("该接口规范没有可生成的用例。", detail={"spec_id": spec.spec_id})
        if len(ordered) > 2_000:
            raise BadRequestError(
                "单次最多生成 2000 条接口用例资产。",
                detail={"requested": len(ordered), "max": 2_000},
            )

        artifact = build_pytest_artifact(
            spec,
            ordered,
            artifact_id=new_id("AUTO-"),
            revision=self.repository.next_artifact_revision(spec.spec_id),
        )
        validation = validate_generated_files(artifact.files)
        artifact.validation_errors = validation.errors
        artifact.warnings.extend(validation.warnings)
        artifact.status = "validated" if validation.ok else "rejected"
        self.repository.automation_artifacts.save(artifact)
        self.add_event(
            trace_id=trace_id,
            action="automation.generate",
            status=artifact.status,
            artifact_id=artifact.artifact_id,
            message=(
                f"spec={spec.spec_id}; cases={len(artifact.case_ids)}; "
                f"errors={len(artifact.validation_errors)}"
            ),
        )
        return artifact

    def list_artifacts(self, *, spec_id: str | None = None, limit: int = 30) -> list[AutomationArtifactSummary]:
        items = self.repository.automation_artifacts.list_recent(
            min(max(limit, 1), 100),
            predicate=lambda item: spec_id is None or item.spec_id == spec_id,
        )
        return [item.summary() for item in items]

    def get_artifact(self, artifact_id: str) -> AutomationArtifact:
        return self.repository.automation_artifacts.get(artifact_id)

    def artifact_download(self, artifact_id: str) -> tuple[bytes, str]:
        artifact = self.get_artifact(artifact_id)
        if artifact.status != "validated":
            raise ConflictError(
                "该自动化资产未通过安全校验，不能下载。",
                detail={
                    "artifact_id": artifact_id,
                    "errors": [item.model_dump() for item in artifact.validation_errors],
                },
            )
        buffer = BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
            for item in artifact.files:
                archive.writestr(item.path, item.content.encode("utf-8"))
        return buffer.getvalue(), f"{artifact.artifact_id}-v{artifact.revision}.zip"

    def delete_artifact(self, artifact_id: str) -> dict:
        self.get_artifact(artifact_id)
        linked_runs = self.repository.test_runs.list_recent(
            limit=1, predicate=lambda item: item.artifact_id == artifact_id
        )
        if linked_runs:
            raise ConflictError(
                "该资产已关联执行记录，请先删除相关执行记录。",
                detail={"artifact_id": artifact_id, "run_id": linked_runs[0].run_id},
            )
        events = self.repository.job_events.list_recent(
            limit=10_000,
            predicate=lambda event: event.artifact_id == artifact_id,
        )
        for event in events:
            self.repository.job_events.delete(event.event_id)
        self.repository.automation_artifacts.delete(artifact_id)
        return {"deleted": True, "artifact_id": artifact_id}

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------
    def import_junit(
        self,
        *,
        filename: str,
        data: bytes,
        artifact_id: str | None = None,
    ) -> TestRun:
        trace_id = new_id("TRACE-")
        if len(data) > self.settings.max_upload_size_bytes:
            raise PayloadTooLargeError(
                f"JUnit 文件超过 {self.settings.max_upload_size_mb} MB 上限。",
                detail={"size_bytes": len(data), "max_mb": self.settings.max_upload_size_mb},
            )
        artifact = self.get_artifact(artifact_id) if artifact_id else None
        if artifact and artifact.status != "validated":
            raise BadRequestError("不能把执行结果关联到未通过校验的资产。")
        parsed, duration_ms, warnings = parse_junit_xml(data, source_file=filename)

        known_cases = {
            item.case_id: item
            for item in self.repository.api_cases.list_recent(limit=20_000)
        }
        matched = []
        unmatched = []
        for item in parsed:
            mapped = known_cases.get(item.case_id or "")
            if mapped is None or (
                artifact is not None and mapped.case_id not in set(artifact.case_ids)
            ):
                unmatched.append(item)
                continue
            item.operation_id = mapped.operation_id
            matched.append(item)

        passed = sum(1 for item in parsed if item.status == "passed")
        failed = sum(1 for item in parsed if item.status == "failed")
        errors = sum(1 for item in parsed if item.status == "error")
        skipped = sum(1 for item in parsed if item.status == "skipped")
        if unmatched:
            warnings.append(f"{len(unmatched)} 条执行结果未匹配平台接口用例，已保留在未匹配列表。")
        run = TestRun(
            run_id=new_id("RUN-"),
            artifact_id=artifact.artifact_id if artifact else None,
            spec_id=artifact.spec_id if artifact else None,
            source_file=Path(filename or "junit.xml").name,
            source_hash=sha256(data).hexdigest(),
            total=len(parsed),
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            matched=len(matched),
            unmatched=len(unmatched),
            duration_ms=duration_ms,
            cases=matched,
            unmatched_cases=unmatched,
            warnings=warnings,
            raw_xml=data.decode("utf-8", errors="replace"),
            created_at=now_iso(),
        )
        self.repository.test_runs.save(run)
        self.add_event(
            trace_id=trace_id,
            action="junit.import",
            status="completed",
            artifact_id=run.artifact_id,
            run_id=run.run_id,
            message=(
                f"total={run.total}; passed={run.passed}; failed={run.failed}; "
                f"errors={run.errors}; skipped={run.skipped}; unmatched={run.unmatched}"
            ),
        )
        return run

    def list_runs(
        self,
        *,
        artifact_id: str | None = None,
        spec_id: str | None = None,
        limit: int = 30,
    ) -> list[TestRunSummary]:
        items = self.repository.test_runs.list_recent(
            min(max(limit, 1), 100),
            predicate=lambda item: (
                (artifact_id is None or item.artifact_id == artifact_id)
                and (spec_id is None or item.spec_id == spec_id)
            ),
        )
        return [item.summary() for item in items]

    def get_run(self, run_id: str) -> TestRun:
        return self.repository.test_runs.get(run_id)

    def delete_run(self, run_id: str) -> dict:
        self.get_run(run_id)
        events = self.repository.job_events.list_recent(
            limit=10_000,
            predicate=lambda event: event.run_id == run_id,
        )
        for event in events:
            self.repository.job_events.delete(event.event_id)
        self.repository.test_runs.delete(run_id)
        return {"deleted": True, "run_id": run_id}

    def run_report_source(self, run_id: str) -> dict[str, str]:
        run = self.get_run(run_id)
        payload = {
            "version": run.artifact_id or run.run_id,
            "summary": {
                "total": run.total,
                "passed": run.passed,
                "failed": run.failed + run.errors,
                "skipped": run.skipped,
                "duration_ms": run.duration_ms,
            },
            "cases": [
                {
                    "case_id": item.case_id,
                    "title": item.name,
                    "status": item.status,
                    "duration_ms": item.duration_ms,
                    "operation_id": item.operation_id,
                }
                for item in [*run.cases, *run.unmatched_cases]
            ],
        }
        return {
            "test_data": dump_json(payload),
            "suggested_title": f"自动化执行 {run.source_file or run.run_id}",
        }

    def recent_counts(self) -> dict[str, int]:
        today = datetime.now().astimezone().date()
        runs = self.repository.test_runs.list_recent(limit=100)
        return {
            "automation_artifacts": self.repository.automation_artifacts.count(),
            "test_runs": self.repository.test_runs.count(),
            "failed_runs_today": sum(
                1
                for run in runs
                if run.failed + run.errors > 0
                and datetime.fromisoformat(run.created_at).astimezone().date() == today
            ),
        }


__all__ = ["ExecutionService"]
