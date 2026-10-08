"""LLM Provider 抽象基类。

约束：业务代码只依赖本模块的抽象，不感知具体厂商。
内置能力：
  - complete()      单轮补全
  - complete_json() JSON 模式 + 解析失败自动修复重试（抵抗模型输出抖动）
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings, get_settings
from app.core.exceptions import LLMError, LLMResponseFormatError
from app.core.logging import get_logger
from app.core.utils import dump_json, extract_json, truncate

logger = get_logger(__name__)

JSON_REPAIR_INSTRUCTION = (
    "上一次回复无法解析为 JSON。请只输出一个合法 JSON 对象（不要 Markdown 代码块、"
    "不要解释文字、不要尾随逗号），字段名使用双引号。"
)

TRUNCATION_INSTRUCTION = (
    "上一次回复因为达到输出长度上限被截断，JSON 没有闭合、无法解析。"
    "请在保证字段结构完整的前提下精简内容：只保留最关键的 items、压缩 description 与列表项，"
    "并确保 JSON 严格闭合。当前输出上限为 {limit} tokens。"
)

#: 连续截断时抬高的输出上限不会超过这个值：再高既超出多数端点的单次响应能力，也白白烧额度。
MAX_TOKEN_CEILING = 32768

#: 连通性探针的提示词：越短越好，探针只关心「能不能通」。
PROBE_PROMPT = "请只回复两个字：连接成功"

#: 探针的输出预算。**不要调小**：思考型模型（如 DeepSeek V4 默认开思考模式）会先输出
#: 一段思维链，预算太小会让 16/64 个 token 全部消耗在推理上、正文为空，
#: 于是探针把「模型正常」误报成「连接失败 · 大模型返回内容为空」。
PROBE_MAX_TOKENS = 512


@dataclass(slots=True)
class LLMMessage:
    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


def system(content: str) -> LLMMessage:
    return LLMMessage(role="system", content=content)


def user(content: str) -> LLMMessage:
    return LLMMessage(role="user", content=content)


def assistant(content: str) -> LLMMessage:
    return LLMMessage(role="assistant", content=content)


@dataclass(slots=True)
class LLMResponse:
    """一次补全的结果：正文 + 可观测元信息。"""

    content: str
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: int = 0
    attempts: int = 1
    parsed: Any = None
    raw: dict[str, Any] = field(default_factory=dict)
    #: 厂商返回的结束原因。``length`` 表示被 max_tokens 截断——这是与「模型输出抖动」
    #: 完全不同的一类失败，必须分开重试，否则只是把同一个必然失败的请求重跑一遍。
    finish_reason: str = ""


class LLMProvider(abc.ABC):
    """所有大模型适配器的基类。"""

    name: str = "base"
    supports_json_mode: bool = True

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.degraded_reason: str = ""

    # ------------------------------------------------------------------ #
    # 由子类实现
    # ------------------------------------------------------------------ #
    @property
    @abc.abstractmethod
    def available(self) -> bool:
        """是否具备真实调用能力（False 时业务层直接走规则引擎）。"""

    @abc.abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
        extra_body: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """执行一次对话补全。

        ``extra_body`` 是厂商私有参数的透传口（如 DeepSeek 的
        ``{"thinking": {"type": "disabled"}}``），默认实现不感知具体字段。
        """

    # ------------------------------------------------------------------ #
    # 通用能力
    # ------------------------------------------------------------------ #
    @property
    def model(self) -> str:
        return self.settings.llm_model

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model,
            "available": self.available,
            "degraded_reason": self.degraded_reason,
        }

    async def complete_json(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        retries: int | None = None,
        expect: type | tuple[type, ...] = (dict, list),
    ) -> LLMResponse:
        """调用并解析 JSON；失败时按失败原因分别重试。

        两类失败分开处理，避免「重试 = 重跑同一个必然失败的请求」：
          - 输出被 max_tokens 截断（``finish_reason == "length"``）：逐次抬高输出上限再试；
            已经到上限仍被截断时，改为要求模型精简内容。
          - 输出不是合法 JSON（模型抖动）：追加修复指令重试。

        这条区分很关键：真实走查中发现 deepseek-flash 会在 4096 tokens 的输出预算里花掉
        ~2200 个推理 token，JSON 必然被截断；旧实现三次重试完全相同，只会白烧三次额度。

        :raises LLMError: 网络/接口层错误
        :raises LLMResponseFormatError: 多次重试后仍非合法 JSON
        """
        max_retries = self.settings.llm_max_retries if retries is None else retries
        budget = max_tokens or self.settings.llm_max_tokens
        working = list(messages)
        last_error: Exception | None = None
        last_content = ""

        for attempt in range(1, max_retries + 2):
            response = await self.complete(
                working,
                temperature=temperature,
                max_tokens=budget,
                json_mode=True,
            )
            response.attempts = attempt
            last_content = response.content

            if response.finish_reason == "length":
                last_error = LLMResponseFormatError(
                    f"模型输出达到 max_tokens 上限（{budget}）被截断，JSON 不完整"
                )
                logger.warning("LLM 第 %s 次输出被截断（max_tokens=%s）", attempt, budget)
                budget = min(budget * 2, MAX_TOKEN_CEILING)
                working = [*messages, user(TRUNCATION_INSTRUCTION.format(limit=budget))]
                continue

            try:
                parsed = extract_json(response.content)
            except ValueError as exc:
                last_error = exc
                logger.warning("LLM 第 %s 次输出无法解析为 JSON：%s", attempt, exc)
                working = [
                    *messages,
                    assistant(truncate(response.content, 1200)),
                    user(JSON_REPAIR_INSTRUCTION),
                ]
                continue

            if not isinstance(parsed, expect):
                last_error = LLMResponseFormatError(
                    f"期望顶层为 {expect}，实际为 {type(parsed).__name__}",
                    detail={"content_preview": truncate(response.content, 500)},
                )
                working = [*messages, assistant(truncate(response.content, 1200)), user(JSON_REPAIR_INSTRUCTION)]
                continue

            response.parsed = parsed
            return response

        raise LLMResponseFormatError(
            f"模型连续 {max_retries + 1} 次未返回合法 JSON：{last_error}",
            detail={"content_preview": truncate(last_content, 800)},
        )

    async def aclose(self) -> None:  # pragma: no cover - 默认无资源可释放
        """释放底层连接资源（如 HTTP 会话）。"""
        return None

    # ------------------------------------------------------------------ #
    def connectivity_probe(self) -> tuple[list[LLMMessage], dict[str, Any]]:
        """连通性探针的请求参数（厂商可覆写）。

        返回的 kwargs 会原样展开给 :meth:`complete`，让适配器有机会关掉
        「先想再答」这类会让极小请求拿不到正文的行为。
        """
        return [user(PROBE_PROMPT)], {"max_tokens": PROBE_MAX_TOKENS, "temperature": 0.0}

    async def health_check(self) -> bool:
        """轻量连通性检查：真实发一次最小请求。"""
        if not self.available:
            return False
        messages, kwargs = self.connectivity_probe()
        try:
            await self.complete(messages, **kwargs)
            return True
        except LLMError:
            return False


def build_json_preview(data: Any, limit: int = 4000) -> str:
    """截断超长 JSON，控制 Prompt 体积。"""
    return truncate(dump_json(data, indent=None), limit)
