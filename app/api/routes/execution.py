"""v3.0 受控 HTTP 执行入口。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import AutomationServiceDep, SettingsDep
from app.execution.http_executor import ControlledHttpExecutor
from app.schemas.api import ApiResponse, ok
from app.schemas.platform_execution import HttpExecutionRequest, HttpExecutionResponse

router = APIRouter(tags=["受控执行"])


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
