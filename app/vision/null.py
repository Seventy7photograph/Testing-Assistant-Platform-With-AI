"""未配置识别通道时的显式占位实现。

刻意"什么都不做"而不是"悄悄跳过"：调用方会拿到明确的 warnings，
于是可以在文档告警、界面提示里如实告诉使用者「这几张图没被识别、原因是什么、
该怎么做」，而不是让人以为图片已经被读过了。
"""
from __future__ import annotations

from app.vision.base import KIND_NONE, ImageTextExtractor, ImageTextResult


class NullExtractor(ImageTextExtractor):
    name = "none"
    label = "未启用图片识别"
    kind = KIND_NONE
    requires = "配置 VISION_PROVIDER（多模态模型）或安装本地 OCR 引擎"

    def __init__(self, reason: str = "") -> None:
        self._reason = reason or self.requires

    @property
    def available(self) -> bool:
        return False

    @property
    def degraded_reason(self) -> str:
        return self._reason

    async def extract(self, image: bytes, *, hint: str = "", filename: str = "") -> ImageTextResult:
        return ImageTextResult(
            extractor=self.name,
            kind=KIND_NONE,
            warnings=[f"该图片未被识别：{self._reason}"],
        )


__all__ = ["NullExtractor"]
