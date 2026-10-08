"""文档解析层单测：格式分发、编码兼容、异常路径。"""
from __future__ import annotations

import io

import pytest

from app.core.exceptions import DocumentParseError, EmptyDocumentError, UnsupportedFormatError
from app.parsers.registry import get_parser_for, parse_document, supported_extensions
from tests.pdf_factory import make_minimal_pdf


def test_supported_extensions_cover_v1_formats() -> None:
    extensions = supported_extensions()
    for expected in ("docx", "pdf", "txt", "md"):
        assert expected in extensions


@pytest.mark.parametrize(
    ("filename", "expected_parser"),
    [("req.md", "text"), ("需求文档.txt", "text"), ("a.docx", "docx"), ("b.PDF", "pdf")],
)
def test_parser_dispatch(filename: str, expected_parser: str) -> None:
    assert get_parser_for(filename).name == expected_parser


def test_parse_markdown_keeps_structure() -> None:
    data = "# 标题\n\n## 子标题\n- 手机号：11位数字\n".encode("utf-8")
    parsed = parse_document(data, "req.md")
    assert "## 子标题" in parsed.text
    assert parsed.parser == "text"


def test_parse_gbk_txt_with_warning() -> None:
    parsed = parse_document("手机号必须为 11 位数字，必填".encode("gb18030"), "req.txt")
    assert "手机号" in parsed.text
    assert any("编码" in warning for warning in parsed.warnings)


def test_parse_docx_paragraphs_and_tables() -> None:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_heading("用户注册", level=1)
    document.add_paragraph("手机号必须唯一")
    table = document.add_table(rows=2, cols=3)
    for index, text in enumerate(["字段名", "类型", "必填"]):
        table.rows[0].cells[index].text = text
    for index, text in enumerate(["手机号", "字符串", "是"]):
        table.rows[1].cells[index].text = text
    buffer = io.BytesIO()
    document.save(buffer)

    parsed = parse_document(buffer.getvalue(), "req.docx")
    assert "# 用户注册" in parsed.text
    assert "字段名: 手机号" in parsed.text
    assert "必填: 是" in parsed.text
    assert parsed.table_count == 1


def test_parse_pdf_text() -> None:
    parsed = parse_document(make_minimal_pdf(), "req.pdf")
    assert "Requirement" in parsed.text
    assert parsed.page_count == 1


def test_unsupported_extension() -> None:
    with pytest.raises(UnsupportedFormatError) as excinfo:
        parse_document(b"data", "req.xlsx")
    assert "xlsx" in str(excinfo.value.message)
    assert excinfo.value.http_status == 415


def test_missing_extension() -> None:
    with pytest.raises(UnsupportedFormatError):
        parse_document(b"data", "noextension")


def test_empty_document_raises() -> None:
    with pytest.raises(EmptyDocumentError):
        parse_document(b"   \n  \n", "req.txt")


def test_corrupted_docx_raises_parse_error() -> None:
    with pytest.raises(DocumentParseError):
        parse_document(b"not a real docx file", "req.docx")