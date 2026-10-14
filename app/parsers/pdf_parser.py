"""PDF 解析器（基于 pypdf + 可选 pypdfium2）。

三条路径，按可靠性依次兜底：

  1. **文本层**：pypdf 直接抽文字（绝大多数需求文档走这条）；
  2. **内嵌图**：抽取页面里的图片作为资产交给识别通道。文本页里的小图标/装饰
     通过字节数阈值过滤（见 ``MIN_IMAGE_BYTES``）—— 需求文档的正文配图通常有
     几十 KB，而 logo 只有几 KB，这是不依赖 Pillow 也能用的廉价判据；
  3. **整页渲染**：整页就是一张扫描图、而 pypdf 又抽不出内嵌图时，
     用 pypdfium2 把页面渲染成位图再交给 OCR。未安装 pypdfium2 时**不静默**：
     抛出带操作指引的 EmptyDocumentError。

关于版面还原：如需更强的排版还原，可在 requirements.txt 启用 pdfplumber 并新增
PdfplumberParser 注册到 PARSER_REGISTRY（接口保持不变）。
"""
from __future__ import annotations

import io

from app.core.exceptions import DocumentParseError, EmptyDocumentError
from app.core.logging import get_logger
from app.core.utils import normalize_whitespace
from app.parsers.base import (
    ASSET_PDF,
    ASSET_PDF_PAGE,
    DocumentParser,
    ParsedAsset,
    ParsedDocument,
)
from app.vision.imaging import extension_for

logger = get_logger(__name__)

try:  # pragma: no cover - 取决于运行环境
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    PDF_AVAILABLE = True
except ImportError:  # pragma: no cover
    PdfReader = None  # type: ignore[assignment]

    class PdfReadError(Exception):  # type: ignore[no-redef]
        """pypdf 未安装时的占位异常。"""

    PDF_AVAILABLE = False

#: 正文页里小于这个体积的图片按图标/装饰处理，不做识别（省额度也降噪）。
MIN_IMAGE_BYTES = 32 * 1024

#: 整页渲染的上限页数：再多的扫描页应交由使用者拆分后上传，避免一次调用打满额度。
MAX_RENDERED_PAGES = 30

#: 整页渲染的缩放倍率（约 150 DPI，足以看清正文小字）。
RENDER_SCALE = 2.0


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
            pages: list[str] = []
            assets: list[ParsedAsset] = []
            warnings: list[str] = []
            for number, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                blocks = [page_text]
                for image_data, mime, size_hint in extract_page_images(page, number, warnings):
                    if page_text.strip() and len(image_data) < MIN_IMAGE_BYTES:
                        # 有文本层说明这不是扫描页，小图基本是 logo/图标/分隔线。
                        continue
                    asset = ParsedAsset(
                        index=len(assets) + 1,
                        data=image_data,
                        mime=mime,
                        extension=extension_for(mime),
                        source=ASSET_PDF,
                        placeholder=f"[图片 {len(assets) + 1}]",
                        anchor=f"第 {number} 页",
                        width=size_hint[0],
                        height=size_hint[1],
                    )
                    assets.append(asset)
                    blocks.append(asset.placeholder)
                pages.append("\n".join(blocks))
            page_count = len(pages)
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
        if not text and not assets:
            rendered = render_pages_as_assets(data, page_count, warnings)
            assets.extend(rendered)
        if not text and not assets:
            raise EmptyDocumentError(
                "PDF 未抽取到任何文字，也没有可识别的图片（疑似扫描件）。"
                "安装 pypdfium2 后可整页渲染并交给 OCR 识别，或直接把页面截图作为图片上传。",
                detail={"filename": filename, "page_count": page_count},
            )
        if not text and assets:
            warnings.append(
                f"PDF 未抽取到文字，已把 {len(assets)} 页/张图片交给图片识别通道处理。"
            )
        return self._finalize(
            text,
            extension="pdf",
            page_count=page_count,
            metadata={"filename": filename},
            warnings=warnings,
            assets=assets,
        )


