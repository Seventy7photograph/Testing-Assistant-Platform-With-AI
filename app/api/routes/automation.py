"""V2.3 自动化资产生成与 JUnit 执行结果回收入口。"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, Query, Response, UploadFile
from pydantic import BaseModel, Field

from app.api.deps import AutomationServiceDep, WorkItemServiceDep
from app.api.responses import build_download_response
from app.schemas.api import ApiResponse, ok
from app.schemas.execution import (
    AutomationArtifact,
    AutomationArtifactSummary,
    AutomationCreateRequest,
    JobEvent,
    TestRun,
    TestRunSummary,
)
from app.schemas.work_item import WorkItem, WorkItemCreate, WorkItemLink, WorkItemPriority

router = APIRouter(tags=["自动化交付"])


class RunFollowUpRequest(BaseModel):
    priority: WorkItemPriority = "P1"
    remind_at: str | None = None


@router.post(
    "/automation/artifacts",
    response_model=ApiResponse[AutomationArtifact],
    summary="从接口用例生成受控 pytest 资产",
)
async def create_automation_artifact(
    payload: AutomationCreateRequest,
    service: AutomationServiceDep,
) -> dict:
    artifact = service.create_artifact(payload)
    message = (
        f"已生成 {len(artifact.case_ids)} 条用例的 pytest 资产"
        if artifact.status == "validated"
        else "资产已生成但未通过安全校验，已禁止下载"
    )
    return ok(artifact, message=message)


@router.get(
    "/automation/artifacts",
    response_model=ApiResponse[list[AutomationArtifactSummary]],
    summary="自动化资产列表",
)
async def list_automation_artifacts(
    service: AutomationServiceDep,
    spec_id: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
) -> dict:
    return ok(service.list_artifacts(spec_id=spec_id, limit=limit))


@router.get(
    "/automation/artifacts/{artifact_id}",
    response_model=ApiResponse[AutomationArtifact],
    summary="自动化资产详情",
)
async def get_automation_artifact(artifact_id: str, service: AutomationServiceDep) -> dict:
    return ok(service.get_artifact(artifact_id))


@router.get("/automation/artifacts/{artifact_id}/download", summary="下载自动化资产 zip")
async def download_automation_artifact(
    artifact_id: str,
    service: AutomationServiceDep,
) -> Response:
    content, filename = service.artifact_download(artifact_id)
    return build_download_response(content, filename, "application/zip")


@router.delete(
    "/automation/artifacts/{artifact_id}",
    response_model=ApiResponse[dict],
    summary="删除未关联执行记录的自动化资产",
)
async def delete_automation_artifact(artifact_id: str, service: AutomationServiceDep) -> dict:
    return ok(service.delete_artifact(artifact_id), message="自动化资产已删除")


@router.post(
    "/automation/runs/import",
    response_model=ApiResponse[TestRun],
    summary="导入 JUnit XML 执行结果",
)
async def import_junit_run(
    service: AutomationServiceDep,
    file: UploadFile = File(...),
    artifact_id: str | None = Form(default=None),
) -> dict:
    run = service.import_junit(
        filename=file.filename or "junit.xml",
        data=await file.read(),
        artifact_id=artifact_id or None,
    )
    return ok(
        run,
        message=(
            f"已导入 {run.total} 条结果：通过 {run.passed}，失败 {run.failed}，"
            f"错误 {run.errors}，跳过 {run.skipped}，未匹配 {run.unmatched}"
        ),
    )


@router.get(
    "/automation/runs",
    response_model=ApiResponse[list[TestRunSummary]],
    summary="执行记录列表",
)
async def list_test_runs(
    service: AutomationServiceDep,
    artifact_id: str | None = Query(default=None),
    spec_id: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
) -> dict:
    return ok(service.list_runs(artifact_id=artifact_id, spec_id=spec_id, limit=limit))


@router.get(
    "/automation/runs/{run_id}",
    response_model=ApiResponse[TestRun],
    summary="执行记录详情",
)
async def get_test_run(run_id: str, service: AutomationServiceDep) -> dict:
    return ok(service.get_run(run_id))


@router.delete(
    "/automation/runs/{run_id}",
    response_model=ApiResponse[dict],
    summary="删除执行记录与关联事件",
)
async def delete_test_run(run_id: str, service: AutomationServiceDep) -> dict:
    return ok(service.delete_run(run_id), message="执行记录已删除")


@router.get(
    "/automation/runs/{run_id}/report-source",
    response_model=ApiResponse[dict[str, str]],
    summary="取得可送入测试报告工作台的执行数据",
)
async def test_run_report_source(run_id: str, service: AutomationServiceDep) -> dict:
    return ok(service.run_report_source(run_id))


@router.post(
    "/automation/runs/{run_id}/follow-up",
    response_model=ApiResponse[WorkItem],
    summary="从执行记录一键创建跟进事项",
)
async def create_run_follow_up(
    run_id: str,
    payload: RunFollowUpRequest,
    execution: AutomationServiceDep,
    work_items: WorkItemServiceDep,
) -> dict:
    run = execution.get_run(run_id)
    failing = [item for item in [*run.cases, *run.unmatched_cases] if item.status in {"failed", "error"}]
    first = failing[0].name if failing else "执行待复核"
    item = work_items.create(
        WorkItemCreate(
            item_type="task",
            title=f"跟进自动化失败：{first}",
            body=(
                f"运行 `{run.run_id}` 共 {run.total} 条，失败 {run.failed}，错误 {run.errors}，"
                f"跳过 {run.skipped}，未匹配 {run.unmatched}。"
            ),
            status="todo",
            priority=payload.priority,
            remind_at=payload.remind_at,
            tags=["自动化", "失败跟进"],
            links=[
                WorkItemLink(
                    resource_type="test_run",
                    resource_id=run.run_id,
                    label=run.source_file or run.run_id,
                    href=f"/workspace?run={run.run_id}",
                )
            ],
        )
    )
    return ok(item, message="已创建关联执行记录的跟进事项")


@router.get(
    "/automation/events",
    response_model=ApiResponse[list[JobEvent]],
    summary="按运行或资产检索结构化任务事件",
)
async def list_job_events(
    service: AutomationServiceDep,
    run_id: str | None = Query(default=None),
    artifact_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    return ok(service.list_events(run_id=run_id, artifact_id=artifact_id, limit=limit))


__all__ = ["router"]
