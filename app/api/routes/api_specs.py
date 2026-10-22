"""OpenAPI 接口资产导入、浏览、用例查询与 Postman 导出。"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, Query, Response, UploadFile

from app.api.deps import ApiServiceDep, ExportServiceDep, LLMDep
from app.api.responses import build_download_response
from app.schemas.api import ApiResponse, ok
from app.schemas.api_testing import (
    ApiCaseCollection,
    ApiImportResult,
    ApiOperation,
    ApiReviewResult,
    ApiSpec,
    ApiSpecDeleteResult,
    ApiSpecSummary,
)

router = APIRouter(tags=["接口资产"])


@router.post(
    "/api-specs/import",
    response_model=ApiResponse[ApiImportResult],
    summary="导入 OpenAPI 3 JSON / YAML 并生成接口用例",
)
async def import_api_spec(
    service: ApiServiceDep,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
) -> dict:
    data = await file.read()
    result = service.import_spec(
        filename=file.filename or "",
        data=data,
        title=title,
    )
    return ok(
        result,
        message=(
            f"已导入 {result.spec.stats.operations} 个 operation，"
            f"生成 {result.spec.stats.cases} 条接口用例"
        ),
    )


@router.get(
    "/api-specs",
    response_model=ApiResponse[list[ApiSpecSummary]],
    summary="接口规范列表",
)
async def list_api_specs(
    service: ApiServiceDep,
    limit: int = Query(default=30, ge=1, le=100),
) -> dict:
    return ok(service.list_specs(limit))


@router.get(
    "/api-specs/{spec_id}",
    response_model=ApiResponse[ApiSpec],
    summary="接口规范详情",
)
async def get_api_spec(spec_id: str, service: ApiServiceDep) -> dict:
    return ok(service.get_spec(spec_id))


@router.get(
    "/api-specs/{spec_id}/operations",
    response_model=ApiResponse[list[ApiOperation]],
    summary="operation 列表",
)
async def list_api_operations(spec_id: str, service: ApiServiceDep) -> dict:
    return ok(service.list_operations(spec_id))


@router.get(
    "/api-specs/{spec_id}/operations/{operation_id}",
    response_model=ApiResponse[ApiOperation],
    summary="operation 详情",
)
async def get_api_operation(
    spec_id: str,
    operation_id: str,
    service: ApiServiceDep,
) -> dict:
    return ok(service.get_operation(spec_id, operation_id))


@router.get(
    "/api-specs/{spec_id}/cases",
    response_model=ApiResponse[ApiCaseCollection],
    summary="接口用例列表；可按 operation 过滤",
)
async def list_api_cases(
    spec_id: str,
    service: ApiServiceDep,
    operation_id: str | None = Query(default=None),
) -> dict:
    return ok(service.list_cases(spec_id, operation_id=operation_id))


@router.post(
    "/api-specs/{spec_id}/review",
    response_model=ApiResponse[ApiReviewResult],
    summary="大模型只读复核接口用例",
)
async def review_api_spec(
    spec_id: str,
    service: ApiServiceDep,
    llm: LLMDep,
) -> dict:
    result = await service.review_spec(spec_id, llm)
    message = (
        f"AI 复核完成：{len(result.findings)} 条建议，"
        f"覆盖 {result.meta.reviewed_operations} 个 operation"
        if result.meta.used
        else "AI 复核未完成，已保留确定性用例。"
    )
    return ok(result, message=message)


@router.get(
    "/api-specs/{spec_id}/export/postman",
    summary="导出 Postman Collection 2.1",
)
async def export_postman(
    spec_id: str,
    service: ApiServiceDep,
    export_service: ExportServiceDep,
) -> Response:
    spec = service.get_spec(spec_id)
    cases = service.list_cases(spec_id).cases
    result = export_service.export_api(spec, cases)
    return build_download_response(result.content, result.filename, result.media_type)


@router.delete(
    "/api-specs/{spec_id}",
    response_model=ApiResponse[ApiSpecDeleteResult],
    summary="删除接口规范及其用例",
)
async def delete_api_spec(spec_id: str, service: ApiServiceDep) -> dict:
    return ok(service.delete_spec(spec_id), message="接口规范已删除")
