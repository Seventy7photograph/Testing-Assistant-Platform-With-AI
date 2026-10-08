"""PDF 解析器（基于 pypdf）。

假设与限制（显式标注）：
  - pypdf 只能抽取「文本型 PDF」；扫描件/图片型 PDF 抽不出文字，
    此时会抛出 EmptyDocumentError 并提示改用 OCR（后续扩展点）。
  - 如需更好的排版还原，可在 requirements.txt 启用 pdfplumber 并新增
    PdfplumberParser 注册到 PARSER_REGISTRY（接口保持不变）。
"""
from __future__ import annotations

import io

from app.core.exceptions import DocumentParseError
from app.core.utils import normalize_whitespace
from app.parsers.base import DocumentParser, ParsedDocument

try:  # pragma: no cover - 取决于运行环境
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    PDF_AVAILABLE = True
except ImportError:  # pragma: no cover
    PdfReader = None  # type: ignore[assignment]

    class PdfReadError(Exception):  # type: ignore[no-redef]
        """pypdf 未安装时的占位异常。"""

    PDF_AVAILABLE = False


class PdfParser(DocumentParser):
    name = "pdf"
    label = "PDF 解析器"
    extensions = ("pdf",)

    def parse(self, data: bytes, *, filename: str = "") -> ParsedDocument:
        if not PDF_AVAILABLE:  # pragma: no cover
            raise DocumentParseError(
                "解析 .pdf 需要安装 pypdf，请执行：pip install pypdf",
                detail={"missing_dependency": "pypdf"},
            )

        try:
            reader = PdfReader(io.BytesIO(data))
            if getattr(reader, "is_encrypted", False):
                try:
                    reader.decrypt("")
                except Exception as exc:  # noqa: BLE001
                    raise DocumentParseError(
                        "PDF 已加密，请提供未加密文件。", detail={"filename": filename}
                    ) from exc
            pages = [(page.extract_text() or "") for page in reader.pages]
        except DocumentParseError:
            raise
        except PdfReadError as exc:
            raise DocumentParseError(
                f"PDF 解析失败，文件可能损坏：{exc}", detail={"filename": filename, "error": str(exc)}
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise DocumentParseError(
                f"PDF 解析异常：{exc}", detail={"filename": filename, "error": str(exc)}
            ) from exc

        text = normalize_whitespace("\n\n".join(pages))
        warnings: list[str] = []
        if not text:
            warnings.append("PDF 未抽取到文字，可能是扫描件，V1.0 暂不支持 OCR。")
        return self._finalize(
            text,
            extension="pdf",
            page_count=len(pages),
            metadata={"filename": filename},
            warnings=warnings,
        )