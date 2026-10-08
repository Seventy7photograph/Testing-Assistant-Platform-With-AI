"""导出接口：Excel / JSON。"""
from __future__ import annotations

from fastapi import APIRouter, Response

from app.api.deps import ExportServiceDep
from app.api.responses import build_download_response
from app.exporters.registry import available_formats
from app.schemas.api import ApiResponse, ExportFormatInfo, ExportRequest, ok

router = APIRouter(tags=["导出"])


@router.get("/export/formats", response_model=ApiResponse[list[ExportFormatInfo]], summary="可用导出格式")
async def list_formats() -> dict:
    return ok([ExportFormatInfo(**item) for item in available_formats()])


@router.post("/export", summary="导出用例集（返回文件流）")
async def export_suite(payload: ExportRequest, service: ExportServiceDep) -> Response:
    result = service.export_suite(payload.suite_id, payload.format)
    return build_download_response(result.content, result.filename, result.media_type)


@router.get("/export/{suite_id}/{fmt}", summary="按路径导出用例集（便于浏览器直接下载）")
async def export_suite_by_path(suite_id: str, fmt: str, service: ExportServiceDep) -> Response:
    result = service.export_suite(suite_id, fmt)
    return build_download_response(result.content, result.filename, result.media_type)
