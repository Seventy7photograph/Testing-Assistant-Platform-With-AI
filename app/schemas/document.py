"""已上传文档的记录模型（元信息 + 抽取文本）。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.utils import now_iso, truncate
from app.schemas.requirement import ParseMeta


class DocumentAsset(BaseModel):
    """文档里的一张图片及其识别情况（V2.0 多模态 OCR）。

    状态字段是刻意保留的：图片识别一定会有「跳过 / 无文字 / 通道不可用」这些
    非成功结局，把它们如实记下来，界面才能解释清楚每张图到底怎么了。
    """

    index: int = 0
    filename: str = ""
    mime: str = ""
    size_bytes: int = 0
    source: str = Field(default="", description="docx / pdf / pdf-page / upload")
    anchor: str = Field(default="", description="位置说明：邻近段落或页码")
    placeholder: str = Field(default="", description="正文里的占位标记")
    width: int = 0
    height: int = 0
    checksum: str = ""
    stored: bool = Field(default=False, description="图片是否已成功落盘（落盘失败仍可识别）")
    status: str = Field(
        default="pending",
        description="pending / recognized / empty / skipped / unavailable",
    )
    extractor: str = Field(default="", description="实际使用的识别通道，如 vlm:qwen-vl-max")
    kind: str = Field(default="", description="text / description / mixed / none")
    confidence: float | None = None
    reused_from: int = Field(default=0, description="内容重复时复用第几张图片的识别结果")
    text: str = Field(default="", description="识别出的文本/描述")
    message: str = Field(default="", description="状态说明：为什么跳过、失败原因、需注意什么")

    def brief(self, limit: int = 200) -> "DocumentAssetBrief":
        return DocumentAssetBrief(
            index=self.index,
            filename=self.filename,
            mime=self.mime,
            size_bytes=self.size_bytes,
            source=self.source,
            anchor=self.anchor,
            status=self.status,
            extractor=self.extractor,
            kind=self.kind,
            confidence=self.confidence,
            reused_from=self.reused_from,
            text_preview=truncate(self.text, limit),
            message=self.message,
        )


class DocumentAssetBrief(BaseModel):
    """图片的列表项视图：带预览、不带全文，避免列表响应随图片数膨胀。"""

    index: int = 0
    filename: str = ""
    mime: str = ""
    size_bytes: int = 0
    source: str = ""
    anchor: str = ""
    status: str = "pending"
    extractor: str = ""
    kind: str = ""
    confidence: float | None = None
    reused_from: int = 0
    text_preview: str = ""
    message: str = ""


class DocumentRecord(BaseModel):
    doc_id: str
    filename: str
    extension: str
    size_bytes: int
    text: str = ""
    #: 解析器产出的原文（图片识别结果回填**之前**）。重跑图片识别时从这里重建，
    #: 否则重复识别会把上次的结果再叠一遍，正文里出现两份一样的文字。
    text_base: str = ""
    char_count: int = 0
    line_count: int = 0
    encoding: str = "utf-8"
    stored_path: str = ""
    parser: str = ""
    page_count: int | None = None
    table_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    #: 解析阶段的告警快照。重跑图片识别时用它重建 warnings，
    #: 否则重复识别会把上次的图片告警一遍遍叠加。
    parser_warnings: list[str] = Field(default_factory=list)
    assets: list[DocumentAsset] = Field(
        default_factory=list, description="文档内的图片及识别情况（V2.0）"
    )
    external_source: str = ""
    external_id: str = ""
    external_url: str = ""
    external_version: str = ""
    external_status: str = ""
    sync_metadata: dict = Field(default_factory=dict)
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
    #: 图片识别概况：共发现多少张、成功识别多少张。
    image_count: int = 0
    image_recognized: int = 0
    images: list[DocumentAssetBrief] = Field(default_factory=list)
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
            image_count=len(record.assets),
            image_recognized=sum(1 for asset in record.assets if asset.status == "recognized"),
            images=[asset.brief() for asset in record.assets],
            created_at=record.created_at,
            preview=record.preview(),
            has_requirement=has_requirement,
            requirement_items=requirement_items,
            parse_meta=parse_meta,
        )
