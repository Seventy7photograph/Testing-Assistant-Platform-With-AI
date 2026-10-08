"""大模型厂商 / 模型「匹配选项」目录。

前端下拉框的候选项统一来自这里，而不是前端硬编码：
新增厂商或模型只需在 catalog 里加一条，前后端同时生效。
"""
from __future__ import annotations

from typing import Any

LLM_PROVIDER_CATALOG: list[dict[str, Any]] = [
    {
        "name": "deepseek",
        "label": "DeepSeek 官方",
        "description": "OpenAI 兼容协议，官方直连，默认选项。",
        "requires_key": True,
        "requires_base_url": False,
        "allow_custom_model": True,
        "default_base_url": "https://api.deepseek.com",
        "default_model": "deepseek-flash",
        "models": [
            {
                "value": "deepseek-flash",
                "label": "deepseek-flash（V4.1-Flash｜1M 上下文｜默认开思考模式）",
                "base_url": "https://api.deepseek.com",
            },
            {
                "value": "deepseek-v4-pro",
                "label": "deepseek-v4-pro（V4-Pro｜深度推理，单价更高）",
                "base_url": "https://api.deepseek.com",
            },
            {
                "value": "deepseek-chat",
                "label": "deepseek-chat（旧版别名｜不在官方模型列表中，非思考模式）",
                "base_url": "https://api.deepseek.com",
            },
        ],
    },
    {
        "name": "openai_compatible",
        "label": "OpenAI 兼容端点",
        "description": "任意提供 /chat/completions 的服务，如通义千问、智谱 GLM、Kimi、OpenAI。",
        "requires_key": True,
        "requires_base_url": True,
        "allow_custom_model": True,
        "default_base_url": "",
        "default_model": "",
        "models": [
            {
                "value": "qwen-plus",
                "label": "通义千问 qwen-plus",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            },
            {
                "value": "glm-4-plus",
                "label": "智谱 GLM-4-Plus",
                "base_url": "https://open.bigmodel.cn/api/paas/v4",
            },
            {
                "value": "moonshot-v1-8k",
                "label": "Kimi moonshot-v1-8k",
                "base_url": "https://api.moonshot.cn/v1",
            },
            {
                "value": "gpt-4o-mini",
                "label": "OpenAI gpt-4o-mini",
                "base_url": "https://api.openai.com/v1",
            },
        ],
    },
    {
        "name": "fake",
        "label": "离线假实现（演示 / 测试）",
        "description": "不联网、返回确定性假数据，仅用于演示与自动化测试。",
        "requires_key": False,
        "requires_base_url": False,
        "allow_custom_model": False,
        "default_base_url": "",
        "default_model": "fake-model",
        "models": [{"value": "fake-model", "label": "fake-model（离线确定性）", "base_url": ""}],
    },
    {
        "name": "none",
        "label": "纯规则引擎（不使用大模型）",
        "description": "完全不调用大模型，全部走内置规则引擎；适合离线或保密环境。",
        "requires_key": False,
        "requires_base_url": False,
        "allow_custom_model": False,
        "default_base_url": "",
        "default_model": "",
        "models": [],
    },
]


def provider_options() -> list[dict[str, Any]]:
    """返回全部厂商选项的深拷贝，避免调用方修改目录常量。"""
    return [dict(item) for item in LLM_PROVIDER_CATALOG]


def provider_option(name: str) -> dict[str, Any] | None:
    for item in LLM_PROVIDER_CATALOG:
        if item["name"] == name:
            return dict(item)
    return None
