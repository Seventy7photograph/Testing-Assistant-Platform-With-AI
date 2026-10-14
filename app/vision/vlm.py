"""多模态模型通道：把图片交给「能看图的模型」转成文字或结构化描述。

实现上直接复用 :class:`OpenAICompatibleProvider` —— 多模态请求与纯文本请求走的是
同一个 ``/chat/completions``，区别只在 ``content`` 是内容数组而不是字符串。
复用的好处是超时、重试、错误提示、空正文诊断（思考模式吃满预算等）全部继承，
不需要为「看图」再维护一套 HTTP 逻辑。

三种输出形态（``VISION_MODE``）：

  - ``text``：只要图里的文字。表格截图、条款截图走这条，产物可参与规则解析；
  - ``describe``：要模型描述界面/流程要素。原型图、流程图走这条 —— 这类图 OCR
    只能抠出零散标签，语义必须靠模型读；
  - ``both``：两者都要。产物标记为 mixed，**不参与规则解析**（见 base.py 的说明）。
"""
from __future__ import annotations

import base64
from typing import Any

from app.core.config import Settings
from app.core.exceptions import LLMError
from app.core.logging import get_logger
from app.core.utils import Timer, truncate
from app.llm.base import LLMMessage, user
from app.llm.openai_compatible import OpenAICompatibleProvider
from app.vision.base import KIND_DESCRIPTION, KIND_MIXED, KIND_TEXT, ImageTextExtractor, ImageTextResult
from app.vision.imaging import DEFAULT_MAX_BYTES, DEFAULT_MAX_SIDE, prepare_image

logger = get_logger(__name__)

MODE_TEXT = "text"
MODE_DESCRIBE = "describe"
MODE_BOTH = "both"

MODE_KINDS: dict[str, str] = {
    MODE_TEXT: KIND_TEXT,
    MODE_DESCRIBE: KIND_DESCRIPTION,
    MODE_BOTH: KIND_MIXED,
}

PROMPTS: dict[str, str] = {
    MODE_TEXT: (
        "请只输出这张图片中出现的文字。要求：\n"
        "1. 保持原有阅读顺序；标题、正文、表格分别用换行分隔，表格按「表头: 值」逐行输出；\n"
        "2. 不要解释、不要总结、不要补充图中没有出现的内容；\n"
        "3. 图片里没有文字时，只回复「（无文字）」。"
    ),
    MODE_DESCRIBE: (
        "请用中文描述这张图片的内容与结构。要求：\n"
        "1. 说明这是什么类型的图（界面原型 / 流程图 / 表格 / 架构图 / 其他）；\n"
        "2. 列出可见的关键要素、字段、按钮、分支与标注；\n"
        "3. 只描述看得见的内容，不要推断业务规则、不要补全未出现的信息；\n"
        "4. 控制在 400 字以内。"
    ),
    MODE_BOTH: (
        "请分两段输出：\n"
        "第一段以「[文字]」开头，逐行输出图片中可见的文字（保持顺序，表格按「表头: 值」输出）；\n"
        "第二段以「[描述]」开头，用中文描述图片的类型、界面/流程要素与标注，控制在 300 字以内。\n"
        "只写看得见的内容，不要推断业务规则、不要补全未出现的信息。"
    ),
}


class VisionLlmExtractor(ImageTextExtractor):
    name = "vlm"
    label = "多模态模型"
    requires = "配置 VISION_API_KEY（或复用 LLM_API_KEY）与支持图片输入的 VISION_MODEL"

    def __init__(
        self,
        settings: Settings,
        *,
        mode: str = MODE_TEXT,
        max_side: int = DEFAULT_MAX_SIDE,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        self.mode = mode if mode in PROMPTS else MODE_TEXT
        self.kind = MODE_KINDS[self.mode]
        self.max_side = max_side
        self.max_bytes = max_bytes
        self._provider = OpenAICompatibleProvider(settings)
        self._model = self._provider.model

    # ------------------------------------------------------------------ #
    @property
    def available(self) -> bool:
        return self._provider.available

    @property
    def degraded_reason(self) -> str:
        return self._provider.degraded_reason or self.requires

    @property
    def model(self) -> str:
        return self._model

    # ------------------------------------------------------------------ #
    async def extract(self, image: bytes, *, hint: str = "", filename: str = "") -> ImageTextResult:
        if not self.available:
            return ImageTextResult(extractor=self.name, warnings=[f"多模态模型不可用：{self.degraded_reason}"])

        payload, mime, warnings = prepare_image(image, max_side=self.max_side, max_bytes=self.max_bytes)
        if mime == "application/octet-stream":
            return ImageTextResult(
                extractor=self.name,
                warnings=[*warnings, "无法识别的图片格式，已跳过该图片。"],
            )

        messages: list[LLMMessage] = [user(self._content(payload, mime, hint, filename))]
        with Timer() as timer:
            try:
                response = await self._provider.complete(messages, temperature=0.0)
            except LLMError as exc:
                logger.warning("多模态识别失败：%s", exc.message)
                return ImageTextResult(
                    extractor=f"vlm:{self._model}",
                    warnings=[f"多模态识别失败（{exc.code}）：{exc.message}"],
                    elapsed_ms=timer.elapsed_ms,
                )

        text = clean_vision_text(response.content)
        if not text:
            warnings.append("多模态模型没有返回可用的图片内容。")
        return ImageTextResult(
            text=text,
            extractor=f"vlm:{response.model or self._model}",
            kind=self.kind,
            warnings=warnings,
            elapsed_ms=timer.elapsed_ms,
        )

    # ------------------------------------------------------------------ #
    def _content(self, data: bytes, mime: str, hint: str, filename: str) -> list[dict[str, Any]]:
        prompt = PROMPTS[self.mode]
        if hint:
            prompt += f"\n\n补充上下文（仅供定位，不要据此编造内容）：{truncate(hint, 200)}"
        if filename:
            prompt += f"\n图片文件名：{filename}"
        encoded = base64.b64encode(data).decode("ascii")
        return [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
        ]


def clean_vision_text(raw: str) -> str:
    """清掉模型爱加的 Markdown 代码围栏与「（无文字）」这类空答案。"""
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[-1].strip().startswith("```"):
            text = "\n".join(lines[1:-1]).strip()
        else:
            text = "\n".join(lines[1:]).strip()
    if text in {"（无文字）", "(无文字)", "无文字", "无"}:
        return ""
    return text


__all__ = [
    "MODE_BOTH",
    "MODE_DESCRIBE",
    "MODE_TEXT",
    "PROMPTS",
    "VisionLlmExtractor",
    "clean_vision_text",
]
