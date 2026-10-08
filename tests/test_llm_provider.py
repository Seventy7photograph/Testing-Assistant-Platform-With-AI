"""LLM Provider 单测：协议组装、错误映射、JSON 重试、降级策略。

全部使用 httpx.AsyncClient 替身，不发真实网络请求。
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from app.core.exceptions import LLMError, LLMNotConfiguredError, LLMResponseFormatError
from app.llm import openai_compatible
from app.llm.base import system, user
from app.llm.deepseek_provider import DeepSeekProvider
from app.llm.fake_provider import FakeProvider
from app.llm.factory import build_llm_provider
from app.llm.null_provider import NullProvider
from app.llm.prompts import build_requirement_messages, build_scenario_messages

MESSAGES = [system("你是测试架构师"), user("请输出 JSON")]


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, payload: dict | None = None, text: str | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {}, ensure_ascii=False)

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _FakeClient:
    def __init__(self, outcomes: list, captured: list) -> None:
        self.outcomes = outcomes
        self.captured = captured

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url, json=None, headers=None):  # noqa: A002 - 对齐 httpx 签名
        self.captured.append({"url": url, "payload": json, "headers": headers})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def patch_client(monkeypatch, outcomes: list) -> list:
    captured: list = []
    monkeypatch.setattr(
        openai_compatible.httpx, "AsyncClient", lambda **kwargs: _FakeClient(outcomes, captured)
    )
    return captured


def completion(content: str, *, model: str = "deepseek-chat") -> _FakeResponse:
    return _FakeResponse(
        payload={
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
        }
    )


def truncated(content: str = '{"items": [') -> _FakeResponse:
    """``finish_reason=length``：模型在输出上限处被截断，JSON 一定不完整。"""
    return _FakeResponse(
        payload={
            "model": "deepseek-flash",
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "length"}
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4096, "total_tokens": 4108},
        }
    )


def provider(**overrides) -> DeepSeekProvider:
    base = {"llm_provider": "deepseek", "llm_api_key": "test-key", "llm_base_url": "https://api.deepseek.com", "llm_model": "deepseek-chat", "llm_max_retries": 2}
    base.update(overrides)
    return DeepSeekProvider(Settings(**base))


async def test_complete_builds_openai_compatible_request(monkeypatch) -> None:
    captured = patch_client(monkeypatch, [completion('{"ok": true}')])
    response = await provider().complete(MESSAGES, json_mode=True, temperature=0.1, max_tokens=128)

    assert captured[0]["url"] == "https://api.deepseek.com/chat/completions"
    assert captured[0]["headers"]["Authorization"] == "Bearer test-key"
    assert captured[0]["payload"]["response_format"] == {"type": "json_object"}
    assert captured[0]["payload"]["temperature"] == 0.1
    assert captured[0]["payload"]["max_tokens"] == 128
    assert response.content == '{"ok": true}'
    assert response.usage["total_tokens"] == 20


async def test_http_error_maps_to_llm_error(monkeypatch) -> None:
    patch_client(monkeypatch, [_FakeResponse(status_code=401, payload={"error": "invalid key"})])
    with pytest.raises(LLMError) as excinfo:
        await provider().complete(MESSAGES)
    assert "401" in excinfo.value.message


async def test_timeout_maps_to_llm_error(monkeypatch) -> None:
    patch_client(monkeypatch, [httpx.TimeoutException("timeout")])
    with pytest.raises(LLMError) as excinfo:
        await provider().complete(MESSAGES)
    assert "超时" in excinfo.value.message


async def test_missing_choices_raises_format_error(monkeypatch) -> None:
    patch_client(monkeypatch, [_FakeResponse(payload={"model": "x"})])
    with pytest.raises(LLMResponseFormatError):
        await provider().complete(MESSAGES)


async def test_empty_content_raises_format_error(monkeypatch) -> None:
    patch_client(monkeypatch, [completion("   ")])
    with pytest.raises(LLMResponseFormatError):
        await provider().complete(MESSAGES)


def empty_truncated() -> _FakeResponse:
    """正文为空 + finish_reason=length：典型「预算被思维链吃光」形态。"""
    return _FakeResponse(
        payload={
            "model": "deepseek-flash",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "", "reasoning_content": "思考" * 30},
                    "finish_reason": "length",
                }
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 16, "total_tokens": 36},
        }
    )


async def test_empty_content_error_explains_why(monkeypatch) -> None:
    """空正文必须说清原因，否则使用者不知道要动 max_tokens 还是关思考模式。"""
    patch_client(monkeypatch, [empty_truncated()])
    with pytest.raises(LLMResponseFormatError) as excinfo:
        await provider().complete(MESSAGES, max_tokens=16)
    assert "思考过程" in excinfo.value.message
    assert "max_tokens" in excinfo.value.message


def test_deepseek_probe_disables_thinking_mode() -> None:
    """连通性探针必须显式关掉 DeepSeek 的思考模式。

    回归：《思考模式》文档写明该开关**默认打开**，模型先输出思维链再输出正文。
    探针只给几十个 token，预算会被整段用掉、content 为空，
    于是一次完全正常的连通被误报成「连接失败 · 大模型返回内容为空」。
    """
    messages, kwargs = provider().connectivity_probe()
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert kwargs["max_tokens"] >= 32
    assert messages and messages[0].content


def test_generic_probe_budget_suits_thinking_models() -> None:
    """通用 Provider 的探针预算要够思考型模型先想完再答。"""
    from app.llm.base import PROBE_MAX_TOKENS
    from app.llm.openai_compatible import OpenAICompatibleProvider

    instance = OpenAICompatibleProvider(
        Settings(llm_api_key="k", llm_base_url="https://example.com/v1", llm_model="m")
    )
    _, kwargs = instance.connectivity_probe()
    assert kwargs["max_tokens"] == PROBE_MAX_TOKENS
    assert PROBE_MAX_TOKENS >= 256, "预算太小会让思考型模型返回空正文"


async def test_complete_json_retries_after_invalid_output(monkeypatch) -> None:
    captured = patch_client(
        monkeypatch,
        [completion("抱歉，我无法输出 JSON。"), completion('{"items": [{"title": "注册"}]}')],
    )
    response = await provider().complete_json(MESSAGES)

    assert response.parsed == {"items": [{"title": "注册"}]}
    assert response.attempts == 2
    assert len(captured) == 2
    # 第二次调用应带上"修复 JSON"的追加消息
    assert any("JSON" in message["content"] for message in captured[1]["payload"]["messages"][-1:])


async def test_complete_json_raises_after_retries_exhausted(monkeypatch) -> None:
    patch_client(monkeypatch, [completion("no json here"), completion("still no json"), completion("nope")])
    with pytest.raises(LLMResponseFormatError) as excinfo:
        await provider(llm_max_retries=2).complete_json(MESSAGES)
    assert "3 次" in excinfo.value.message


async def test_complete_json_escalates_output_budget_when_truncated(monkeypatch) -> None:
    """被截断时必须抬高 max_tokens 重试，而不是把同一个必然被截断的请求重跑一遍。

    回归：真实走查中 deepseek-flash 会在 4096 token 的输出预算里花掉 ~2200 个推理 token，
    结构化 JSON 必然被截断；旧实现三次重试完全相同，只会白烧三次额度后降级。
    """
    captured = patch_client(
        monkeypatch,
        [truncated('{"items": [{"title": "注册"'), completion('{"items": [{"title": "注册"}]}')],
    )
    response = await provider(llm_max_retries=2, llm_max_tokens=4096).complete_json(MESSAGES)

    assert response.parsed == {"items": [{"title": "注册"}]}
    assert response.attempts == 2
    assert captured[0]["payload"]["max_tokens"] == 4096
    assert captured[1]["payload"]["max_tokens"] == 8192, "截断后应抬高输出上限"
    # 截断要走「请精简」指令，而不是复用「JSON 修复」指令
    assert "截断" in captured[1]["payload"]["messages"][-1]["content"]


async def test_complete_json_reports_truncation_after_exhausting_retries(monkeypatch) -> None:
    captured = patch_client(monkeypatch, [truncated("a"), truncated("b"), truncated("c")])
    with pytest.raises(LLMResponseFormatError) as excinfo:
        await provider(llm_max_retries=2, llm_max_tokens=4096).complete_json(MESSAGES)

    assert "截断" in excinfo.value.message
    assert [item["payload"]["max_tokens"] for item in captured] == [4096, 8192, 16384]


async def test_complete_json_rejects_wrong_top_level_type(monkeypatch) -> None:
    patch_client(monkeypatch, [completion("[1,2,3]"), completion("[1,2,3]"), completion("[1,2,3]")])
    with pytest.raises(LLMResponseFormatError):
        await provider(llm_max_retries=1).complete_json(MESSAGES, expect=dict)


async def test_deepseek_default_base_url(monkeypatch) -> None:
    instance = DeepSeekProvider(Settings(llm_api_key="k", llm_base_url="", llm_model=""))
    assert instance.endpoint == "https://api.deepseek.com/chat/completions"
    assert instance.model == "deepseek-flash"


# --------------------------------------------------------------------------- #
# 降级与占位 Provider
# --------------------------------------------------------------------------- #
def test_factory_degrades_to_null_without_key() -> None:
    instance = build_llm_provider(Settings(llm_provider="deepseek", llm_api_key=""))
    assert isinstance(instance, NullProvider)
    assert instance.available is False
    assert "LLM_API_KEY" in instance.degraded_reason


def test_factory_returns_deepseek_with_key() -> None:
    instance = build_llm_provider(Settings(llm_provider="deepseek", llm_api_key="k"))
    assert isinstance(instance, DeepSeekProvider) and instance.available


def test_factory_supports_fake_provider() -> None:
    assert isinstance(build_llm_provider(Settings(llm_provider="fake")), FakeProvider)


def test_factory_unknown_provider_degrades() -> None:
    instance = build_llm_provider(Settings.model_construct(llm_provider="mystery", llm_api_key="k"))
    assert isinstance(instance, NullProvider)


async def test_null_provider_raises() -> None:
    instance = NullProvider(Settings(), reason="测试原因")
    with pytest.raises(LLMNotConfiguredError):
        await instance.complete(MESSAGES)
    with pytest.raises(LLMNotConfiguredError):
        await instance.complete_json(MESSAGES)
    assert await instance.health_check() is False


async def test_fake_provider_returns_task_specific_payload(settings) -> None:
    instance = FakeProvider(settings)
    response = await instance.complete_json(build_requirement_messages("测试需求", title="t", max_items=3))
    assert response.parsed["items"][0]["title"] == "用户注册"

    scenario = await instance.complete_json(
        build_scenario_messages({"id": "REQ-001"}, existing_titles=["a"], max_cases=3)
    )
    assert isinstance(scenario.parsed["cases"], list)

    unknown = await instance.complete_json([user("无任务标记")])
    assert unknown.parsed.get("_fake") is True
