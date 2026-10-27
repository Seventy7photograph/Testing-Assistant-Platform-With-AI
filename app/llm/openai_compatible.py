"""OpenAI 兼容协议的通用 Provider。

绝大多数国产大模型（DeepSeek、Qwen、GLM、Kimi 等）都提供
`POST {base_url}/chat/completions` 形式的 OpenAI 兼容接口，
因此把协议差异收敛在本文件，DeepSeek 只需继承并改默认值。
"""
from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.core.exceptions import LLMError, LLMResponseFormatError
from app.core.logging import get_logger
from app.core.utils import Timer, truncate
from app.llm.base import LLMMessage, LLMProvider, LLMResponse

logger = get_logger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """通用 OpenAI 兼容适配器。"""

    name = "openai_compatible"
    supports_json_mode = True

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(settings)
        self._api_key = api_key if api_key is not None else self.settings.llm_api_key
        self._base_url = (base_url or self.settings.llm_base_url or "").rstrip("/")
        self._model = model or self.settings.llm_model
        if not self._api_key:
            self.degraded_reason = "未配置 API Key"

    @property
    def model(self) -> str:
        return self._model

    @property
    def available(self) -> bool:
        return bool(self._api_key and self._base_url)

    @property
    def endpoint(self) -> str:
        return f"{self._base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
        extra_body: dict[str, Any] | None = None,
    ) -> LLMResponse:
        if not self.available:
            raise LLMError("LLM Provider 不可用：" + (self.degraded_reason or "未配置"))

        resolved_model = (model or self.model).strip()
        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": [message.to_dict() for message in messages],
            "temperature": self.settings.llm_temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.settings.llm_max_tokens,
            "stream": False,
        }
        if json_mode and self.supports_json_mode:
            payload["response_format"] = {"type": "json_object"}
        if extra_body:
            # 厂商私有参数透传（如 DeepSeek 的 thinking 开关）。
            payload.update(extra_body)

        with Timer() as timer:
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self.settings.llm_timeout, connect=15.0),
                    follow_redirects=True,
                ) as client:
                    response = await client.post(self.endpoint, json=payload, headers=self._headers())
            except httpx.TimeoutException as exc:
                raise LLMError(
                    f"调用大模型超时（>{self.settings.llm_timeout}s）",
                    detail={"endpoint": self.endpoint},
                ) from exc
            except httpx.HTTPError as exc:
                raise LLMError(
                    f"调用大模型失败：{exc}",
                    detail={"endpoint": self.endpoint, "error": str(exc)},
                ) from exc

        if response.status_code >= 400:
            raise LLMError(
                f"大模型接口返回 HTTP {response.status_code}",
                detail={"endpoint": self.endpoint, "body": truncate(response.text, 500)},
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMResponseFormatError(
                "大模型返回体不是合法 JSON",
                detail={"body": truncate(response.text, 500)},
            ) from exc

        return self._parse_completion(
            data,
            elapsed_ms=timer.elapsed_ms,
            fallback_model=resolved_model,
        )

    def _parse_completion(
        self,
        data: dict[str, Any],
        *,
        elapsed_ms: int,
        fallback_model: str = "",
    ) -> LLMResponse:
        choices = data.get("choices") or []
        if not choices:
            raise LLMResponseFormatError(
                "大模型返回体缺少 choices 字段",
                detail={"keys": list(data.keys())},
            )
        choice = choices[0]
        finish_reason = str(choice.get("finish_reason") or "")
        message = choice.get("message") or {}
        content = message.get("content") or ""
        if not content.strip():
            # 空正文有两种截然不同的原因，报错必须区分，否则使用者只会看到
            # 「返回内容为空」而不知道该动哪个旋钮：
            #   1. 输出预算被思考过程吃光（finish_reason=length）→ 调大 max_tokens
            #      或关掉思考模式；
            #   2. 模型真的没说话（finish_reason=stop）→ 多半是提示词被拒答。
            usage = data.get("usage") or {}
            reasoning_chars = len(message.get("reasoning_content") or "")
            if finish_reason == "length":
                detail = (
                    f"输出预算（max_tokens={usage.get('completion_tokens') or '?'}）被思考过程占满，"
                    "正文尚未开始就被截断。请调大 max_tokens，或对探活类请求关闭思考模式。"
                )
            elif reasoning_chars:
                detail = "模型只输出了思维链（reasoning_content），没有输出正文。"
            else:
                detail = "模型返回的 message.content 为空。"
            raise LLMResponseFormatError(
                "大模型返回内容为空：" + detail,
                detail={
                    "finish_reason": finish_reason,
                    "usage": usage,
                    "reasoning_chars": reasoning_chars,
                },
            )
        return LLMResponse(
            content=content,
            model=data.get("model") or fallback_model or self.model,
            usage=data.get("usage") or {},
            elapsed_ms=elapsed_ms,
            raw=data,
            finish_reason=finish_reason,
        )
