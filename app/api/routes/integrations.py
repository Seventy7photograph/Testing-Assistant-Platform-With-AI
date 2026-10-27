"""v3.0 Jira / 禅道双向同步与状态回读。"""
from __future__ import annotations

import json

from fastapi import APIRouter, File, Query, UploadFile

from app.api.deps import IntegrationServiceDep
from app.core.exceptions import BadRequestError
from app.schemas.api import ApiResponse, ok
from app.schemas.integrations import (
    ExternalStatus,
    IntegrationHealth,
    IntegrationPullResult,
    IntegrationPushRequest,
    IntegrationPushResult,
    IntegrationSyncRequest,
)

router = APIRouter(tags=["外部集成"])


@router.get(
    "/integrations/capabilities",
    response_model=ApiResponse[list[dict]],
    summary="外部同步适配器能力",
)
async def integration_capabilities() -> dict:
    from app.integrations.base import available_integrations

    return ok(available_integrations())


@router.post(
    "/integrations/{name}/health",
    response_model=ApiResponse[IntegrationHealth],
    summary="检查 Jira / 禅道连通性与鉴权",
)
async def integration_health(
    name: str,
    service: IntegrationServiceDep,
    payload: IntegrationSyncRequest | None = None,
) -> dict:
    result = await service.health(name, payload)
    return ok(result, message=result.message)


@router.post(
    "/integrations/{name}/requirements/pull",
    response_model=ApiResponse[IntegrationPullResult],
    summary="从 Jira / 禅道拉取需求并建立文档",
)
async def pull_requirements(
    name: str,
    payload: IntegrationSyncRequest,
    service: IntegrationServiceDep,
) -> dict:
    result = await service.pull(name, payload)
    return ok(result, message=f"已拉取并写入 {result.fetched} 条外部需求。")


@router.post(
    "/integrations/{name}/requirements/import",
    response_model=ApiResponse[IntegrationPullResult],
    summary="用 JSON fixture 导入外部需求（无沙箱实例的验收路径）",
)
async def import_requirements(
    name: str,
    payload: IntegrationSyncRequest,
    service: IntegrationServiceDep,
) -> dict:
    result = await service.import_fixture(name, payload)
    return ok(result, message=f"已从 fixture 导入 {result.fetched} 条需求。")


@router.post(
    "/integrations/{name}/requirements/file",
    response_model=ApiResponse[IntegrationPullResult],
    summary="上传外部需求 JSON 文件作为 Jira / 禅道过渡导入",
)
async def import_requirements_file(
    name: str,
    service: IntegrationServiceDep,
    file: UploadFile = File(...),
    project_key: str = Query(default=""),
) -> dict:
    try:
        raw = json.loads((await file.read()).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BadRequestError("需求 JSON 文件格式不合法。", detail={"error": str(exc)}) from exc
    items = raw.get("requirements") if isinstance(raw, dict) else raw
    payload = IntegrationSyncRequest(
        project_key=project_key,
        options={"requirements": items},
    )
    result = await service.import_fixture(name, payload)
    return ok(result, message=f"已从文件导入 {result.fetched} 条需求。")


@router.post(
    "/integrations/{name}/suites/{suite_id}/push",
    response_model=ApiResponse[IntegrationPushResult],
    summary="把用例集回写到 Jira 任务/评论或禅道用例",
)
async def push_suite(
    name: str,
    suite_id: str,
    payload: IntegrationPushRequest,
    service: IntegrationServiceDep,
) -> dict:
    result = await service.push(name, suite_id, payload)
    return ok(result, message=result.message)


@router.get(
    "/integrations/{name}/requirements/{external_id}/status",
    response_model=ApiResponse[ExternalStatus],
    summary="回读外部需求状态",
)
async def external_status(
    name: str,
    external_id: str,
    service: IntegrationServiceDep,
) -> dict:
    return ok(await service.status(name, external_id))


__all__ = ["router"]
