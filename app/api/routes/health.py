"""健康检查与能力清单。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DesignEngineDep, LLMDep, SettingsDep
from app.exporters.registry import available_formats
from app.integrations.base import available_integrations
from app.llm.factory import get_effective_settings, get_runtime_config_store
from app.parsers.registry import supported_extensions
from app.schemas.api import ApiResponse, HealthInfo, IntegrationInfo, MethodInfo, ok
from app.vision.registry import vision_capabilities

router = APIRouter(tags=["健康检查"])


@router.get("/health", response_model=ApiResponse[HealthInfo], summary="健康检查与能力清单")
async def health(settings: SettingsDep, llm: LLMDep, engine: DesignEngineDep) -> dict:
    # 未启用时 runtime provider 是 null 哨兵，对界面没有信息量：
    # 这里回报「配置里的服务商」，可用性由 llm_available 单独表达。
    effective = get_effective_settings()
    provider_name = llm.name if llm.name not in {"", "null"} else (effective.llm_provider or "none")
    info = HealthInfo(
        app_name=settings.app_name,
        version=settings.app_version,
        status="ok",
        llm_provider=provider_name,
        llm_model=llm.model or effective.llm_model,
        llm_base_url=settings.llm_base_url,
        llm_available=llm.available,
        llm_degraded_reason=llm.degraded_reason,
        llm_source="runtime" if get_runtime_config_store().read() else "env",
        methods=[MethodInfo(**item) for item in engine.available_methods()],
        export_formats=available_formats(),
        supported_extensions=supported_extensions(),
        vision=vision_capabilities(effective),
        limits={
            "max_cases_per_requirement": effective.max_cases_per_requirement,
            "max_upload_size_mb": effective.max_upload_size_mb,
        },
    )
    return ok(info)


@router.get("/integrations", response_model=ApiResponse[list[IntegrationInfo]], summary="外部集成清单（尚未实现）")
async def integrations() -> dict:
    return ok(available_integrations())

