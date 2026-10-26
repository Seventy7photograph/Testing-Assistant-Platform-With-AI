"""离线假 Provider：用于单元测试与无网络演示。

它不会真正调用任何接口，而是根据 Prompt 中的 [TASK:xxx] 标记返回
结构稳定的假数据，从而让「LLM 链路」可以在 CI 中确定性验证。
注意：生产环境请勿使用（数据无意义）。
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import Settings
from app.core.utils import Timer
from app.llm.base import LLMMessage, LLMProvider, LLMResponse
from app.llm.prompts import (
    TASK_API_CASE_REVIEW,
    TASK_AUTOMATION_FAILURE_ASSERTION,
    TASK_AUTOMATION_FIXTURE_RECIPE,
    TASK_AUTOMATION_OPERATION_GAP,
    TASK_AUTOMATION_SCRIPT_REVIEW,
    TASK_GENERATION_REVIEW,
    TASK_REQUIREMENT_EXTRACTION,
    TASK_SCENARIO_ENRICHMENT,
)

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
            "evidence_quotes": ["手机号"],
            "claim_status": "verified",
            "uncertainty_reason": "",
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
            "evidence_quotes": ["手机号"],
            "claim_status": "verified",
            "uncertainty_reason": "",
        },
        {
            "title": "弱网环境下重复点击提交按钮",
            "case_type": "场景",
            "priority": "P2",
            "preconditions": ["模拟弱网"],
            "steps": [{"action": "连续点击提交 5 次", "expected": "按钮置灰并只提交一次"}],
            "expected_result": "不产生重复注册记录",
            "test_data": {},
            "evidence_quotes": ["手机号"],
            "claim_status": "verified",
            "uncertainty_reason": "",
        },
    ]
}

#: 生成阶段复核的假响应：既有意见，也有补充用例（供 review / enhance 两种模式复用）。
_FAKE_REVIEW: dict[str, Any] = {
    "findings": [
        {
            "severity": "warning",
            "target": "手机号 有效等价类",
            "issue": "假数据：规则用例未覆盖「手机号已注册」这一分支，而业务规则明确要求提示直接登录。",
            "suggestion": "补充一条「手机号已注册时提交」的异常用例。",
            "evidence_quotes": ["手机号"],
            "claim_status": "verified",
            "uncertainty_reason": "",
        },
        {
            "severity": "info",
            "target": "年龄",
            "issue": "假数据：年龄字段允许为空，但需求未说明为空时按什么规则处理。",
            "suggestion": "确认空值语义后再决定是否需要单独的用例。",
            "evidence_quotes": ["年龄"],
            "claim_status": "verified",
            "uncertainty_reason": "",
        },
    ],
    "cases": [
        {
            "title": "手机号已注册时提交注册请求",
            "method": "cause_effect",
            "case_type": "异常",
            "priority": "P1",
            "preconditions": ["该手机号已存在"],
            "steps": [{"action": "用已注册手机号提交注册", "expected": "提示直接登录，不创建新用户"}],
            "expected_result": "不产生重复用户记录",
            "test_data": {"phone": "13800000000"},
            "reason": "业务规则「同一手机号不可重复注册」在规则用例里没有对应用例。",
            "evidence_quotes": ["手机号"],
            "claim_status": "verified",
            "uncertainty_reason": "",
        },
        {
            "title": "并发提交同一手机号",
            "method": "scenario",
            "case_type": "异常",
            "priority": "P1",
            "preconditions": [],
            "steps": [{"action": "并发发送两次注册", "expected": "仅一次成功"}],
            "expected_result": "数据库无重复记录",
            "test_data": {},
            "reason": "并发属于规则方法覆盖不到的测试点。",
            "evidence_quotes": ["手机号"],
            "claim_status": "inferred",
            "uncertainty_reason": "并发场景由测试经验推断",
        },
    ],
}

_FAKE_API_CASE_REVIEW: dict[str, Any] = {
    "findings": [
        {
            "severity": "warning",
            "kind": "case_gap",
            "operation_id": "createPet",
            "target": "request.body.status",
            "issue": "假数据：可补充状态迁移与重复创建的人工场景。",
            "suggestion": "人工确认业务是否允许重复创建同名宠物，再补充对应用例。",
            "source_ref": "paths./pets.post",
            "claim_status": "inferred",
            "uncertainty_reason": "规范未声明业务唯一性规则。",
        }
    ]
}

_FAKE_AUTOMATION_OPERATION_GAP: dict[str, Any] = {
    "summary": "假数据：存在 operation 尚未进入自动化资产。",
    "findings": [
        {
            "severity": "warning",
            "operation_id": "createPet",
            "target": "response.201",
            "issue": "假数据：未覆盖创建后的标识返回。",
            "suggestion": "人工确认创建响应字段后补充断言场景。",
            "rationale": "OpenAPI 响应包含 id 与 name。",
            "source_ref": "paths./pets.post",
            "claim_status": "inferred",
        }
    ],
}

_FAKE_AUTOMATION_FAILURE_ASSERTION: dict[str, Any] = {
    "summary": "假数据：失败更像断言不足，而非明确产品缺陷。",
    "findings": [
        {
            "severity": "warning",
            "case_id": "API-POST-83D9E0C255",
            "operation_id": "createPet",
            "target": "response.body.id",
            "issue": "假数据：失败信息不足以定位响应字段。",
            "suggestion": "人工确认后补充 id 类型与存在性断言。",
            "rationale": "当前失败消息只包含状态码差异。",
            "source_ref": "paths./pets.post",
            "claim_status": "inferred",
            "proposed_assertion": {
                "kind": "json",
                "path": "$.id",
                "operator": "type",
                "expected": "integer",
                "description": "创建成功后返回整数 id",
                "source_ref": "paths./pets.post",
            },
        }
    ],
}

_FAKE_AUTOMATION_FIXTURE_RECIPE: dict[str, Any] = {
    "summary": "假数据：接口测试 fixture 与数据配方。",
    "recipe": {
        "summary": "使用环境变量和本地测试数据完成接口准备。",
        "environment_variables": [
            {
                "name": "BASE_URL",
                "description": "目标服务地址",
                "secret": False,
                "placeholder": "http://127.0.0.1:8000",
            },
            {
                "name": "AUTH_TOKEN",
                "description": "测试环境授权 Token",
                "secret": True,
                "placeholder": "AUTH_TOKEN",
            },
        ],
        "fixtures": [
            {
                "name": "pet_fixture",
                "purpose": "准备可查询的测试宠物",
                "setup": ["在测试环境创建一只 available 状态的宠物"],
                "data": {"name": "fixture-pet", "status": "available"},
            }
        ],
        "test_data": [
            {
                "case_id": "API-GET-6EB7EEAE24",
                "title": "列表查询数据",
                "data": {"limit": 1},
                "notes": "假数据，仅用于离线演示",
            }
        ],
        "preconditions": ["测试环境可访问", "AUTH_TOKEN 由本地环境注入"],
        "execution_notes": ["运行前人工核对 fixture 清理策略"],
        "warnings": ["假数据不代表真实业务约束"],
    },
}

_FAKE_AUTOMATION_SCRIPT_REVIEW: dict[str, Any] = {
    "summary": "假数据：脚本结构清晰，建议补充断言来源说明。",
    "findings": [
        {
            "severity": "info",
            "target": "tests/test_api_cases.py",
            "issue": "假数据：断言失败信息可以更明确。",
            "suggestion": "人工评估是否补充断言 source_ref。",
            "rationale": "当前失败消息包含 case_id 与预期状态。",
            "source_ref": "tests/test_api_cases.py",
            "claim_status": "inferred",
        }
    ],
}


def _first_quoted_value(blob: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]+)"', blob)
    return match.group(1) if match else ""


def _first_python_file(blob: str) -> str:
    match = re.search(r'"(tests/[^"]+\.py)"', blob) or re.search(r'"([^"]+\.py)"', blob)
    return match.group(1) if match else "tests/test_api_cases.py"


def _dynamic_automation_payload(marker: str, messages: list[LLMMessage]) -> dict[str, Any] | None:
    user_blob = str(messages[-1].content) if messages else ""
    if marker == TASK_AUTOMATION_OPERATION_GAP:
        operation_id = _first_quoted_value(user_blob, "operation_id")
        source_ref = _first_quoted_value(user_blob, "source_ref")
        if operation_id and source_ref:
            return {
                "summary": "假数据：存在 operation 尚未进入自动化资产。",
                "findings": [
                    {
                        "severity": "warning",
                        "operation_id": operation_id,
                        "target": "request / response contract",
                        "issue": "假数据：该 operation 尚未进入当前自动化资产。",
                        "suggestion": "人工确认后补充成功路径与错误响应场景。",
                        "rationale": "该 operation 出现在未覆盖清单中。",
                        "source_ref": source_ref,
                        "claim_status": "inferred",
                    }
                ],
            }
    if marker == TASK_AUTOMATION_FAILURE_ASSERTION:
        case_id = _first_quoted_value(user_blob, "case_id")
        operation_id = _first_quoted_value(user_blob, "operation_id")
        source_ref = _first_quoted_value(user_blob, "source_ref")
        if case_id and operation_id and source_ref:
            return {
                "summary": "假数据：失败更像断言不足，而非明确产品缺陷。",
                "findings": [
                    {
                        "severity": "warning",
                        "case_id": case_id,
                        "operation_id": operation_id,
                        "target": "response contract",
                        "issue": "假数据：现有失败消息不足以区分环境问题与断言缺口。",
                        "suggestion": "人工确认后补充错误响应字段断言。",
                        "rationale": "当前只有状态码差异和有限断言摘要。",
                        "source_ref": source_ref,
                        "claim_status": "inferred",
                        "proposed_assertion": {
                            "kind": "json",
                            "path": "$.code",
                            "operator": "exists",
                            "expected": True,
                            "description": "错误响应包含可诊断的错误码",
                            "source_ref": source_ref,
                        },
                    }
                ],
            }
    if marker == TASK_AUTOMATION_FIXTURE_RECIPE:
        case_id = _first_quoted_value(user_blob, "case_id")
        payload = json.loads(json.dumps(_FAKE_AUTOMATION_FIXTURE_RECIPE))
        if case_id and payload.get("recipe", {}).get("test_data"):
            payload["recipe"]["test_data"][0]["case_id"] = case_id
        return payload
    if marker == TASK_AUTOMATION_SCRIPT_REVIEW:
        source_ref = _first_python_file(user_blob)
        payload = json.loads(json.dumps(_FAKE_AUTOMATION_SCRIPT_REVIEW))
        payload["findings"][0]["source_ref"] = source_ref
        payload["findings"][0]["target"] = source_ref
        return payload
    return None


class FakeProvider(LLMProvider):
    """确定性 Provider，按任务标记返回预置 JSON。"""

    name = "fake"
    supports_json_mode = True

    def __init__(self, settings: Settings | None = None, *, scripted: dict[str, Any] | None = None) -> None:
        super().__init__(settings)
        self._use_dynamic_automation = scripted is None
        self.scripted: dict[str, Any] = scripted or {
            TASK_REQUIREMENT_EXTRACTION: _FAKE_REQUIREMENT_DOC,
            TASK_SCENARIO_ENRICHMENT: _FAKE_SCENARIO_CASES,
            TASK_GENERATION_REVIEW: _FAKE_REVIEW,
            TASK_API_CASE_REVIEW: _FAKE_API_CASE_REVIEW,
            TASK_AUTOMATION_OPERATION_GAP: _FAKE_AUTOMATION_OPERATION_GAP,
            TASK_AUTOMATION_FAILURE_ASSERTION: _FAKE_AUTOMATION_FAILURE_ASSERTION,
            TASK_AUTOMATION_FIXTURE_RECIPE: _FAKE_AUTOMATION_FIXTURE_RECIPE,
            TASK_AUTOMATION_SCRIPT_REVIEW: _FAKE_AUTOMATION_SCRIPT_REVIEW,
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
                if self._use_dynamic_automation:
                    dynamic = _dynamic_automation_payload(marker, messages)
                    if dynamic is not None:
                        return dynamic
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
