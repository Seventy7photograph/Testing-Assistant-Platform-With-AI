"""纯文本 / Markdown / CSV / JSON 解析器。

中文需求文档常见 GBK 编码，这里通过 decode_bytes 做多编码兼容。
"""
from __future__ import annotations

from app.core.utils import decode_bytes
from app.parsers.base import DocumentParser, ParsedDocument


class TextParser(DocumentParser):
    name = "text"
    label = "文本解析器"
    extensions = ("txt", "md", "markdown", "csv", "json", "log", "text")

    def parse(self, data: bytes, *, filename: str = "") -> ParsedDocument:
        text, encoding = decode_bytes(data)
        warnings: list[str] = []
        if encoding not in ("utf-8",):
            warnings.append(f"文件未使用 UTF-8 编码，已按 {encoding} 解码，请确认中文无乱码。")
        return self._finalize(
            text,
            extension=self._extension(filename),
            metadata={"encoding": encoding, "filename": filename},
            warnings=warnings,
        )

    def _extension(self, filename: str) -> str:
        if "." in filename:
            return filename.rsplit(".", 1)[1].lower()
        return "txt"