# --------------------------------------------------------------------------- #
# 内嵌图与整页渲染
# --------------------------------------------------------------------------- #


def extract_page_images(page, number: int, warnings: list[str]) -> list[tuple[bytes, str, tuple[int, int]]]:
    """取一页里的内嵌图片；返回 [(字节, mime, (宽, 高))]。"""
    try:
        images = list(page.images)
    except Exception as exc:  # noqa: BLE001 - pypdf 在畸形 PDF 上会抛多种异常
        warnings.append(f"第 {number} 页的内嵌图片读取失败：{exc}")
        return []

    collected: list[tuple[bytes, str, tuple[int, int]]] = []
    for image in images:
        data = getattr(image, "data", b"") or b""
        if not data:
            continue
        mime = guess_image_mime(image, data)
        collected.append((data, mime, image_size(image)))
    return collected


def guess_image_mime(image, data: bytes) -> str:
    from app.vision.imaging import sniff_mime

    name = (getattr(image, "name", "") or "").lower()
    for suffix, mime in (
        (".png", "image/png"),
        (".jpg", "image/jpeg"),
        (".jpeg", "image/jpeg"),
        (".bmp", "image/bmp"),
        (".tif", "image/tiff"),
        (".tiff", "image/tiff"),
        (".webp", "image/webp"),
    ):
        if name.endswith(suffix):
            return mime
    return sniff_mime(data)


def image_size(image) -> tuple[int, int]:
    """尽力取图片尺寸；取不到就返回 (0, 0)。"""
    try:
        pil_image = getattr(image, "image", None)
        if pil_image is not None:
            width, height = pil_image.size
            return int(width), int(height)
    except Exception:  # noqa: BLE001 - 尺寸只是优化项，取不到不影响主流程
        pass
    from app.vision.imaging import read_size

    return read_size(getattr(image, "data", b"") or b"")


def render_pages_as_assets(data: bytes, page_count: int, warnings: list[str]) -> list[ParsedAsset]:
    """用 pypdfium2 把整页渲染成位图资产（扫描件兜底路径）。"""
    try:
        import pypdfium2 as pdfium  # type: ignore[import-not-found]
    except ImportError:
        warnings.append(
            "未安装 pypdfium2，无法把扫描件整页渲染成图片交给 OCR。"
            "安装方式：pip install pypdfium2"
        )
        return []

    assets: list[ParsedAsset] = []
    try:
        document = pdfium.PdfDocument(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - pdfium 异常类型不稳定
        warnings.append(f"扫描件整页渲染失败：{exc}")
        return []
    try:
        limit = min(len(document), MAX_RENDERED_PAGES)
        if len(document) > limit:
            warnings.append(
                f"PDF 共 {len(document)} 页，整页渲染仅处理前 {limit} 页，其余页面请拆分后上传。"
            )
        for index in range(limit):
            try:
                bitmap = document[index].render(scale=RENDER_SCALE).to_pil()
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"第 {index + 1} 页渲染失败：{exc}")
                continue
            buffer = io.BytesIO()
            bitmap.save(buffer, format="PNG")
            assets.append(
                ParsedAsset(
                    index=len(assets) + 1,
                    data=buffer.getvalue(),
                    mime="image/png",
                    extension="png",
                    source=ASSET_PDF_PAGE,
                    placeholder=f"[图片 {len(assets) + 1}]",
                    anchor=f"第 {index + 1} 页整页",
                    width=bitmap.width,
                    height=bitmap.height,
                )
            )
    finally:
        close = getattr(document, "close", None)
        if callable(close):
            close()
    if assets:
        warnings.append(
            f"已把 {len(assets)} 页扫描内容渲染为图片（原文共 {page_count} 页），交给图片识别通道。"
        )
    return assets


__all__ = [
    "MAX_RENDERED_PAGES",
    "MIN_IMAGE_BYTES",
    "PdfParser",
    "extract_page_images",
    "render_pages_as_assets",
]
