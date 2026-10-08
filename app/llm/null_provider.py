"""空 Provider：表示"未启用大模型"。

当未配置 LLM_API_KEY 时由 factory 返回本实现，
业务层通过 `available == False` 判断并直接走规则引擎，
从而保证「无密钥也能端到端跑通」，而不是抛异常中断。
"""
from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.exceptions import LLMNotConfiguredError
from app.llm.base import LLMMessage, LLMProvider, LLMResponse


class NullProvider(LLMProvider):
    name = "null"
    supports_json_mode = False

    def __init__(self, settings: Settings | None = None, *, reason: str = "") -> None:
        super().__init__(settings)
        self.degraded_reason = reason or "未启用大模型（未配置 LLM_API_KEY）"

    @property
    def available(self) -> bool:
        return False

    @property
    def model(self) -> str:
        return ""

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
        extra_body: dict[str, Any] | None = None,
    ) -> LLMResponse:
        raise LLMNotConfiguredError(self.degraded_reason)

    async def complete_json(self, messages: list[LLMMessage], **kwargs: object) -> LLMResponse:
        raise LLMNotConfiguredError(self.degraded_reason)

    async def health_check(self) -> bool:
        return False
