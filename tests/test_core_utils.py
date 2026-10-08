"""核心工具单测：JSON 容错解析、编码兼容、文件名安全化。"""
from __future__ import annotations

import pytest

from app.core.utils import (
    JsonExtractionError,
    decode_bytes,
    extract_json,
    normalize_whitespace,
    short_hash,
    slugify_filename,
)


class TestExtractJson:
    def test_plain_object(self) -> None:
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_block(self) -> None:
        text = '好的，结果如下：\n```json\n{"items": [1, 2]}\n```\n以上。'
        assert extract_json(text) == {"items": [1, 2]}

    def test_trailing_comma_and_chinese_quotes(self) -> None:
        text = '{"name": “张三”, "age": 18,}'
        assert extract_json(text) == {"name": "张三", "age": 18}

    def test_line_comments(self) -> None:
        text = '{\n// 注释\n"ok": true\n}'
        assert extract_json(text) == {"ok": True}

    def test_extract_from_noise(self) -> None:
        text = '前言 {"a": {"b": [1,2,3]}} 后记'
        assert extract_json(text) == {"a": {"b": [1, 2, 3]}}

    def test_array(self) -> None:
        assert extract_json("[1, 2, 3]") == [1, 2, 3]

    @pytest.mark.parametrize("text", ["", "   ", "完全不是 JSON 的一段话"])
    def test_invalid_raises(self, text: str) -> None:
        with pytest.raises(JsonExtractionError):
            extract_json(text)


class TestEncoding:
    def test_gbk_fallback(self) -> None:
        raw = "手机号必须为 11 位数字".encode("gb18030")
        text, encoding = decode_bytes(raw)
        assert "手机号" in text
        assert encoding == "gb18030"

    def test_utf8_first(self) -> None:
        text, encoding = decode_bytes("中文 UTF-8".encode("utf-8"))
        assert text == "中文 UTF-8"
        assert encoding == "utf-8"

    def test_never_crash_on_garbage(self) -> None:
        text, encoding = decode_bytes(b"\xff\xfe\x00\x01\x02")
        assert isinstance(text, str)
        assert encoding


class TestFilenameAndHash:
    def test_slugify_keeps_chinese(self) -> None:
        name = slugify_filename("订单系统 需求 v1.0.docx")
        assert "订单系统" in name
        assert " " not in name
        assert not name.endswith(".docx")

    def test_slugify_fallback(self) -> None:
        assert slugify_filename("///", fallback="cases") == "cases"

    def test_hash_is_stable(self) -> None:
        assert short_hash("a", "b") == short_hash("a", "b")
        assert short_hash("a", "b") != short_hash("b", "a")


def test_normalize_whitespace() -> None:
    assert normalize_whitespace("a\r\n\r\n\r\nb   \n") == "a\n\nb"