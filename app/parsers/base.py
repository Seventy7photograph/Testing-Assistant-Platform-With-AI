"""解析器抽象与统一结果对象。"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from app.core.exceptions import EmptyDocumentError
from app.core.utils import normalize_whitespace

MIN_TEXT_LENGTH = 5


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
    ) -> ParsedDocument:
        """统一做空白归一化与"空文档"兜底校验。"""
        normalized = normalize_whitespace(text)
        if len(normalized) < MIN_TEXT_LENGTH:
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
        )