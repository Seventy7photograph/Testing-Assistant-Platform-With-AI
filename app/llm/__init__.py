"""LLM Provider 抽象层。

扩展点：后续接入 Qwen/GLM/本地 Ollama 时，只需实现 LLMProvider 并注册，
业务层代码零改动（见 factory.py 的 PROVIDER_REGISTRY）。
"""
from app.llm.base import LLMMessage, LLMProvider, LLMResponse, assistant, system, user
from app.llm.factory import build_llm_provider, get_llm_provider, reset_llm_provider_cache

__all__ = [
    "LLMMessage",
    "LLMProvider",
    "LLMResponse",
    "assistant",
    "system",
    "user",
    "build_llm_provider",
    "get_llm_provider",
    "reset_llm_provider_cache",
]