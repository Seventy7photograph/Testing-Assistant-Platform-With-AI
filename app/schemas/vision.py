"""图片识别通道的接口契约（设置页「图片识别」面板）。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VisionProviderOption(BaseModel):
    name: str
    label: str
    description: str = ""
    requires_key: bool = False
    requires_url: bool = False
    allow_model: bool = False
    allow_mode: bool = False


class VisionConfigInfo(BaseModel):
    """当前生效的图片识别配置 + 实际选中的通道（含不可用原因）。"""

    provider: str = "auto"
    mode: str = "text"
    model: str = ""
    base_url: str = ""
    api_key_configured: bool = False
    api_key_masked: str = ""
    cloud_url_configured: bool = False
    ocr_backend: str = ""
    languages: str = ""
    max_images: int = 20
    max_side: int = 1600
    min_pixels: int = 4096

    extractor: str = ""
    label: str = ""
    kind: str = ""
    available: bool = False
    degraded_reason: str = ""
    local_ocr_backend: str = ""
    local_ocr_hint: str = ""

    source: str = Field(default="env", description="env=来自 .env 基线；runtime=被界面覆盖")
    overridden_fields: list[str] = Field(default_factory=list)
    env_defaults: dict[str, Any] = Field(default_factory=dict)
    providers: list[VisionProviderOption] = Field(default_factory=list)
    modes: list[dict[str, str]] = Field(default_factory=list)


class VisionConfigUpdate(BaseModel):
    """界面可覆盖的图片识别配置子集；省略=不修改，空字符串=清除该覆盖。"""

    model_config = ConfigDict(extra="ignore")

    provider: str | None = None
    mode: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    cloud_url: str | None = None
    cloud_key: str | None = None
    ocr_backend: str | None = None
    languages: str | None = None
    max_images: int | None = Field(default=None, ge=1, le=200)
    max_side: int | None = Field(default=None, ge=200, le=6000)
    min_pixels: int | None = Field(default=None, ge=0, le=10_000_000)


class VisionTestResult(BaseModel):
    ok: bool
    provider: str = ""
    extractor: str = ""
    mode: str = ""
    elapsed_ms: int = 0
    message: str = ""
    sample: str = Field(default="", description="识别返回内容的片段（用于判断通道是否真的可用）")
