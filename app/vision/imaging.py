"""图片预处理：格式嗅探、下采样与体积控制。

为什么必须做这一步：一份 40 页的 PRD 能塞进几十张图，原图直传会把 token 与费用
烧穿；部分多模态端点又只接受 png/jpeg/webp，BMP/TIFF 直接传会 400。
因此统一在这里「归一格式 + 限制长边 + 控制体积」，下游（VLM / OCR）拿到的是
已经规整过的字节流。

Pillow 缺失时不报错：能原样传就原样传，并在 warnings 里写明「未做下采样」，
把「为什么这张图特别贵/特别慢」的原因留在数据里。
"""
from __future__ import annotations

import io

from app.core.logging import get_logger

logger = get_logger(__name__)

#: 默认长边上限：多数多模态端点在此分辨率下仍能读清界面文字与表格。
DEFAULT_MAX_SIDE = 1600

#: 默认单图字节上限（base64 之后还会膨胀约 1/3）。
DEFAULT_MAX_BYTES = 4 * 1024 * 1024

MIME_BY_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)

EXTENSION_BY_MIME: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/bmp": "bmp",
    "image/tiff": "tiff",
    "image/webp": "webp",
}

#: 这些格式可以直接传给多模态端点，无需转码。
WEB_SAFE_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})


def sniff_mime(data: bytes) -> str:
    """按魔数判断图片类型（不依赖 Pillow，也不需要文件扩展名）。"""
    for magic, mime in MIME_BY_MAGIC:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def extension_for(mime: str) -> str:
    return EXTENSION_BY_MIME.get(mime, "bin")


def pillow_available() -> bool:
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    return True


def read_size(data: bytes) -> tuple[int, int]:
    """只读图片头拿到 (宽, 高)，不解码像素；取不到返回 (0, 0)。

    为什么值得读：没有尺寸就没法判断「这是一张 32×32 的图标还是 1200×800 的原型图」，
    于是「跳过小图标」这条规则对 Word 内嵌图与直传图片完全失效 —— 文档里插了 20 个
    图标就要白跑 20 次识别。Pillow 读头是毫秒级且不占内存。
    """
    if not pillow_available():
        return 0, 0
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            return int(image.width), int(image.height)
    except Exception:  # noqa: BLE001 - 尺寸只是优化项，取不到不影响主流程
        return 0, 0


def probe_image(text: str = "TEST 123") -> bytes:
    """生成一张带文字的探针图片：用于验证识别通道是否真的能工作。

    刻意画上文字而不是给一张纯色图：纯色图即使通道「通了」也识别不出东西，
    探针只会给出一句没信息量的「成功」。Pillow 不可用时退化为 1×1 图片，
    此时探针只能证明「请求发出去了」，这一点会在结果说明里写清楚。
    """
    if not pillow_available():
        return bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000a49444154789c6300010000050001"
            "0d0a2db40000000049454e44ae426082"
        )
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (360, 90), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([4, 4, 355, 85], outline="black", width=2)
    draw.text((22, 34), text, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def prepare_image(
    data: bytes,
    *,
    max_side: int = DEFAULT_MAX_SIDE,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> tuple[bytes, str, list[str]]:
    """归一化图片：返回 (字节, mime, warnings)。"""
    warnings: list[str] = []
    mime = sniff_mime(data)
    if mime == "application/octet-stream":
        warnings.append("无法识别图片格式（既不是 png/jpeg，也不是 gif/bmp/tiff/webp）。")
        return data, mime, warnings

    if not pillow_available():
        if not mime in WEB_SAFE_MIMES:
            warnings.append(
                f"图片格式为 {mime}，部分多模态端点不接受该格式；"
                "安装 pillow 可自动转换为 png 后再提交。"
            )
        if len(data) > max_bytes:
            warnings.append(
                f"图片体积 {len(data) / 1024 / 1024:.1f}MB 超过建议上限 "
                f"{max_bytes / 1024 / 1024:.1f}MB；安装 pillow 可自动压缩。"
            )
        return data, mime, warnings

    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - pillow_available 已经判过
        return data, mime, warnings

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            converted = _convert(image)
            resized = _resize(converted, max_side)
            encoded, out_mime = _encode(resized, max_bytes)
            if resized is not converted:
                resized.close()
            if converted is not image:
                converted.close()
            return encoded, out_mime, warnings
    except Exception as exc:  # noqa: BLE001 - Pillow 异常类型很多，统一兜底
        logger.warning("图片预处理失败，改为原样使用：%s", exc)
        warnings.append(f"图片预处理失败（{exc}），已按原图提交。")
        return data, mime, warnings


def _convert(image):
    """统一为 RGB/RGBA：JPEG 不支持透明通道，P/CMYK 等模式需转换。"""
    from PIL import Image

    if image.mode in ("RGB", "RGBA"):
        return image
    if image.mode == "P" and "transparency" in image.info:
        return image.convert("RGBA")
    if image.mode in ("LA", "L", "P"):
        return image.convert("RGB")
    return image.convert("RGB")


def _resize(image, max_side: int):
    from PIL import Image

    longest = max(image.size)
    if max_side <= 0 or longest <= max_side:
        return image
    ratio = max_side / float(longest)
    target = (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
    return image.resize(target, Image.LANCZOS)


def _encode(image, max_bytes: int) -> tuple[bytes, str]:
    """优先 PNG（界面截图文字更清晰），超限再降为 JPEG。"""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    payload = buffer.getvalue()
    if len(payload) <= max_bytes:
        return payload, "image/png"

    rgb = image.convert("RGB")
    buffer = io.BytesIO()
    quality = 85
    while quality >= 45:
        buffer.seek(0)
        buffer.truncate()
        rgb.save(buffer, format="JPEG", quality=quality, optimize=True)
        payload = buffer.getvalue()
        if len(payload) <= max_bytes:
            return payload, "image/jpeg"
        quality -= 15
    return payload, "image/jpeg"


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_SIDE",
    "EXTENSION_BY_MIME",
    "WEB_SAFE_MIMES",
    "extension_for",
    "pillow_available",
    "prepare_image",
    "probe_image",
    "read_size",
    "sniff_mime",
]
