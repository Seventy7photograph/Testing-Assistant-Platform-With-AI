"""图片识别层：把图片（内嵌图 / 整页扫描 / 直接上传）统一转成文本。

扩展点：接入新的视觉模型或 OCR 服务，实现 ``ImageTextExtractor`` 子类并注册到
``VISION_REGISTRY`` 即可；文档解析器只负责把图片抠出来，主干不感知具体引擎。
"""
from app.vision.base import (
    DERIVED_KINDS,
    KIND_DESCRIPTION,
    KIND_MIXED,
    KIND_NONE,
    KIND_TEXT,
    ImageTextExtractor,
    ImageTextResult,
)
from app.vision.registry import (
    VISION_REGISTRY,
    build_vision_extractor,
    vision_capabilities,
    vlm_settings,
)

__all__ = [
    "DERIVED_KINDS",
    "KIND_DESCRIPTION",
    "KIND_MIXED",
    "KIND_NONE",
    "KIND_TEXT",
    "VISION_REGISTRY",
    "ImageTextExtractor",
    "ImageTextResult",
    "build_vision_extractor",
    "vision_capabilities",
    "vlm_settings",
]
