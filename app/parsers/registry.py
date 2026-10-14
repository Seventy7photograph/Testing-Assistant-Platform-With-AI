"""解析器注册表与分发入口。"""
from __future__ import annotations

from pathlib import Path

from app.core.exceptions import UnsupportedFormatError
from app.core.registry import Registry
from app.parsers.base import DocumentParser, ParsedDocument
from app.parsers.docx_parser import DocxParser
from app.parsers.excel_parser import ExcelParser
from app.parsers.image_parser import ImageParser
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
# V2.0 S7：Excel 需求清单与直接上传的图片。
register_parser(ExcelParser())
register_parser(ImageParser())

#: 已知但故意不支持、且能给出明确替代方案的扩展名 -> 提示语。
_KNOWN_UNSUPPORTED: dict[str, str] = {
    "xls": "旧版 Excel（.xls）请先用 Excel「另存为」.xlsx 后重新上传。",
    "doc": "旧版 Word（.doc）请先另存为 .docx 后重新上传。",
    "ppt": "演示文稿不是需求文档；请把需求内容整理为 .docx/.pdf/.xlsx 或直接粘贴文本。",
    "pptx": "演示文稿不是需求文档；请把需求内容整理为 .docx/.pdf/.xlsx 或直接粘贴文本。",
    "zip": "压缩包请先解压，再逐个上传其中的需求文档。",
}


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
    if extension in _KNOWN_UNSUPPORTED:
        raise UnsupportedFormatError(
            f"暂不支持 .{extension} 格式。" + _KNOWN_UNSUPPORTED[extension],
            detail={"filename": filename, "extension": extension, "supported": supported_extensions()},
        )
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
