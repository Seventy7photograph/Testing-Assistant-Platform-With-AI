"""OpenAI-compatible Chat Completions 客户端。

只依赖 /chat/completions 这一个约定，因此 DeepSeek、Qwen、OpenAI、
Moonshot、SiliconFlow 等兼容服务都可以直接换 base_url 使用。
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import time
from typing import Any, AsyncIterator, Callable
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from dataclasses import dataclass

from app.core.config import Settings
from app.llm.base import PROBE_MAX_TOKENS
from app.llm.factory import get_effective_settings
from app.report.config import provider_label
from .prompts import SYSTEM_PROMPT


@dataclass(frozen=True)
class LLMSettings:
    """报告链路的 LLM 视图。

    字段值全部来自统一配置（`.env` 基线 + 界面运行时覆盖），与「用例生成」链路
    共用同一份 Key 与端点，避免两处配置互相打架。
    """

    api_key: str
    base_url: str
    model: str
    temperature: float
    timeout: float
    max_retries: int

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def provider(self) -> str:
        return provider_label(urlparse(self.base_url).hostname or "")


def llm_settings(
    *,
    model: str | None = None,
    temperature: float | None = None,
    settings: Settings | None = None,
) -> LLMSettings:
    """构造报告链路使用的 LLM 设置（取自当前生效的统一配置）。"""

    effective = settings or get_effective_settings()
    return LLMSettings(
        api_key=(effective.llm_api_key or "").strip(),
        base_url=(effective.llm_base_url or "https://api.deepseek.com").rstrip("/"),
        model=(model or effective.llm_model or "deepseek-flash").strip() or "deepseek-flash",
        temperature=effective.llm_temperature if temperature is None else temperature,
        timeout=float(effective.llm_timeout or 60.0),
        max_retries=max(0, int(effective.llm_max_retries or 0)),
    )

_RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


def _endpoint(settings: LLMSettings) -> str:
    return f"{settings.base_url}/chat/completions"


def _is_deepseek(base_url: str) -> bool:
    """判断端点是否为 DeepSeek 官方（只有它认 ``thinking`` 开关）。"""
    return "deepseek" in (urlparse(base_url).hostname or "").lower()


def _headers(settings: LLMSettings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
    }


def _payload(
    settings: LLMSettings,
    user_prompt: str,
    stream: bool = False,
    include_usage: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": settings.model,
        "temperature": settings.temperature,
        "stream": stream,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }
    if stream and include_usage:
        # 流式默认不返回 usage，要显式要一次。有服务商不认这个字段，
        # stream() 里对 400 做了去掉它重试的降级。
        payload["stream_options"] = {"include_usage": True}
    return payload


def _require_key(settings: LLMSettings) -> None:
    if not settings.configured:
        raise HTTPException(
            status_code=503,
            detail="未配置 LLM_API_KEY。请复制 .env.example 为 .env 并填写 API Key。",
        )


def _http_error(exc: httpx.HTTPStatusError) -> HTTPException:
    status = exc.response.status_code
    body = exc.response.text[:600]
    hints = {
        401: "API Key 无效或已过期。",
        402: "账户额度不足。",
        403: "该 Key 无权访问此模型。",
        404: "接口地址或模型名不正确，请检查 LLM_BASE_URL 与 LLM_MODEL。",
        429: "请求过于频繁，已被服务方限流。",
        502: "模型服务或网络中间层返回了错误，请检查网络与系统代理设置。",
        503: "模型服务暂时不可用。",
        504: "模型服务网关超时。",
    }
    hint = hints.get(status, "模型服务返回错误。")
    return HTTPException(status_code=502, detail=f"{hint}（{status}）{body}")


def _host_bypasses_proxy(host: str | None) -> bool:
    """本机与内网地址一律绕开系统代理。

    Windows 上 httpx 会读取注册表里的代理设置（Clash 一类工具常写进去），
    而它的 no_proxy 匹配并不认识 ProxyOverride 里的 `127.*` 通配，
    于是连 http://127.0.0.1:8011 这种本机请求也会被送给代理，
    代理回一个空 body 的 502 —— 界面只能看到「模型服务返回错误。（502）」。
    系统代理是给公网用的，内网直连才是正确行为。
    """
    if not host:
        return False
    if host == "localhost" or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


def _client(settings: LLMSettings, timeout: float | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=settings.timeout if timeout is None else timeout,
        trust_env=not _host_bypasses_proxy(urlparse(settings.base_url).hostname),
    )


async def _request_with_retry(
    settings: LLMSettings, user_prompt: str
) -> httpx.Response:
    """带退避重试的普通（非流式）请求。"""

    last_error: Exception | None = None
    attempts = settings.max_retries + 1

    for attempt in range(attempts):
        try:
            async with _client(settings) as client:
                response = await client.post(
                    _endpoint(settings),
                    headers=_headers(settings),
                    json=_payload(settings, user_prompt),
                )
                if response.status_code in _RETRY_STATUS and attempt < attempts - 1:
                    raise httpx.HTTPStatusError(
                        "retryable", request=response.request, response=response
                    )
                response.raise_for_status()
                return response
        except httpx.TimeoutException as exc:
            last_error = exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in _RETRY_STATUS and attempt < attempts - 1:
                last_error = exc
            else:
                raise _http_error(exc) from exc
        except httpx.HTTPError as exc:
            last_error = exc

        if attempt < attempts - 1:
            await asyncio.sleep(0.6 * (2**attempt))

    if isinstance(last_error, httpx.TimeoutException):
        raise HTTPException(status_code=504, detail=f"大模型 API 请求超时（{settings.timeout:.0f}s）。")
    if isinstance(last_error, httpx.HTTPStatusError):
        raise _http_error(last_error)
    raise HTTPException(status_code=502, detail=f"大模型 API 网络请求失败：{last_error}")


def _extract_content(data: Any) -> str:
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(
            status_code=502, detail="大模型返回结构异常，请检查模型接口兼容性。"
        ) from exc

    content = message.get("content")
    if isinstance(content, list):
        # 部分服务返回分段内容
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    if not isinstance(content, str) or not content.strip():
        reason = (data.get("choices") or [{}])[0].get("finish_reason")
        if reason == "length":
            detail = "大模型返回了空内容：输出预算被思考过程占满（finish_reason=length）。"
        else:
            detail = "大模型返回了空内容。"
        raise HTTPException(status_code=502, detail=detail)
    return content


async def complete(user_prompt: str, settings: LLMSettings) -> tuple[str, dict[str, Any] | None]:
    """一次性生成，返回 (正文, usage)。"""

    _require_key(settings)
    response = await _request_with_retry(settings, user_prompt)
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="大模型返回的不是合法 JSON。") from exc
    return _extract_content(data), data.get("usage")


async def stream(
    user_prompt: str,
    settings: LLMSettings,
    usage_sink: Callable[[dict[str, Any]], None] | None = None,
) -> AsyncIterator[str]:
    """流式生成。逐段产出 delta 文本；usage 通过 usage_sink 回传。

    流式响应默认不带 usage，要显式请求 `stream_options.include_usage`。
    部分兼容服务不认这个字段并回 400 —— 那时去掉它重来一次，而不是把整个生成判失败。
    """

    _require_key(settings)
    attempts = settings.max_retries + 1
    include_usage = usage_sink is not None
    attempt = 0

    # 用 while 而不是 for：协议降级（去掉 stream_options）不该消耗重试预算。
    while attempt < attempts:
        emitted = False
        try:
            async with _client(settings) as client:
                async with client.stream(
                    "POST",
                    _endpoint(settings),
                    headers=_headers(settings),
                    json=_payload(settings, user_prompt, stream=True, include_usage=include_usage),
                ) as response:
                    if response.status_code == 400 and include_usage:
                        # 服务商不认 stream_options。不占用重试预算，去掉字段重来。
                        await response.aread()
                        include_usage = False
                        continue
                    if response.status_code in _RETRY_STATUS and attempt < attempts - 1:
                        await response.aread()
                        await asyncio.sleep(0.6 * (2**attempt))
                        attempt += 1
                        continue
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        await response.aread()
                        raise _http_error(exc) from exc

                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if chunk == "[DONE]":
                            return
                        try:
                            payload = json.loads(chunk)
                        except json.JSONDecodeError:
                            continue
                        if usage_sink is not None:
                            usage = payload.get("usage")
                            if isinstance(usage, dict):
                                usage_sink(usage)
                        try:
                            delta = payload["choices"][0]["delta"].get("content")
                        except (KeyError, IndexError, TypeError, AttributeError):
                            continue
                        if delta:
                            emitted = True
                            yield delta
                    return
        except httpx.TimeoutException as exc:
            if emitted:
                raise HTTPException(status_code=504, detail="流式响应中断：模型服务超时。") from exc
        except httpx.HTTPError as exc:
            if emitted or attempt >= attempts - 1:
                raise HTTPException(status_code=502, detail=f"模型服务连接失败：{exc}") from exc

        await asyncio.sleep(0.6 * (2**attempt))
        attempt += 1


async def probe(settings: LLMSettings) -> tuple[int, str]:
    """真实探活：用最小代价的请求确认服务可用，并返回延迟。

    探针必须显式关闭思考模式并给足输出预算：DeepSeek V4 默认开思考，
    极小预算（曾用 max_tokens=8）会被思维链整段吃光，``content`` 为空，
    服务明明是通的却被报成「返回了空内容」。
    """

    _require_key(settings)
    payload: dict[str, Any] = {
        "model": settings.model,
        "stream": False,
        "max_tokens": PROBE_MAX_TOKENS,
        "messages": [
            {"role": "system", "content": "你是一个连通性测试端点。"},
            {"role": "user", "content": "回复：ok"},
        ],
    }
    if _is_deepseek(settings.base_url):
        # 只有 DeepSeek 认这个字段；对其他兼容端点透传未知字段会被 400 拒绝。
        payload["thinking"] = {"type": "disabled"}

    started = time.perf_counter()
    async with _client(settings, min(settings.timeout, 30.0)) as client:
        try:
            response = await client.post(
                _endpoint(settings),
                headers=_headers(settings),
                json=payload,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise HTTPException(status_code=504, detail="探活超时，模型服务未在 30 秒内响应。") from exc
        except httpx.HTTPStatusError as exc:
            raise _http_error(exc) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"无法连接模型服务：{exc}") from exc

    latency = int((time.perf_counter() - started) * 1000)
    try:
        reply = _extract_content(response.json())
    except HTTPException:
        reply = "服务已响应，但返回结构无法解析。"
    return latency, reply.strip()[:120]
