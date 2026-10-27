"""项目级任务、调度定义与 Agent 审计服务。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.config import Settings, get_settings
from app.core.context import get_current_actor, get_current_project_id
from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import sanitize_log_text
from app.core.utils import new_id, now_iso
from app.repository import Repository, get_repository
from app.schemas.execution import JobEvent
from app.schemas.jobs import AgentRun, Job, JobCreate, Schedule, ScheduleCreate, ToolCall
from app.services.project_service import ProjectService


class JobService:
    def __init__(
        self,
        settings: Settings | None = None,
        repository: Repository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or get_repository()
        self.project_id = get_current_project_id() or "PRJ-default"
        self.project_service = ProjectService(self.settings)
        self.project_service.ensure_default()

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------
    def create(self, payload: JobCreate) -> Job:
        if payload.idempotency_key:
            existing = self.repository.jobs.list_recent(
                limit=1,
                predicate=lambda item: (
                    item.kind == payload.kind
                    and item.idempotency_key == payload.idempotency_key
                ),
            )
            if existing:
                return existing[0]
        project = self.project_service.get(self.project_id)
        self.project_service.check_quota(
            project,
            resource="jobs",
            current=self.repository.jobs.count(),
        )
        job = Job(
            job_id=new_id("JOB-"),
            project_id=self.project_id,
            kind=payload.kind,
            trace_id=new_id("TRACE-"),
            idempotency_key=payload.idempotency_key,
            timeout_seconds=payload.timeout_seconds,
            max_attempts=payload.max_attempts,
            payload_summary=self._safe_dict(payload.payload_summary),
            created_by=get_current_actor(),
        )
        self.repository.jobs.save(job)
        self.event(job, "job.created", "queued")
        self.project_service.audit(
            action="job.create",
            resource_type="job",
            resource_id=job.job_id,
            project_id=self.project_id,
            actor=get_current_actor(),
            trace_id=job.trace_id,
            detail={"kind": job.kind, "idempotency_key": job.idempotency_key},
        )
        return job

    def start(self, job: Job) -> Job:
        if job.status not in {"queued", "failed"}:
            raise ConflictError(
                "当前任务状态不允许启动。",
                detail={"job_id": job.job_id, "status": job.status},
            )
        job.status = "running"
        job.attempt += 1
        job.started_at = now_iso()
        job.finished_at = None
        job.error = ""
        self.repository.jobs.save(job)
        self.event(job, "job.started", "running")
        return job

    def finish(
        self,
        job: Job,
        *,
        succeeded: bool,
        result: dict | None = None,
        error: str = "",
    ) -> Job:
        job.status = "succeeded" if succeeded else "failed"
        job.result_summary = self._safe_dict(result or {})
        job.error = sanitize_log_text(error)[:2000]
        job.finished_at = now_iso()
        self.repository.jobs.save(job)
        self.event(
            job,
            "job.finished",
            job.status,
            message=job.error or "任务完成",
        )
        self.project_service.audit(
            action="job.finish",
            resource_type="job",
            resource_id=job.job_id,
            project_id=self.project_id,
            outcome="succeeded" if succeeded else "failed",
            actor=get_current_actor(),
            trace_id=job.trace_id,
            detail={"kind": job.kind, "status": job.status},
        )
        return job

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status in {"succeeded", "failed", "cancelled"}:
            raise ConflictError(
                "已结束的任务不能取消。",
                detail={"job_id": job_id, "status": job.status},
            )
        job.status = "cancelled"
        job.finished_at = now_iso()
        self.repository.jobs.save(job)
        self.event(job, "job.cancelled", "cancelled")
        return job

    def get(self, job_id: str) -> Job:
        job = self.repository.jobs.get(job_id)
        if job.project_id != self.project_id:
            raise NotFoundError("任务不存在。", detail={"job_id": job_id})
        return job

    def list_jobs(self, *, status: str = "", kind: str = "", limit: int = 100) -> list[Job]:
        return self.repository.jobs.list_recent(
            min(max(limit, 1), 500),
            predicate=lambda item: (
                item.project_id == self.project_id
                and (not status or item.status == status)
                and (not kind or item.kind == kind)
            ),
        )

    def events(self, job_id: str, limit: int = 200) -> list[JobEvent]:
        self.get(job_id)
        return self.repository.job_events.list_recent(
            min(max(limit, 1), 1000),
            predicate=lambda item: item.job_id == job_id,
        )

    def event(
        self,
        job: Job,
        action: str,
        status: str,
        *,
        message: str = "",
    ) -> JobEvent:
        event = JobEvent(
            event_id=new_id("EVT-"),
            trace_id=job.trace_id,
            project_id=self.project_id,
            job_id=job.job_id,
            action=action,
            status=status,
            message=sanitize_log_text(message),
        )
        self.repository.job_events.save(event)
        return event

    # ------------------------------------------------------------------
    # Schedules (definitions only; execution belongs to V3.2)
    # ------------------------------------------------------------------
    def create_schedule(self, payload: ScheduleCreate) -> Schedule:
        base_time = (
            datetime.fromisoformat(payload.first_run_at)
            if payload.first_run_at
            else datetime.now(timezone.utc) + timedelta(seconds=payload.interval_seconds)
        )
        schedule = Schedule(
            schedule_id=new_id("SCH-"),
            project_id=self.project_id,
            name=payload.name,
            job_kind=payload.job_kind,
            interval_seconds=payload.interval_seconds,
            timezone=payload.timezone,
            enabled=payload.enabled,
            max_runs=payload.max_runs,
            payload_summary=self._safe_dict(payload.payload_summary),
            next_run_at=base_time.isoformat(timespec="seconds"),
        )
        self.repository.schedules.save(schedule)
        self.project_service.audit(
            action="schedule.create",
            resource_type="schedule",
            resource_id=schedule.schedule_id,
            project_id=self.project_id,
            actor=get_current_actor(),
            detail={"job_kind": schedule.job_kind},
        )
        return schedule

    def list_schedules(self, limit: int = 100) -> list[Schedule]:
        return self.repository.schedules.list_recent(
            min(max(limit, 1), 500),
            predicate=lambda item: item.project_id == self.project_id,
        )

    # ------------------------------------------------------------------
    # Agent runs / tool calls
    # ------------------------------------------------------------------
    def create_agent_run(
        self,
        request: str,
        *,
        agent_kind: str = "readonly_assistant",
        conversation_id: str = "",
    ) -> AgentRun:
        run = AgentRun(
            run_id=new_id("AGENT-"),
            project_id=self.project_id,
            agent_kind=agent_kind,
            conversation_id=conversation_id,
            request=request[:20_000],
            trace_id=new_id("TRACE-"),
            created_by=get_current_actor(),
        )
        self.repository.agent_runs.save(run)
        return run

    def finish_agent_run(
        self,
        run: AgentRun,
        *,
        status: str,
        response: str,
        citation_ids: list[str],
        tool_call_ids: list[str],
        error: str = "",
    ) -> AgentRun:
        run.status = status  # type: ignore[assignment]
        run.response = response[:50_000]
        run.citation_ids = list(dict.fromkeys(citation_ids))
        run.tool_call_ids = list(dict.fromkeys(tool_call_ids))
        run.error = sanitize_log_text(error)[:2000]
        run.finished_at = now_iso()
        self.repository.agent_runs.save(run)
        return run

    def record_tool_call(
        self,
        *,
        run: AgentRun,
        tool_name: str,
        status: str,
        arguments: dict,
        result: dict,
        error: str = "",
    ) -> ToolCall:
        call = ToolCall(
            tool_call_id=new_id("TOOL-"),
            project_id=self.project_id,
            run_id=run.run_id,
            tool_name=tool_name,
            status=status,  # type: ignore[arg-type]
            arguments_summary=self._safe_dict(arguments),
            result_summary=self._safe_dict(result),
            error=sanitize_log_text(error),
            trace_id=run.trace_id,
            finished_at=now_iso(),
        )
        self.repository.tool_calls.save(call)
        return call

    def list_agent_runs(self, limit: int = 50) -> list[AgentRun]:
        return self.repository.agent_runs.list_recent(
            min(max(limit, 1), 200),
            predicate=lambda item: item.project_id == self.project_id,
        )

    def list_tool_calls(self, *, run_id: str = "", limit: int = 100) -> list[ToolCall]:
        return self.repository.tool_calls.list_recent(
            min(max(limit, 1), 500),
            predicate=lambda item: (
                item.project_id == self.project_id
                and (not run_id or item.run_id == run_id)
            ),
        )

    @staticmethod
    def _safe_dict(value: dict) -> dict:
        result: dict = {}
        for key, item in value.items():
            text = sanitize_log_text(str(item))
            result[str(key)] = text[:1000]
        return result


__all__ = ["JobService"]
