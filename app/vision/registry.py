"""图片识别通道的注册表与装配入口。

与设计策略 / 导出器 / 文档解析器同一套插件模式：新增一家 OCR 或一个视觉模型，
只需实现 ``ImageTextExtractor`` 子类并注册，主干代码不动。

``VISION_PROVIDER=auto``（默认）时的挑选顺序体现的是**成本与稳定性优先**：
先试多模态模型（语义最好，但按 token 计费），不可用再退本地 OCR（离线、免费、
但只认字），最后才是云端 OCR。三者都不可用时返回 NullExtractor，
由调用方把「为什么没识别」如实体现在告警与界面上，绝不静默跳过。
"""
from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.registry import Registry
from app.vision.base import ImageTextExtractor
from app.vision.cloud_ocr import CloudOcrExtractor
from app.vision.fake import FakeVisionExtractor
from app.vision.imaging import DEFAULT_MAX_SIDE
from app.vision.local_ocr import BACKENDS, DEFAULT_LANGUAGES, LocalOcrExtractor, detect_backend
from app.vision.null import NullExtractor
from app.vision.vlm import MODE_TEXT, VisionLlmExtractor

logger = get_logger(__name__)

#: 图片识别器注册表（名称 -> 类型/工厂标识）。
VISION_REGISTRY: Registry[str] = Registry("图片识别器")

VISION_REGISTRY.register("vlm", "vlm")
VISION_REGISTRY.register("local-ocr", "local-ocr")
VISION_REGISTRY.register("cloud-ocr", "cloud-ocr")
VISION_REGISTRY.register("fake", "fake")
VISION_REGISTRY.register("none", "none")

#: 配置别名 -> 注册表名，避免使用者必须记住连字符写法。
PROVIDER_ALIASES: dict[str, str] = {
    "vlm": "vlm",
    "vision": "vlm",
    "llm": "vlm",
    "multimodal": "vlm",
    "local": "local-ocr",
    "local_ocr": "local-ocr",
    "ocr": "local-ocr",
    "cloud": "cloud-ocr",
    "cloud_ocr": "cloud-ocr",
    "fake": "fake",
    "mock": "fake",
    "none": "none",
    "off": "none",
    "disabled": "none",
}

#: 前端「图片识别通道」下拉框的候选项（与 LLM 目录同一个思路：候选来自后端，前端不硬编码）。
PROVIDER_OPTIONS: list[dict[str, Any]] = [
    {
        "name": "auto",
        "label": "自动（推荐）",
        "description": "按 多模态模型 -> 本地 OCR -> 云端 OCR 依次尝试，都不行则如实提示，不静默跳过。",
        "requires_key": False,
        "requires_url": False,
        "allow_model": False,
        "allow_mode": True,
    },
    {
        "name": "vlm",
        "label": "多模态模型",
        "description": "把图片交给支持图片输入的模型。识别语义最好（原型图、流程图），按 token 计费。",
        "requires_key": True,
        "requires_url": False,
        "allow_model": True,
        "allow_mode": True,
    },
    {
        "name": "local-ocr",
        "label": "本地 OCR（离线）",
        "description": "离线、免费、不联网，只认图中的文字（不认识界面语义）。需安装本地 OCR 引擎。",
        "requires_key": False,
        "requires_url": False,
        "allow_model": False,
        "allow_mode": False,
    },
    {
        "name": "cloud-ocr",
        "label": "云端 OCR",
        "description": "调用自建或第三方的 OCR 服务，适合手写与复杂版式；需按契约提供地址。",
        "requires_key": True,
        "requires_url": True,
        "allow_model": False,
        "allow_mode": False,
    },
    {
        "name": "fake",
        "label": "离线假识别（演示 / 测试）",
        "description": "不联网、返回确定性占位文本，仅用于演示与自动化测试。",
        "requires_key": False,
        "requires_url": False,
        "allow_model": False,
        "allow_mode": False,
    },
    {
        "name": "none",
        "label": "关闭图片识别",
        "description": "不识别任何图片：正文只保留 [图片 N] 占位与告警。适合完全离线且不需要图片信息的场景。",
        "requires_key": False,
        "requires_url": False,
        "allow_model": False,
        "allow_mode": False,
    },
]


