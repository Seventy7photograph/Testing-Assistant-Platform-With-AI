"""文档上传与查询。"""
from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path

from fastapi import APIRouter, File, Query, Response, UploadFile

from app.api.deps import DocumentServiceDep, RepositoryDep, SettingsDep
from app.api.responses import build_download_response
from app.core.exceptions import NotFoundError
from app.repository import Repository
from app.schemas.api import ApiResponse, BatchDeleteRequest, BatchDeleteResult, ok
from app.schemas.document import DocumentRecord, DocumentSummary
from app.vision.registry import vision_capabilities

router = APIRouter(tags=["文档"])


def _summary(record: DocumentRecord, repository: Repository) -> DocumentSummary:
    """列表/详情统一带上「解析过了没」。

    没有这个标记，文档库就只能一律显示「解析需求」——用户想回看上次的解析结果，
    唯一能点的按钮就是再解析一遍，既费时又可能重复消耗大模型额度。
    """
    requirement = repository.requirements.try_get(record.doc_id)
    return DocumentSummary.from_record(
        record,
        has_requirement=requirement is not None,
        requirement_items=len(requirement.items) if requirement is not None else 0,
        parse_meta=requirement.parse_meta if requirement is not None else None,
    )


@router.post(
    "/documents/upload",
    response_model=ApiResponse[DocumentSummary],
    summary="上传并解析需求文档（docx/pdf/txt/md/csv/json）",
)
async def upload_document(
    service: DocumentServiceDep, repository: RepositoryDep, file: UploadFile = File(...)
) -> dict:
    data = await file.read()
    record = await service.save_and_parse(filename=file.filename or "", data=data)
    return ok(_summary(record, repository), message="文档解析成功")


@router.get("/documents", response_model=ApiResponse[list[DocumentSummary]], summary="最近上传的文档")
async def list_documents(
    service: DocumentServiceDep,
    repository: RepositoryDep,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    records = service.list_recent(limit)
    return ok([_summary(record, repository) for record in records])


@router.get("/documents/{doc_id}", response_model=ApiResponse[DocumentSummary], summary="文档详情")
async def get_document(doc_id: str, service: DocumentServiceDep, repository: RepositoryDep) -> dict:
    return ok(_summary(service.get(doc_id), repository))


@router.get("/documents/{doc_id}/download", summary="下载文档原文")
async def download_document(
    doc_id: str, service: DocumentServiceDep, settings: SettingsDep
) -> Response:
    """原样返回上传时的文件，文件名恢复成用户上传时用的名字。

    原文在入库时就按 doc_id 存了一份（``storage/uploads``），
    需求文档常要拿去做评审、归档或跟版本对比，只进不出是不合理的。
    """
    record = service.get(doc_id)
    if not record.stored_path:
        raise NotFoundError(
            f"「{record.filename}」的原文没有留存（上传时落盘失败），无法下载。可重新上传该文件。"
        )
    path = Path(record.stored_path)
    if not path.is_file():
        raise NotFoundError(f"「{record.filename}」的原文已不在存储中，无法下载。可重新上传该文件。")
    # 只允许下载 uploads/ 目录内的文件：路径来自我们自己的记录，仍然兜一层，杜绝路径穿越。
    if settings.upload_dir.resolve() not in path.resolve().parents:
        raise NotFoundError("原文路径不在上传目录内，已拒绝下载。")
    media_type = mimetypes.guess_type(record.filename)[0] or "application/octet-stream"
    return build_download_response(path.read_bytes(), record.filename, media_type)


@router.get("/documents/{doc_id}/images/{filename}", summary="查看文档中的图片")
async def get_document_image(
    doc_id: str, filename: str, service: DocumentServiceDep, settings: SettingsDep
) -> Response:
    """回显文档里的某张图片（界面据此展示缩略图，便于人工核对识别结果）。"""
    record = service.get(doc_id)
    if not any(asset.filename == filename for asset in record.assets):
        raise NotFoundError(f"文档里没有这张图片：{filename}", detail={"doc_id": doc_id})
    directory = (settings.asset_dir / doc_id).resolve()
    path = (directory / filename).resolve()
    # 文件名来自我们自己的记录，仍然兜一层：不给路径穿越留任何余地。
    if directory not in path.parents or not path.is_file():
        raise NotFoundError(f"图片文件已不在存储中：{filename}", detail={"doc_id": doc_id})
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return Response(content=path.read_bytes(), media_type=media_type)


@router.post(
    "/documents/{doc_id}/images/recognize",
    response_model=ApiResponse[DocumentSummary],
    summary="重新识别文档中的图片",
)
async def recognize_document_images(
    doc_id: str, service: DocumentServiceDep, repository: RepositoryDep
) -> dict:
    """重新跑一遍图片识别。

    使用场景很具体：首次上传时没装本地 OCR、也没配多模态模型（图片被跳过），
    之后装好了想补识别；或者换了 VISION_MODE 想重新读一遍图片。
    识别通道仍不可用时返回 501，而不是假装成功。
    """
    record = await service.recognize_images(doc_id)
    return ok(_summary(record, repository), message="图片识别已完成")


@router.get(
    "/documents/vision/capabilities",
    response_model=ApiResponse[dict],
    summary="当前图片识别通道的能力与降级原因",
)
async def document_vision_capabilities(settings: SettingsDep) -> dict:
    return ok(vision_capabilities(settings))

def _purge_document(record: DocumentRecord, repository: RepositoryDep) -> None:
    """删除文档原文、图片、解析结果与文档记录（幂等）。"""
    if record.stored_path:
        try:
            Path(record.stored_path).unlink(missing_ok=True)
        except OSError:
            pass
    if record.assets:
        # 图片目录按 doc_id 命名，整个删掉即可（失败不影响主流程）。
        try:
            from app.core.config import get_settings

            shutil.rmtree(get_settings().asset_dir / record.doc_id, ignore_errors=True)
        except OSError:
            pass
    repository.requirements.delete(record.doc_id)
    repository.documents.delete(record.doc_id)


@router.delete("/documents/{doc_id}", response_model=ApiResponse[dict], summary="删除文档及其解析结果与原文")
async def delete_document(doc_id: str, service: DocumentServiceDep, repository: RepositoryDep) -> dict:
    _purge_document(service.get(doc_id), repository)
    return ok({"deleted": True, "doc_id": doc_id}, message="文档已删除")


@router.post(
    "/documents/batch-delete",
    response_model=ApiResponse[BatchDeleteResult],
    summary="批量删除文档及其解析结果与原文",
)
async def batch_delete_documents(payload: BatchDeleteRequest, repository: RepositoryDep) -> dict:
    deleted = 0
    missing: list[str] = []
    for doc_id in dict.fromkeys(payload.ids):
        record = repository.documents.try_get(doc_id)
        if record is None:
            missing.append(doc_id)
            continue
        _purge_document(record, repository)
        deleted += 1
    message = f"已删除 {deleted} 份文档" + (f"，{len(missing)} 份未找到" if missing else "")
    return ok(BatchDeleteResult(deleted=deleted, missing=missing), message=message)
