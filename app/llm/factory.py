"""LLM Provider 工厂 + 注册表（依赖注入入口）。

配置优先级：界面运行时覆盖（storage/data/llm_config.json） > .env / 环境变量 > 代码默认值。

降级策略（保证"没有 API Key 也能端到端跑通"）：
  显式 none           -> NullProvider（显式选择纯规则引擎）
  显式 fake           -> FakeProvider
  未配置 API Key      -> NullProvider（业务层走纯规则引擎）
  配置齐全            -> 对应真实 Provider
"""
from __future__ import annotations

from typing import Callable

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.registry import Registry
from app.llm.base import LLMProvider
from app.llm.deepseek_provider import DeepSeekProvider
from app.llm.fake_provider import FakeProvider
from app.llm.null_provider import NullProvider
from app.llm.openai_compatible import OpenAICompatibleProvider
from app.llm.runtime_config import (
    RUNTIME_CONFIG_FILENAME,
    LLMRuntimeConfigStore,
    llm_config_fingerprint,
)

logger = get_logger(__name__)

# 后续扩展点：注册新的 Provider 只需一行
PROVIDER_REGISTRY: Registry[Callable[[Settings], LLMProvider]] = Registry("LLM Provider")

PROVIDER_REGISTRY.register("deepseek", lambda settings: DeepSeekProvider(settings))
PROVIDER_REGISTRY.register("openai_compatible", lambda settings: OpenAICompatibleProvider(settings))
PROVIDER_REGISTRY.register("fake", lambda settings: FakeProvider(settings))

_PROVIDERS_REQUIRING_KEY = {"deepseek", "openai_compatible"}

# 显式选择「纯规则引擎」的别名，避免把内部实现名暴露给界面。
_RULE_ONLY_NAMES = {"none", "rule", "null"}

_config_store: LLMRuntimeConfigStore | None = None
_provider_cache: tuple[str, LLMProvider] | None = None


def get_runtime_config_store() -> LLMRuntimeConfigStore:
    """运行时配置存储（路径跟随 storage_dir，测试换目录也能自动切）。"""
    global _config_store
    settings = get_settings()
    path = settings.data_dir / RUNTIME_CONFIG_FILENAME
    if _config_store is None or _config_store.path != path:
        _config_store = LLMRuntimeConfigStore(path)
    return _config_store


def get_effective_settings() -> Settings:
    """把界面覆盖合并到 .env 基线上，得到当前真正生效的配置。"""
    base = get_settings()
    overrides = get_runtime_config_store().read()
    return base.with_llm_overrides(overrides) if overrides else base


def build_llm_provider(settings: Settings | None = None, *, provider_name: str | None = None) -> LLMProvider:
    """按配置构建 Provider，必要时自动降级为 NullProvider。"""
    settings = settings or get_effective_settings()
    name = (provider_name or settings.llm_provider or "deepseek").strip().lower()

    if name in _RULE_ONLY_NAMES:
        return NullProvider(settings, reason="已选择「纯规则引擎」模式：不调用大模型。")

    builder = PROVIDER_REGISTRY.try_get(name)
    if builder is None:
        logger.warning("未知的 LLM_PROVIDER=%s，降级为纯规则引擎", name)
        return NullProvider(settings, reason=f"未知的 LLM_PROVIDER：{name}")

    if name in _PROVIDERS_REQUIRING_KEY and not settings.llm_api_key.strip():
        reason = (
            f"未配置 LLM_API_KEY，已自动降级为纯规则引擎（provider={name}）。"
            "如需启用大模型，请在 .env 中填写 LLM_API_KEY。"
        )
        logger.warning(reason)
        return NullProvider(settings, reason=reason)

    provider = builder(settings)
    logger.info("LLM Provider 就绪：%s (%s)", provider.name, provider.model)
    return provider


def get_llm_provider() -> LLMProvider:
    """全局 Provider（依赖注入用）。

    以「生效配置指纹」做缓存：配置没变就复用同一实例，界面改动后自动重建，
    因此不需要重启服务即可切换厂商 / 模型 / Key。
    """
    global _provider_cache
    settings = get_effective_settings()
    fingerprint = llm_config_fingerprint(settings)
    if _provider_cache is not None and _provider_cache[0] == fingerprint:
        return _provider_cache[1]
    provider = build_llm_provider(settings)
    _provider_cache = (fingerprint, provider)
    return provider


def reset_llm_provider_cache() -> None:
    """清空 Provider 缓存（保存 / 清除运行时配置后调用）。"""
    global _provider_cache
    _provider_cache = None
