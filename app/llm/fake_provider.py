"""离线假 Provider：用于单元测试与无网络演示。

它不会真正调用任何接口，而是根据 Prompt 中的 [TASK:xxx] 标记返回
结构稳定的假数据，从而让「LLM 链路」可以在 CI 中确定性验证。
注意：生产环境请勿使用（数据无意义）。
"""
from __future__ import annotations

import json
from typing import Any

from app.core.config import Settings
from app.core.utils import Timer
from app.llm.base import LLMMessage, LLMProvider, LLMResponse
from app.llm.prompts import TASK_REQUIREMENT_EXTRACTION, TASK_SCENARIO_ENRICHMENT

_FAKE_REQUIREMENT_DOC: dict[str, Any] = {
    "title": "离线示例需求文档",
    "summary": "用于演示 LLM 链路的假数据，不代表真实业务。",
    "items": [
        {
            "id": "REQ-001",
            "title": "用户注册",
            "module": "用户中心",
            "description": "用户提交手机号与密码完成注册。",
            "priority": "P0",
            "requirement_type": "functional",
            "fields": [
                {
                    "name": "phone",
                    "label": "手机号",
                    "data_type": "string",
                    "required": True,
                    "nullable": False,
                    "min_length": 11,
                    "max_length": 11,
                    "pattern": "^1[3-9]\\d{9}$",
                    "description": "中国大陆手机号",
                },
                {
                    "name": "age",
                    "label": "年龄",
                    "data_type": "integer",
                    "required": False,
                    "min_value": 18,
                    "max_value": 120,
                    "unit": "岁",
                    "description": "用户年龄",
                },
            ],
            "business_rules": ["同一手机号不可重复注册"],
            "preconditions": ["系统正常运行", "短信通道可用"],
            "main_flow": ["进入注册页", "填写手机号与密码", "获取并输入验证码", "提交注册"],
            "alternative_flows": ["手机号已注册时提示直接登录", "验证码错误可重新获取"],
            "exceptions": ["短信通道异常", "数据库写入失败"],
            "acceptance_criteria": ["注册成功后自动登录并跳转首页"],
            "source_ref": "假数据",
        }
    ],
}

_FAKE_SCENARIO_CASES: dict[str, Any] = {
    "cases": [
        {
            "title": "并发提交同一手机号注册请求",
            "case_type": "异常",
            "priority": "P1",
            "preconditions": ["使用同一手机号"],
            "steps": [
                {"action": "并发发送两次注册请求", "expected": "仅一次成功，另一次提示手机号已注册"}
            ],
            "expected_result": "数据库不产生重复用户记录",
            "test_data": {"phone": "13800000000"},
        },
        {
            "title": "弱网环境下重复点击提交按钮",
            "case_type": "场景",
            "priority": "P2",
            "preconditions": ["模拟弱网"],
            "steps": [{"action": "连续点击提交 5 次", "expected": "按钮置灰并只提交一次"}],
            "expected_result": "不产生重复注册记录",
            "test_data": {},
        },
    ]
}


class FakeProvider(LLMProvider):
    """确定性 Provider，按任务标记返回预置 JSON。"""

    name = "fake"
    supports_json_mode = True

    def __init__(self, settings: Settings | None = None, *, scripted: dict[str, Any] | None = None) -> None:
        super().__init__(settings)
        self.scripted: dict[str, Any] = scripted or {
            TASK_REQUIREMENT_EXTRACTION: _FAKE_REQUIREMENT_DOC,
            TASK_SCENARIO_ENRICHMENT: _FAKE_SCENARIO_CASES,
        }
        self.calls: list[list[LLMMessage]] = []

    @property
    def available(self) -> bool:
        return True

    @property
    def model(self) -> str:
        return "fake-model"

    def _resolve(self, messages: list[LLMMessage]) -> Any:
        blob = "\n".join(message.content for message in messages)
        for marker, payload in self.scripted.items():
            if marker in blob:
                return payload
        return {"_fake": True, "note": "FakeProvider 未匹配到任务标记，返回占位对象。"}

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
        extra_body: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.calls.append(list(messages))

        with Timer() as timer:
            payload = self._resolve(messages)
        return LLMResponse(
            content=json.dumps(payload, ensure_ascii=False),
            model="fake-model",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            elapsed_ms=timer.elapsed_ms,
            raw={"fake": True},
        )

    async def health_check(self) -> bool:
        return True
