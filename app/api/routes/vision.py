"""图片识别通道配置接口（设置页「图片识别」面板）。

GET    /vision/config       读取当前生效配置与实际选中的通道（含不可用原因）
PUT    /vision/config       保存界面覆盖（写进 storage/data/llm_config.json，不重启即生效）
DELETE /vision/config       清除图片识别的界面覆盖，恢复 .env 基线
POST   /vision/config/test  用一张带文字的探针图片真跑一次识别

与 LLM 配置页共用同一套机制（界面覆盖 > .env 基线，随时可一键恢复），
使用者也只需要学一次。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import SettingsDep
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.utils import truncate
from app.llm.factory import get_effective_settings, get_runtime_config_store
from app.llm.runtime_config import mask_api_key
from app.schemas.api import ApiResponse, ok
from app.schemas.vision import (
    VisionConfigInfo,
    VisionConfigUpdate,
    VisionProviderOption,
    VisionTestResult,
)
from app.vision.imaging import pillow_available, probe_image
from app.vision.registry import build_vision_extractor, provider_options, vision_capabilities

router = APIRouter(tags=["图片识别"])

logger = get_logger(__name__)

#: 回显 .env 基线时用到的配置项。
ENV_BASELINE_FIELDS: tuple[str, ...] = (
    "vision_provider",
    "vision_mode",
    "vision_model",
    "vision_base_url",
    "vision_cloud_url",
    "vision_ocr_backend",
    "vision_languages",
    "vision_max_images",
    "vision_max_side",
    "vision_min_pixels",
)

#: 界面字段 -> 配置项。
PATCH_FIELDS: dict[str, str] = {
    "provider": "vision_provider",
    "mode": "vision_mode",
    "model": "vision_model",
    "base_url": "vision_base_url",
    "api_key": "vision_api_key",
    "cloud_url": "vision_cloud_url",
    "cloud_key": "vision_cloud_key",
    "ocr_backend": "vision_ocr_backend",
    "languages": "vision_languages",
    "max_images": "vision_max_images",
    "max_side": "vision_max_side",
    "min_pixels": "vision_min_pixels",
}

MODES: list[dict[str, str]] = [
    {
        "value": "text",
        "label": "只要图里的文字",
        "description": "适合表格截图、条款截图；识别结果可参与字段约束抽取。",
    },
    {
        "value": "describe",
        "label": "描述图片内容",
        "description": "适合原型图、流程图；识别结果不参与字段约束抽取，需人工复核。",
    },
    {
        "value": "both",
        "label": "文字 + 描述",
        "description": "两者都要，信息最全、费用最高；描述部分需人工复核。",
    },
]


def _vision_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in overrides.items() if key.startswith("vision_")}


def _baseline_defaults() -> dict[str, Any]:
    base = get_settings()
    defaults: dict[str, Any] = {key: getattr(base, key) for key in ENV_BASELINE_FIELDS}
    defaults["api_key_configured"] = bool(base.vision_api_key.strip() or base.llm_api_key.strip())
    defaults["cloud_key_configured"] = bool(base.vision_cloud_key.strip())
    return defaults


def _to_info(settings: Settings) -> VisionConfigInfo:
    capabilities = vision_capabilities(settings)
    overrides = _vision_overrides(get_runtime_config_store().read())
    api_key = settings.vision_api_key or settings.llm_api_key
    return VisionConfigInfo(
        provider=settings.vision_provider,
        mode=settings.vision_mode,
        model=settings.vision_model or settings.llm_model,
        base_url=settings.vision_base_url or settings.llm_base_url,
        api_key_configured=bool(api_key.strip()),
        api_key_masked=mask_api_key(api_key),
        cloud_url_configured=bool(settings.vision_cloud_url.strip()),
        ocr_backend=settings.vision_ocr_backend,
        languages=settings.vision_languages,
        max_images=settings.vision_max_images,
        max_side=settings.vision_max_side,
        min_pixels=settings.vision_min_pixels,
        extractor=capabilities["extractor"],
        label=capabilities["label"],
        kind=capabilities["kind"],
        available=capabilities["available"],
        degraded_reason=capabilities["degraded_reason"],
        local_ocr_backend=capabilities["local_ocr_backend"],
        local_ocr_hint=capabilities["local_ocr_hint"],
        source="runtime" if overrides else "env",
        overridden_fields=sorted(overrides),
        env_defaults=_baseline_defaults(),
        providers=[VisionProviderOption(**item) for item in provider_options()],
        modes=MODES,
    )


@router.get("/vision/config", response_model=ApiResponse[VisionConfigInfo], summary="读取图片识别配置")
async def get_vision_config(settings: SettingsDep) -> dict:
    return ok(_to_info(get_effective_settings()))


@router.put("/vision/config", response_model=ApiResponse[VisionConfigInfo], summary="保存图片识别配置")
async def update_vision_config(payload: VisionConfigUpdate) -> dict:
    patch: dict[str, Any] = {}
    for field, key in PATCH_FIELDS.items():
        value = getattr(payload, field, None)
        if value is not None:
            patch[key] = value
    get_runtime_config_store().save(patch)
    logger.info("已更新图片识别配置：%s", sorted(patch))
    return ok(_to_info(get_effective_settings()), message="图片识别配置已保存。")


@router.delete("/vision/config", response_model=ApiResponse[VisionConfigInfo], summary="恢复图片识别基线")
async def reset_vision_config() -> dict:
    store = get_runtime_config_store()
    current = store.read()
    if not _vision_overrides(current):
        return ok(
            _to_info(get_effective_settings()),
            message="当前没有图片识别的界面覆盖，仍使用 .env 基线。",
        )
    # 只清 vision_* 覆盖，保留大模型那边的界面配置：两类配置互不牵连。
    remaining = {key: value for key, value in current.items() if not key.startswith("vision_")}
    store.replace(remaining)
    return ok(_to_info(get_effective_settings()), message="已恢复图片识别的 .env 基线。")


@router.post("/vision/config/test", response_model=ApiResponse[VisionTestResult], summary="测试图片识别通道")
async def test_vision_config() -> dict:
    """用一张带文字的探针图片真跑一次识别。

    只报「配置完整」没有意义 —— 真正会踩的坑是「配了个不支持图片输入的模型」，
    那只有真发一次请求才暴露得出来。
    """
    settings = get_effective_settings()
    extractor = build_vision_extractor(settings)
    if not extractor.available:
        return ok(
            VisionTestResult(
                ok=False,
                provider=settings.vision_provider,
                mode=settings.vision_mode,
                message=extractor.degraded_reason or "当前没有可用的图片识别通道。",
            )
        )
    result = await extractor.extract(probe_image(), filename="probe.png")
    if result.usable:
        message = "识别通道可用，已返回内容。"
    else:
        message = "；".join(result.warnings) or "通道有响应，但未返回任何内容。"
    if not pillow_available():
        message += "（未安装 pillow，探针图片为 1×1 纯色图，只能证明请求链路可用。）"
    return ok(
        VisionTestResult(
            ok=result.usable,
            provider=settings.vision_provider,
            extractor=result.extractor,
            mode=settings.vision_mode,
            elapsed_ms=result.elapsed_ms,
            message=message,
            sample=truncate(result.text.strip(), 120),
        )
    )
