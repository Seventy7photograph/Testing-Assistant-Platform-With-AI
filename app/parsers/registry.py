"""解析器注册表与分发入口。"""
from __future__ import annotations

from pathlib import Path

from app.core.exceptions import UnsupportedFormatError
from app.core.registry import Registry
from app.parsers.base import DocumentParser, ParsedDocument
from app.parsers.docx_parser import DocxParser
from app.parsers.pdf_parser import PdfParser
from app.parsers.text_parser import TextParser

PARSER_REGISTRY: Registry[DocumentParser] = Registry("文档解析器")


def register_parser(parser: DocumentParser, *, override: bool = False) -> DocumentParser:
    """注册解析器实例（新增格式走这里）。"""
    return PARSER_REGISTRY.register(
        parser.name,
        parser,
        meta={"label": parser.label, "extensions": list(parser.extensions)},
        override=override,
    )


register_parser(TextParser())
register_parser(DocxParser())
register_parser(PdfParser())


def supported_extensions() -> list[str]:
    extensions: set[str] = set()
    for _, parser in PARSER_REGISTRY.items():
        extensions.update(parser.extensions)
    return sorted(extensions)


def get_extension(filename: str) -> str:
    return Path(filename or "").suffix.lower().lstrip(".")


def get_parser_for(filename: str) -> DocumentParser:
    """按扩展名选择解析器。"""
    extension = get_extension(filename)
    if not extension:
        raise UnsupportedFormatError(
            "无法识别文件类型（缺少扩展名）。" + _hint(),
            detail={"filename": filename, "supported": supported_extensions()},
        )
    for _, parser in PARSER_REGISTRY.items():
        if parser.supports(extension):
            return parser
    raise UnsupportedFormatError(
        f"暂不支持 .{extension} 格式。" + _hint(),
        detail={"filename": filename, "extension": extension, "supported": supported_extensions()},
    )


def parse_document(data: bytes, filename: str) -> ParsedDocument:
    """统一入口：按文件名选择解析器并解析。"""
    parser = get_parser_for(filename)
    return parser.parse(data, filename=filename)


def _hint() -> str:
    return f"当前支持：{', '.join('.' + ext for ext in supported_extensions())}；也可直接粘贴需求文本。"