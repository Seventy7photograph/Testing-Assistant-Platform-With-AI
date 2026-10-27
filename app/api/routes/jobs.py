"""v3.0 项目级任务、调度定义与 Agent 审计查询。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import JobServiceDep
from app.schemas.api import ApiResponse, ok
from app.schemas.execution import JobEvent
from app.schemas.jobs import AgentRun, Job, JobCreate, Schedule, ScheduleCreate, ToolCall

router = APIRouter(tags=["运行治理"])


@router.post("/jobs", response_model=ApiResponse[Job], summary="登记项目任务")
async def create_job(payload: JobCreate, service: JobServiceDep) -> dict:
    return ok(service.create(payload), message="任务已登记")


@router.get("/jobs", response_model=ApiResponse[list[Job]], summary="项目任务历史")
async def list_jobs(
    service: JobServiceDep,
    status: str = Query(default="", max_length=30),
    kind: str = Query(default="", max_length=80),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    return ok(service.list_jobs(status=status, kind=kind, limit=limit))


@router.get("/jobs/{job_id}", response_model=ApiResponse[Job], summary="任务详情")
async def get_job(job_id: str, service: JobServiceDep) -> dict:
    return ok(service.get(job_id))


@router.post("/jobs/{job_id}/cancel", response_model=ApiResponse[Job], summary="取消未结束任务")
async def cancel_job(job_id: str, service: JobServiceDep) -> dict:
    return ok(service.cancel(job_id), message="任务已取消")


@router.get(
    "/jobs/{job_id}/events",
    response_model=ApiResponse[list[JobEvent]],
    summary="任务事件时间线",
)
async def job_events(
    job_id: str,
    service: JobServiceDep,
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    return ok(service.events(job_id, limit))


@router.post(
    "/schedules",
    response_model=ApiResponse[Schedule],
    summary="登记受控调度定义（执行器在 v3.2 启用）",
)
async def create_schedule(payload: ScheduleCreate, service: JobServiceDep) -> dict:
    return ok(service.create_schedule(payload), message="调度定义已保存")


@router.get(
    "/schedules",
    response_model=ApiResponse[list[Schedule]],
    summary="项目调度定义列表",
)
async def list_schedules(
    service: JobServiceDep,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    return ok(service.list_schedules(limit))


@router.get(
    "/agent-runs",
    response_model=ApiResponse[list[AgentRun]],
    summary="Agent 运行历史",
)
async def list_agent_runs(
    service: JobServiceDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    return ok(service.list_agent_runs(limit))


@router.get(
    "/tool-calls",
    response_model=ApiResponse[list[ToolCall]],
    summary="白名单工具调用审计",
)
async def list_tool_calls(
    service: JobServiceDep,
    run_id: str = Query(default="", max_length=128),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    return ok(service.list_tool_calls(run_id=run_id, limit=limit))


__all__ = ["router"]
