"""大模型配置的 HTTP 契约。

界面提交的是「友好字段名」（provider / model / base_url ...），
服务端再映射到 Settings 的 llm_* 字段，避免把内部命名暴露给前端。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import LLMProviderName


class LLMModelOption(BaseModel):
    value: str
    label: str = ""
    base_url: str = ""


class LLMProviderOption(BaseModel):
    """厂商选项：含默认端点、默认模型与候选模型列表（匹配选项）。"""

    name: str
    label: str
    description: str = ""
    requires_key: bool = True
    requires_base_url: bool = False
    allow_custom_model: bool = True
    default_base_url: str = ""
    default_model: str = ""
    models: list[LLMModelOption] = Field(default_factory=list)


class LLMConfigInfo(BaseModel):
    provider: str
    model: str = ""
    base_url: str = ""
    api_key_configured: bool = False
    api_key_masked: str = ""
    timeout: float = 60.0
    max_retries: int = 2
    temperature: float = 0.2
    max_tokens: int = 8192
    available: bool = False
    degraded_reason: str = ""
    source: str = Field(default="env", description="env=来自 .env 基线；runtime=被界面覆盖")
    overridden_fields: list[str] = Field(default_factory=list)
    env_defaults: dict[str, Any] = Field(default_factory=dict)
    providers: list[LLMProviderOption] = Field(default_factory=list)


class LLMConfigUpdate(BaseModel):
    """保存运行时覆盖。字段为 None 表示「不修改」。"""

    model_config = ConfigDict(extra="forbid")

    provider: LLMProviderName | None = None
    model: str | None = Field(default=None, description="模型名；留空则沿用当前/默认")
    base_url: str | None = Field(default=None, description="OpenAI 兼容端点根地址")
    api_key: str | None = Field(
        default=None,
        description="不传=沿用现有 Key；传空字符串=清除已保存的 Key（回落到 .env）",
    )
    timeout: float | None = Field(default=None, gt=0, le=600)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=16, le=131072)


class LLMTestRequest(BaseModel):
    """连通性测试：不传则测「当前生效配置」，传了则测「未保存的表单值」。"""

    model_config = ConfigDict(extra="forbid")

    provider: LLMProviderName | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    timeout: float | None = Field(default=None, gt=0, le=600)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=16, le=131072)


class LLMTestResult(BaseModel):
    ok: bool
    provider: str
    model: str = ""
    elapsed_ms: int = 0
    message: str = ""
    reply: str = ""


class LLMModelList(BaseModel):
    source: str = Field(default="builtin", description="remote=来自远端 /models；builtin=内置目录")
    message: str = ""
    models: list[LLMModelOption] = Field(default_factory=list)


class PromptInfo(BaseModel):
    prompt_id: str
    version: str
    task: str
    input_boundary: str
    temperature: float
    model_scope: str
    change_log: list[str] = Field(default_factory=list)


class ModelRouteInfo(BaseModel):
    provider: str
    model: str
    task: str
    strategy: str
    quality_tier: str
    cost_tier: str
    rationale: str


class RoutingPolicyInfo(BaseModel):
    configured_strategy: str = "balanced"
    strategy: str = "balanced"
    routes: list[ModelRouteInfo] = Field(default_factory=list)
