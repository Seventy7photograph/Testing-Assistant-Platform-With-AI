"""文档服务：上传校验 + 解析 + 落盘。"""
from __future__ import annotations

from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.exceptions import DocumentParseError, PayloadTooLargeError, UnsupportedFormatError
from app.core.logging import get_logger
from app.core.utils import new_id
from app.parsers.registry import get_extension, get_parser_for, supported_extensions
from app.repository import Repository, get_repository
from app.schemas.document import DocumentRecord

logger = get_logger(__name__)


class DocumentService:
    def __init__(self, settings: Settings | None = None, repository: Repository | None = None) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or get_repository()

    # ------------------------------------------------------------------ #
    def save_and_parse(self, *, filename: str, data: bytes) -> DocumentRecord:
        """校验 -> 解析 -> 保存原文与解析结果。

        异常路径（均有明确提示）：
          - 文件过大            -> PayloadTooLargeError (413)
          - 扩展名不支持/缺失    -> UnsupportedFormatError (415)
          - 解析失败/空文档      -> DocumentParseError (422)
        """
        if not filename:
            raise UnsupportedFormatError("上传文件缺少文件名，无法识别格式。")

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

        record = DocumentRecord(
            doc_id=doc_id,
            filename=filename,
            extension=extension,
            size_bytes=size,
            text=parsed.text,
            char_count=len(parsed.text),
            line_count=parsed.text.count("\n") + 1,
            encoding=str(parsed.metadata.get("encoding", "utf-8")),
            stored_path=str(stored_path),
            parser=parsed.parser,
            page_count=parsed.page_count,
            table_count=parsed.table_count,
            warnings=parsed.warnings,
        )
        self.repository.documents.save(record)
        logger.info(
            "文档已入库：%s（%s，%d 字符，解析器=%s）", doc_id, filename, record.char_count, parsed.parser
        )
        return record

    def get(self, doc_id: str) -> DocumentRecord:
        return self.repository.documents.get(doc_id)

    def list_recent(self, limit: int = 20) -> list[DocumentRecord]:
        return self.repository.documents.list_recent(limit)

    def supported_extensions(self) -> list[str]:
        return supported_extensions()

    # ------------------------------------------------------------------ #
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