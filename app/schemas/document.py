"""已上传文档的记录模型（元信息 + 抽取文本）。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.utils import now_iso
from app.schemas.requirement import ParseMeta


class DocumentRecord(BaseModel):
    doc_id: str
    filename: str
    extension: str
    size_bytes: int
    text: str = ""
    char_count: int = 0
    line_count: int = 0
    encoding: str = "utf-8"
    stored_path: str = ""
    parser: str = ""
    page_count: int | None = None
    table_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)

    def preview(self, limit: int = 500) -> str:
        from app.core.utils import truncate

        return truncate(self.text, limit)


class DocumentSummary(BaseModel):
    """上传接口返回体（不回传全文，避免响应体过大）。"""

    doc_id: str
    filename: str
    extension: str
    size_bytes: int
    char_count: int
    line_count: int
    encoding: str = "utf-8"
    parser: str
    page_count: int | None = None
    table_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    created_at: str = ""
    preview: str = ""
    #: 是否已经解析过结构化需求；列表页据此把「解析需求」换成「查看需求」。
    has_requirement: bool = False
    #: 已解析的需求条目数（未解析为 0）。
    requirement_items: int = 0
    #: 解析阶段的口径快照（哪个 provider / 模型、是否降级）；未解析为 None。
    #: 列表页据此把「这条需求是谁解析的」标出来，方便判断结果可信度。
    parse_meta: ParseMeta | None = None

    @classmethod
    def from_record(
        cls,
        record: DocumentRecord,
        *,
        has_requirement: bool = False,
        requirement_items: int = 0,
        parse_meta: ParseMeta | None = None,
    ) -> "DocumentSummary":
        return cls(
            doc_id=record.doc_id,
            filename=record.filename,
            extension=record.extension,
            size_bytes=record.size_bytes,
            char_count=record.char_count,
            line_count=record.line_count,
            encoding=record.encoding,
            parser=record.parser,
            page_count=record.page_count,
            table_count=record.table_count,
            warnings=record.warnings,
            created_at=record.created_at,
            preview=record.preview(),
            has_requirement=has_requirement,
            requirement_items=requirement_items,
            parse_meta=parse_meta,
        )
