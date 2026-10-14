"""图片转文本的抽象层（V2.0 多模态 OCR）。

核心设计：**把「看图」从主模型上拆下来**。

主模型有没有视觉能力，和「能不能识别需求文档里的图片」是两个正交问题。
把「图片 -> 文本」抽成独立扩展点之后，``deepseek-flash`` 这类纯文本模型照样能吃到
图片里的信息 —— 图片先经本条链路变成文字，再进入原有的「文本 -> 结构化需求」流程，
下游（LLM 结构化、规则解析、用例生成）一行都不用改。

两类产物必须严格区分：

  - ``kind="text"``：**OCR 原文**，是图里真实存在的字。可以参与规则解析（抽字段约束），
    因为它不会凭空造出原文没有的约束；
  - ``kind="description"``：**视觉描述**，是模型对图的理解（如「这是一个登录页，
    含手机号、验证码、登录按钮」）。它可能推断出错，因此必须打标记、且**不参与**
    规则引擎的字段约束抽取，否则一句「金额上限 500」的推测会直接变成测试数据里的
    ``max_value``。
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field

#: 产物性质：OCR 原文。
KIND_TEXT = "text"
#: 产物性质：视觉描述（模型推断，需人工复核）。
KIND_DESCRIPTION = "description"
#: 产物性质：文字 + 描述混合（同样含模型推断，按「需复核」处理）。
KIND_MIXED = "mixed"
#: 未识别。
KIND_NONE = "none"

#: 含模型推断、不得进入规则解析的产物性质。
DERIVED_KINDS = frozenset({KIND_DESCRIPTION, KIND_MIXED})

#: 描述类产物的段落标记。规则解析器见到它就把其后内容整体跳过 ——
#: 模型对图片的推断不能变成字段约束（一句「金额上限 500」的猜测会直接污染测试数据），
#: 但多模态结构化那一步仍会读到它，因为那本来就是「让模型理解图片」的环节。
IMAGE_DESC_SECTION = "[图片描述 · 模型推断，非原文]"

#: 识别文字段落标记。
IMAGE_TEXT_SECTION = "[图片文字]"


@dataclass(slots=True)
class ImageTextResult:
    """一张图片的识别结果。"""

    text: str = ""
    extractor: str = ""
    kind: str = KIND_NONE
    confidence: float | None = None
    warnings: list[str] = field(default_factory=list)
    elapsed_ms: int = 0

    @property
    def usable(self) -> bool:
        return bool(self.text.strip())

    @property
    def is_description(self) -> bool:
        return self.kind in DERIVED_KINDS


class ImageTextExtractor(abc.ABC):
    """图片转文本提取器基类（与 DocumentParser / Exporter 同一套插件模式）。"""

    name: str = "base"
    label: str = "图片识别"
    #: 产物性质：text / description / mixed。
    kind: str = KIND_TEXT
    #: 依赖说明，降级提示里会用到。
    requires: str = ""

    @property
    def available(self) -> bool:
        """是否具备真实识别能力。"""
        return True

    @property
    def degraded_reason(self) -> str:
        return "" if self.available else f"{self.label}不可用：{self.requires}"

    @abc.abstractmethod
    async def extract(self, image: bytes, *, hint: str = "", filename: str = "") -> ImageTextResult:
        """识别一张图片；实现方不应抛异常，失败时返回带 warnings 的结果。"""


__all__ = [
    "DERIVED_KINDS",
    "IMAGE_DESC_SECTION",
    "IMAGE_TEXT_SECTION",
    "KIND_DESCRIPTION",
    "KIND_MIXED",
    "KIND_NONE",
    "KIND_TEXT",
    "ImageTextExtractor",
    "ImageTextResult",
]
