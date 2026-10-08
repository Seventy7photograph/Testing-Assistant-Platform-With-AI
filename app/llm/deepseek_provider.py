"""DeepSeek 适配器（V1.0 默认 Provider）。

接口文档：https://api-docs.deepseek.com/  （OpenAI 兼容协议）
说明：默认 base_url 为 https://api.deepseek.com，请求路径 /chat/completions。
默认模型为 deepseek-flash；如需切换，只需改环境变量 LLM_MODEL
（候选见 app/llm/catalog.py，例如 deepseek-v4-pro）。
"""
from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.llm.base import LLMMessage, PROBE_PROMPT, user
from app.llm.openai_compatible import OpenAICompatibleProvider

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek 官方 API 适配。"""

    name = "deepseek"
    supports_json_mode = True

    def __init__(self, settings: Settings | None = None, *, model: str | None = None) -> None:
        super().__init__(settings, base_url=None, model=model)
        if not self._base_url or self._base_url == "https://api.openai.com":
            self._base_url = DEFAULT_BASE_URL
        if not self._model:
            self._model = DEFAULT_MODEL

    def connectivity_probe(self) -> tuple[list[LLMMessage], dict[str, Any]]:
        """DeepSeek V4 默认开启思考模式，探针必须显式关掉。

        官方文档《思考模式》：开关为``{"thinking": {"type": "enabled/disabled"}}``，
        **默认打开**。开着的时候模型先输出思维链再输出正文，而探针只给几十个 token，
        预算会整段花在推理上、``content`` 为空——探针于是把「链路正常」误报成
        「连接失败 · 大模型返回内容为空」。
        """
        return [user(PROBE_PROMPT)], {
            "max_tokens": 64,
            "temperature": 0.0,
            "extra_body": {"thinking": {"type": "disabled"}},
        }
