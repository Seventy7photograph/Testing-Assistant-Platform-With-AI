"""云端 OCR 通道（通用 HTTP 契约）。

各家 OCR 云服务的请求/响应格式都不一样，因此这里不假装统一，而是定义一份
**显式契约**，让接入方改两个配置就能对接自己那家：

请求：``POST {VISION_CLOUD_URL}``
  ``Content-Type: application/json``，请求体 ::

      {"image": "<base64>", "mime": "image/png", "hint": "..."}

响应（二选一，都支持）：
  1. ``application/json``：取 ``data[VISION_CLOUD_FIELD]``，默认字段名 ``text``；
  2. 纯文本：直接作为识别结果。

鉴权：配置了 ``VISION_CLOUD_KEY`` 时带上 ``Authorization: Bearer <key>``。

如果目标服务的契约不同（比如要求 multipart 上传），写一个
``ImageTextExtractor`` 子类注册进 VISION_REGISTRY 即可 —— 与其余插件一致。
"""
from __future__ import annotations

import base64
from typing import Any

import httpx

from app.core.exceptions import LLMError
from app.core.logging import get_logger
from app.core.utils import Timer, truncate
from app.vision.base import KIND_TEXT, ImageTextExtractor, ImageTextResult

logger = get_logger(__name__)


class CloudOcrExtractor(ImageTextExtractor):
    name = "cloud-ocr"
    label = "云端 OCR"
    kind = KIND_TEXT
    requires = "配置 VISION_CLOUD_URL（可选 VISION_CLOUD_KEY）"

    def __init__(
        self,
        *,
        url: str = "",
        api_key: str = "",
        field: str = "text",
        timeout: float = 60.0,
    ) -> None:
        self.url = (url or "").strip()
        self.api_key = (api_key or "").strip()
        self.field = (field or "text").strip() or "text"
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.url)

    @property
    def degraded_reason(self) -> str:
        return "" if self.available else self.requires

    async def extract(self, image: bytes, *, hint: str = "", filename: str = "") -> ImageTextResult:
        if not self.available:
            return ImageTextResult(extractor=self.name, warnings=[f"云端 OCR 不可用：{self.requires}"])
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "image": base64.b64encode(image).decode("ascii"),
            "mime": _sniff(image),
            "hint": truncate(hint, 200),
            "filename": filename,
        }
        with Timer() as timer:
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout, connect=10.0), follow_redirects=True
                ) as client:
                    response = await client.post(self.url, json=payload, headers=headers)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("云端 OCR 调用失败：%s", exc)
                return ImageTextResult(
                    extractor=self.name,
                    warnings=[f"云端 OCR 调用失败：{exc}"],
                    elapsed_ms=timer.elapsed_ms,
                )
        text = _extract_text(response, self.field)
        warnings: list[str] = []
        if not text:
            warnings.append("云端 OCR 未返回可用文本。")
        return ImageTextResult(
            text=text,
            extractor=self.name,
            kind=KIND_TEXT,
            warnings=warnings,
            elapsed_ms=timer.elapsed_ms,
        )


def _sniff(data: bytes) -> str:
    from app.vision.imaging import sniff_mime

    return sniff_mime(data)


def _extract_text(response: httpx.Response, field: str) -> str:
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        try:
            payload: Any = response.json()
        except ValueError:
            return response.text.strip()
        return _dig(payload, field)
    return response.text.strip()


def _dig(payload: Any, field: str) -> str:
    """从响应里取文本：依次尝试 ``data[field]`` / ``[field]`` / ``data`` / 顶层字符串。"""
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict) and field in data:
            return str(data[field]).strip()
        if field in payload:
            return str(payload[field]).strip()
        if isinstance(data, str):
            return data.strip()
    return ""


__all__ = ["CloudOcrExtractor"]
