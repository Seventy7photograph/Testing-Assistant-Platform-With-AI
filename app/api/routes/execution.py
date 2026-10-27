"""v3.0 受控 HTTP 执行入口。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import AutomationServiceDep, SettingsDep
from app.execution.http_executor import ControlledHttpExecutor
from app.schemas.api import ApiResponse, ok
from app.schemas.platform_execution import (
    ApiEnvironmentCreate,
    ApiEnvironmentProfile,
    ApiEnvironmentUpdate,
    HttpExecutionRequest,
    HttpExecutionResponse,
)
from app.services.api_environment_service import ApiEnvironmentService

router = APIRouter(tags=["受控执行"])


@router.get(
    "/execution/environments",
    response_model=ApiResponse[list[ApiEnvironmentProfile]],
    summary="项目接口测试环境列表",
)
async def list_api_environments(
    settings: SettingsDep,
    service: AutomationServiceDep,
) -> dict:
    return ok(ApiEnvironmentService(settings, service.repository).list())


@router.post(
    "/execution/environments",
    response_model=ApiResponse[ApiEnvironmentProfile],
    summary="创建接口测试环境（敏感 Header 只存变量占位符）",
)
async def create_api_environment(
    payload: ApiEnvironmentCreate,
    settings: SettingsDep,
    service: AutomationServiceDep,
) -> dict:
    return ok(
        ApiEnvironmentService(settings, service.repository).create(payload),
        message="接口测试环境已创建",
    )


@router.put(
    "/execution/environments/{environment_id}",
    response_model=ApiResponse[ApiEnvironmentProfile],
    summary="更新接口测试环境",
)
async def update_api_environment(
    environment_id: str,
    payload: ApiEnvironmentUpdate,
    settings: SettingsDep,
    service: AutomationServiceDep,
) -> dict:
    return ok(
        ApiEnvironmentService(settings, service.repository).update(
            environment_id, payload
        ),
        message="接口测试环境已更新",
    )


@router.delete(
    "/execution/environments/{environment_id}",
    response_model=ApiResponse[dict],
    summary="删除接口测试环境",
)
async def delete_api_environment(
    environment_id: str,
    settings: SettingsDep,
    service: AutomationServiceDep,
) -> dict:
    return ok(
        ApiEnvironmentService(settings, service.repository).delete(environment_id),
        message="接口测试环境已删除",
    )


@router.post(
    "/execution/http",
    response_model=ApiResponse[HttpExecutionResponse],
    summary="执行已校验自动化资产中的接口用例",
)
async def execute_http(
    payload: HttpExecutionRequest,
    settings: SettingsDep,
    service: AutomationServiceDep,
) -> dict:
    executor = ControlledHttpExecutor(settings, service.repository)
    result = await executor.execute(payload)
    return ok(
        result,
        message=(
            f"受控执行完成：通过 {result.run.passed}，失败 {result.run.failed}，"
            f"错误 {result.run.errors}"
        ),
    )


__all__ = ["router"]
