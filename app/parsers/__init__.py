"""文档解析层：把 docx/pdf/txt/md 统一转为纯文本。

扩展点：后续接入 OCR（扫描件 PDF）或 Excel 需求清单时，
新增一个 DocumentParser 子类并注册即可，上传接口无需改动。
"""
from app.parsers.base import DocumentParser, ParsedDocument
from app.parsers.registry import (
    PARSER_REGISTRY,
    get_parser_for,
    parse_document,
    register_parser,
    supported_extensions,
)

__all__ = [
    "DocumentParser",
    "ParsedDocument",
    "PARSER_REGISTRY",
    "get_parser_for",
    "parse_document",
    "register_parser",
    "supported_extensions",
]