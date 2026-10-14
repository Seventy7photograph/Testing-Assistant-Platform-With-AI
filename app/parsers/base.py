"""解析器抽象与统一结果对象。

V2.0 起解析器的产出分成两路：

  - ``text``：文本层（原有的东西）；
  - ``assets``：**图片资产**。解析器只负责把图片从文件里抠出来（docx 的内嵌图、
    PDF 的内嵌图或整页扫描、直接上传的图片），至于「怎么把图变成文字」交给
    app/vision 的识别通道 —— 这样解析器不必依赖任何 OCR 引擎，未装引擎时
    依然能正常解析纯文本文档。
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from app.core.exceptions import EmptyDocumentError
from app.core.utils import normalize_whitespace, short_hash

MIN_TEXT_LENGTH = 5

#: 图片资产来源。
ASSET_DOCX = "docx"
ASSET_PDF = "pdf"
ASSET_PDF_PAGE = "pdf-page"
ASSET_UPLOAD = "upload"


@dataclass(slots=True)
class ParsedAsset:
    """从文档中抠出来的一张图片。"""

    index: int
    data: bytes
    mime: str
    extension: str
    source: str
    #: 正文里的占位标记（如 ``[图片 1]``）：识别出的文字要回填到这个位置，
    #: 图片与上下文文字的相对顺序才不会丢。
    placeholder: str = ""
    #: 位置说明：docx 用邻近段落文字，PDF 用页码。
    anchor: str = ""
    width: int = 0
    height: int = 0
    checksum: str = ""
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.checksum and self.data:
            self.checksum = short_hash(len(self.data), self.data[:1024])

    @property
    def pixel_count(self) -> int:
        return self.width * self.height


@dataclass(slots=True)
class ParsedDocument:
    """解析结果：纯文本 + 过程元信息。"""

    text: str
    parser: str
    extension: str
    page_count: int | None = None
    table_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    #: 文档里抠出的图片（尚未识别）。
    assets: list[ParsedAsset] = field(default_factory=list)


class DocumentParser(abc.ABC):
    """文档解析器基类。"""

    name: str = "base"
    label: str = "基础解析器"
    extensions: tuple[str, ...] = ()

    def supports(self, extension: str) -> bool:
        return extension.lower().lstrip(".") in self.extensions

    @abc.abstractmethod
    def parse(self, data: bytes, *, filename: str = "") -> ParsedDocument:
        """把文件字节流解析为文本。实现方只需返回原始文本，由 _finalize 统一收尾。"""

    # ------------------------------------------------------------------ #
    def _finalize(
        self,
        text: str,
        *,
        extension: str,
        page_count: int | None = None,
        table_count: int = 0,
        metadata: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        assets: list[ParsedAsset] | None = None,
    ) -> ParsedDocument:
        """统一做空白归一化与"空文档"兜底校验。

        有图片资产时不再判空：扫描件 PDF、纯图片上传本来就抽不到文本层，
        这时真正的文字要等识别通道产出 —— 在这里报「空文档」会让 OCR 永远没机会执行。
        """
        normalized = normalize_whitespace(text)
        collected = list(assets or [])
        if len(normalized) < MIN_TEXT_LENGTH and not collected:
            raise EmptyDocumentError(
                "未能从文档中抽取到有效文本，请确认文件不是扫描件/图片，或改用文本粘贴方式提交需求。",
                detail={"parser": self.name, "extension": extension, "extracted_length": len(normalized)},
            )
        return ParsedDocument(
            text=normalized,
            parser=self.name,
            extension=extension,
            page_count=page_count,
            table_count=table_count,
            metadata=metadata or {},
            warnings=list(warnings or []),
            assets=collected,
        )