def provider_options() -> list[dict[str, Any]]:
    """返回候选项的深拷贝，避免调用方修改目录常量。"""
    return [dict(item) for item in PROVIDER_OPTIONS]


def build_vision_extractor(settings: Settings) -> ImageTextExtractor:
    """按配置装配图片识别通道（可能返回不可用的 NullExtractor）。"""
    requested = (getattr(settings, "vision_provider", "") or "auto").strip().lower()
    if requested in ("none", "off", "disabled"):
        return NullExtractor("已显式关闭图片识别（VISION_PROVIDER=none）：图片只做占位，不识别内容。")
    if requested in ("auto", ""):
        return _auto_chain(settings)
    name = PROVIDER_ALIASES.get(requested)
    if name is None:
        logger.warning("未知的 VISION_PROVIDER=%s，已回落 auto。", requested)
        return _auto_chain(settings)
    return _build(name, settings)


def _auto_chain(settings: Settings) -> ImageTextExtractor:
    reasons: list[str] = []
    for name in ("vlm", "local-ocr", "cloud-ocr"):
        extractor = _build(name, settings)
        if extractor.available:
            return extractor
        reasons.append(extractor.degraded_reason or extractor.label)
    return NullExtractor(
        "没有任何可用的图片识别通道：" + "；".join(reason for reason in reasons if reason)
    )


def _build(name: str, settings: Settings) -> ImageTextExtractor:
    if name == "vlm":
        return VisionLlmExtractor(
            vlm_settings(settings),
            mode=(getattr(settings, "vision_mode", MODE_TEXT) or MODE_TEXT),
            max_side=int(getattr(settings, "vision_max_side", DEFAULT_MAX_SIDE) or DEFAULT_MAX_SIDE),
        )
    if name == "local-ocr":
        return LocalOcrExtractor(
            languages=getattr(settings, "vision_languages", DEFAULT_LANGUAGES) or DEFAULT_LANGUAGES,
            backend=getattr(settings, "vision_ocr_backend", "") or "",
        )
    if name == "cloud-ocr":
        return CloudOcrExtractor(
            url=getattr(settings, "vision_cloud_url", "") or "",
            api_key=getattr(settings, "vision_cloud_key", "") or "",
            field=getattr(settings, "vision_cloud_field", "text") or "text",
            timeout=float(getattr(settings, "vision_timeout", 60.0) or 60.0),
        )
    if name == "fake":
        return FakeVisionExtractor()
    return NullExtractor()


def vlm_settings(settings: Settings) -> Settings:
    """把 VISION_* 映射成一份 Provider 配置。

    未单独配置视觉 Key / 端点时**复用主模型配置**：如果使用者本来就把模型配成了
    支持图片输入的型号，图片应当直接可用，而不是要求他再填一遍同样的 Key。
    """
    overrides: dict[str, Any] = {
        "llm_provider": "openai_compatible",
        "llm_api_key": getattr(settings, "vision_api_key", "") or settings.llm_api_key,
        "llm_base_url": getattr(settings, "vision_base_url", "") or settings.llm_base_url,
        "llm_model": getattr(settings, "vision_model", "") or settings.llm_model,
        "llm_timeout": float(getattr(settings, "vision_timeout", 60.0) or 60.0),
    }
    return settings.with_llm_overrides(overrides)


def vision_capabilities(settings: Settings) -> dict[str, Any]:
    """能力清单：供 /health 与设置页展示「当前用哪条通道、为什么不可用」。"""
    extractor = build_vision_extractor(settings)
    active = detect_backend()
    return {
        "provider": (getattr(settings, "vision_provider", "") or "auto"),
        "mode": (getattr(settings, "vision_mode", "") or MODE_TEXT),
        "extractor": extractor.name,
        "label": extractor.label,
        "available": extractor.available,
        "kind": extractor.kind,
        "degraded_reason": extractor.degraded_reason,
        "max_images_per_doc": int(getattr(settings, "vision_max_images", 20) or 20),
        "local_ocr_backend": active.name if active else "",
        "local_ocr_hint": "" if active else LocalOcrExtractor().requires,
        "supported": sorted(VISION_REGISTRY.names()),
    }


__all__ = [
    "PROVIDER_ALIASES",
    "VISION_REGISTRY",
    "build_vision_extractor",
    "vision_capabilities",
    "vlm_settings",
]
