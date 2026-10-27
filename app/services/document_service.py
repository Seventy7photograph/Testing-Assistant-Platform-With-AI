"""文档服务：上传校验 + 解析 + 图片识别 + 落盘。"""
from __future__ import annotations

import re
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    DocumentParseError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedFormatError,
    VisionUnavailableError,
)
from app.core.logging import get_logger
from app.core.utils import new_id
from app.parsers.base import ParsedAsset
from app.parsers.registry import get_extension, get_parser_for, supported_extensions
from app.repository import Repository, get_repository
from app.schemas.document import DocumentRecord
from app.services.image_enrichment_service import ImageEnrichmentService
from app.vision.registry import build_vision_extractor

logger = get_logger(__name__)

_INVALID_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class DocumentService:
    def __init__(self, settings: Settings | None = None, repository: Repository | None = None) -> None:
        self.repository = repository or get_repository()
        self.platform_settings = settings or get_settings()
        # 项目请求传入的是全局 Settings + 项目 Repository；文件目录必须跟随
        # Repository 的项目分区，否则记录隔离了、原文仍落在全局 uploads/。
        self.settings = repository.settings if repository is not None else self.platform_settings

    # ------------------------------------------------------------------ #
    def save_text(self, *, text: str, title: str = "粘贴的需求文本") -> DocumentRecord:
        """把粘贴文本保存为可追溯的文档记录。

        粘贴入口过去只保存需求模型，导致用例集详情能追溯需求，文档库却看不到来源。
        这里使用与上传入口相同的 ``DocumentRecord`` 契约，并落一份 UTF-8 原文，
        因此文档详情、下载、删除与图片能力都能沿用现有流程。
        """
        content = text or ""
        if not content.strip():
            raise DocumentParseError("粘贴的需求文本为空，无法保存到文档库。")
        self._check_quota()

        doc_id = new_id("DOC-")
        data = content.encode("utf-8")
        filename = self._text_filename(title)
        stored_path = self._store_raw(doc_id, "txt", data)
        record = DocumentRecord(
            doc_id=doc_id,
            filename=filename,
            extension="txt",
            size_bytes=len(data),
            text=content,
            text_base=content,
            char_count=len(content),
            line_count=content.count("\n") + 1,
            encoding="utf-8",
            stored_path=str(stored_path),
            parser="pasted_text",
        )
        self.repository.documents.save(record)
        self._index_document(record)
        logger.info(
            "粘贴文本已入库：%s（%s，%d 字符）",
            doc_id,
            filename,
            record.char_count,
        )
        return record

    # ------------------------------------------------------------------ #
    async def save_and_parse(self, *, filename: str, data: bytes) -> DocumentRecord:
        """校验 -> 解析 -> 图片识别 -> 保存原文与解析结果。

        异常路径（均有明确提示）：
          - 文件过大            -> PayloadTooLargeError (413)
          - 扩展名不支持/缺失    -> UnsupportedFormatError (415)
          - 解析失败/空文档      -> DocumentParseError (422)

        图片识别**不会**让解析失败：识别通道不可用或某张图识别不出，都只是
        ``warnings`` 与资产状态里的一条记录 —— 一份文档里夹了张图，不该让整份
        需求解析报错。
        """
        if not filename:
            raise UnsupportedFormatError("上传文件缺少文件名，无法识别格式。")
        self._check_quota()

        size = len(data)
        if size == 0:
            raise DocumentParseError("上传文件为空，请重新选择文件。", detail={"filename": filename})
        if size > self.settings.max_upload_size_bytes:
            raise PayloadTooLargeError(
                f"文件大小 {size / 1024 / 1024:.2f}MB 超过限制 {self.settings.max_upload_size_mb}MB。",
                detail={"filename": filename, "size_bytes": size, "limit_mb": self.settings.max_upload_size_mb},
            )

        extension = get_extension(filename)
        parser = get_parser_for(filename)  # 不支持的格式在此抛出

        try:
            parsed = parser.parse(data, filename=filename)
        except (DocumentParseError, UnsupportedFormatError):
            raise
        except Exception as exc:  # noqa: BLE001 - 第三方解析库异常类型不稳定，统一兜底
            logger.exception("文档解析失败：%s", filename)
            raise DocumentParseError(
                f"文档解析失败：{exc}。可尝试另存为 .txt/.md 后重新上传。",
                detail={"filename": filename, "parser": parser.name, "error": str(exc)},
            ) from exc

        doc_id = new_id("DOC-")
        stored_path = self._store_raw(doc_id, extension, data)

        outcome = await ImageEnrichmentService(self.settings).enrich(doc_id=doc_id, parsed=parsed)
        parser_warnings = list(parsed.warnings)
        warnings = [*parser_warnings, *outcome.warnings]
        record = DocumentRecord(
            doc_id=doc_id,
            filename=filename,
            extension=extension,
            size_bytes=size,
            text=outcome.text,
            text_base=parsed.text,
            char_count=len(outcome.text),
            line_count=outcome.text.count("\n") + 1,
            encoding=str(parsed.metadata.get("encoding", "utf-8")),
            stored_path=str(stored_path),
            parser=parsed.parser,
            page_count=parsed.page_count,
            table_count=parsed.table_count,
            warnings=warnings,
            parser_warnings=parser_warnings,
            assets=outcome.assets,
        )
        self.repository.documents.save(record)
        self._index_document(record)
        logger.info(
            "文档已入库：%s（%s，%d 字符，解析器=%s，图片 %d 张/识别 %d 张）",
            doc_id,
            filename,
            record.char_count,
            parsed.parser,
            outcome.image_count,
            outcome.recognized,
        )
        return record

    # ------------------------------------------------------------------ #
    async def recognize_images(self, doc_id: str) -> DocumentRecord:
        """对已入库文档**重新识别**全部图片（换了识别通道、或首次因超限被跳过时用）。

        重建口径是 ``text_base``（解析器原文）而不是上次的结果：否则重复识别会把
        上一次的文字再叠一次，正文里出现两份一样的段落。
        """
        record = self.repository.documents.get(doc_id)
        if not record.assets:
            raise NotFoundError(
                f"「{record.filename}」里没有图片，无需识别。",
                detail={"doc_id": doc_id},
            )
        extractor = build_vision_extractor(self.settings)
        if not extractor.available:
            raise VisionUnavailableError(
                "当前没有可用的图片识别通道，无法重新识别。"
                + (extractor.degraded_reason or ""),
                detail={"doc_id": doc_id, "vision_provider": self.settings.vision_provider},
            )

        reloaded = self._reload_assets(record)
        if not reloaded:
            raise NotFoundError(
                f"「{record.filename}」的图片文件已不在存储中，无法重新识别。请重新上传该文档。",
                detail={"doc_id": doc_id},
            )

        from app.parsers.base import ParsedDocument

        parsed = ParsedDocument(
            text=record.text_base or "",
            parser=record.parser,
            extension=record.extension,
            page_count=record.page_count,
            table_count=record.table_count,
            warnings=list(record.parser_warnings),
            assets=reloaded,
        )
        outcome = await ImageEnrichmentService(self.settings, extractor).enrich(
            doc_id=doc_id, parsed=parsed
        )
        record.text = outcome.text
        record.char_count = len(outcome.text)
        record.line_count = outcome.text.count("\n") + 1
        record.assets = outcome.assets
        record.warnings = [*record.parser_warnings, *outcome.warnings]
        self.repository.documents.save(record)
        self._index_document(record)
        logger.info(
            "图片已重新识别：%s（识别 %d/%d 张）", doc_id, outcome.recognized, outcome.image_count
        )
        return record

    def _reload_assets(self, record: DocumentRecord) -> list[ParsedAsset]:
        assets: list[ParsedAsset] = []
        directory = self.settings.asset_dir / record.doc_id
        for asset in record.assets:
            path = directory / asset.filename
            try:
                data = path.read_bytes()
            except OSError:
                continue
            assets.append(
                ParsedAsset(
                    index=asset.index,
                    data=data,
                    mime=asset.mime,
                    extension=asset.filename.rsplit(".", 1)[-1],
                    source=asset.source,
                    placeholder=asset.placeholder,
                    anchor=asset.anchor,
                    width=asset.width,
                    height=asset.height,
                    checksum=asset.checksum,
                )
            )
        return assets

    def get(self, doc_id: str) -> DocumentRecord:
        return self.repository.documents.get(doc_id)

    def list_recent(self, limit: int = 20) -> list[DocumentRecord]:
        return self.repository.documents.list_recent(limit)

    def supported_extensions(self) -> list[str]:
        return supported_extensions()

    # ------------------------------------------------------------------ #
    @staticmethod
    def _text_filename(title: str) -> str:
        stem = _INVALID_FILENAME_RE.sub("_", (title or "").strip()).strip(" ._")
        if not stem:
            stem = "粘贴的需求文本"
        if stem.lower().endswith(".txt"):
            stem = stem[:-4].rstrip(" ._") or "粘贴的需求文本"
        return f"{stem[:80]}.txt"

    def _store_raw(self, doc_id: str, extension: str, data: bytes) -> Path:
        """保存原始文件，便于问题回溯（失败不影响主流程）。"""
        suffix = f".{extension}" if extension else ""
        path = self.settings.upload_dir / f"{doc_id}{suffix}"
        try:
            path.write_bytes(data)
        except OSError as exc:
            logger.warning("原始文件保存失败（不影响解析结果）：%s", exc)
            return Path("")
        return path

    def _index_document(self, record: DocumentRecord) -> None:
        """知识索引是建议层，失败不能阻断主业务写入。"""
        try:
            from app.knowledge.indexer import KnowledgeService

            KnowledgeService(self.settings, self.repository).index_document(record)
        except Exception as exc:  # noqa: BLE001
            logger.warning("文档知识索引更新失败（不影响文档保存）：%s", exc)

    def _check_quota(self) -> None:
        from app.core.context import get_current_project_id
        from app.services.project_service import ProjectService

        project_id = get_current_project_id()
        if not project_id:
            return
        service = ProjectService(self.platform_settings)
        project = service.get(project_id)
        service.check_quota(project, resource="documents", current=self.repository.documents.count())
