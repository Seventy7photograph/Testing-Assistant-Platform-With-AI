"""离线假识别通道：给测试、演示与「先跑通链路再配真引擎」用。

与 LLM 侧的 FakeProvider 同一个定位：**确定性地**产出一段可辨认的文本，
让「上传含图文档 -> 图片占位 -> 回填 -> 结构化需求」整条链路在无网络、
无 API Key、无 OCR 引擎的环境里也能端到端验证。

它不假装自己识得懂图：输出里带「模拟识别」前缀，避免被误当成真实结果。
"""
from __future__ import annotations

from app.vision.base import KIND_TEXT, ImageTextExtractor, ImageTextResult

PREFIX = "[模拟识别]"


class FakeVisionExtractor(ImageTextExtractor):
    name = "fake"
    label = "离线假识别（演示 / 测试）"
    kind = KIND_TEXT
    requires = "无（不联网、不调用任何模型）"

    def __init__(self, *, text: str = "", kind: str = KIND_TEXT) -> None:
        self._text = text
        self.kind = kind

    @property
    def available(self) -> bool:
        return True

    async def extract(self, image: bytes, *, hint: str = "", filename: str = "") -> ImageTextResult:
        text = self._text or f"{PREFIX} 图片 {filename or '未命名'}（{len(image)} 字节）"
        if hint:
            text = f"{text}\n{hint}"
        return ImageTextResult(
            text=text,
            extractor=self.name,
            kind=self.kind,
            confidence=0.99,
        )


__all__ = ["PREFIX", "FakeVisionExtractor"]
