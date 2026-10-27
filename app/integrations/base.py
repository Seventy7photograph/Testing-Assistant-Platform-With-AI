"""外部同步适配器抽象与注册表。"""
from __future__ import annotations

import abc
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.core.exceptions import ConflictError
from app.core.registry import Registry
from app.schemas.integrations import ExternalRequirement, ExternalStatus
from app.schemas.testcase import TestCaseSuite


class SyncResult(BaseModel):
    success: bool = False
    external_ids: list[str] = Field(default_factory=list)
    message: str = ""
    warnings: list[str] = Field(default_factory=list)
    detail: dict = Field(default_factory=dict)


class ExternalSyncAdapter(abc.ABC):
    name = "base"
    label = "基础适配器"
    implemented = True

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        client_factory: Callable[..., httpx.AsyncClient] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.transport = transport
        self.client_factory = client_factory or httpx.AsyncClient

    @abc.abstractmethod
    async def push_cases(
        self,
        suite: TestCaseSuite,
        *,
        project_key: str = "",
        options: dict[str, Any] | None = None,
    ) -> SyncResult:
        """把用例集推送到外部平台。"""

    @abc.abstractmethod
    async def pull_requirements(
        self,
        *,
        project_key: str = "",
        options: dict[str, Any] | None = None,
    ) -> list[ExternalRequirement]:
        """从外部平台拉取需求。"""

    @abc.abstractmethod
    async def read_status(
        self,
        external_id: str,
        *,
        options: dict[str, Any] | None = None,
    ) -> ExternalStatus:
        """回读外部需求状态。"""

    @abc.abstractmethod
    async def health_check(
        self,
        *,
        project_key: str = "",
        options: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        """返回 (可用, 可展示原因)。"""

    def _client(self, timeout: float = 20.0) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(timeout, connect=8.0),
            "follow_redirects": True,
        }
        if self.transport is not None:
            kwargs["transport"] = self.transport
        return self.client_factory(**kwargs)

    @staticmethod
    def fixture_requirements(options: dict[str, Any] | None) -> list[ExternalRequirement]:
        raw = (options or {}).get("requirements")
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise ConflictError("离线 fixture 的 requirements 必须是数组。")
        return [ExternalRequirement.model_validate(item) for item in raw]

    @staticmethod
    def missing_config(label: str, field: str) -> ConflictError:
        return ConflictError(
            f"{label} 尚未配置 {field}，本次未发起任何外部变更。",
            detail={"integration": label, "missing": field, "state": "not_configured"},
        )


ADAPTER_BUILDERS: Registry[Callable[..., ExternalSyncAdapter]] = Registry("外部集成适配器")
# 兼容 v2.x 的公开符号；新代码应使用 build_adapter。
INTEGRATION_REGISTRY = ADAPTER_BUILDERS


def adapter_available() -> list[dict[str, Any]]:
    return [
        {"name": name, "label": builder(None).label, "implemented": True}
        for name, builder in ADAPTER_BUILDERS.items()
    ]


def build_adapter(
    name: str,
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    client_factory: Callable[..., httpx.AsyncClient] | None = None,
) -> ExternalSyncAdapter:
    normalized = (name or "").strip().lower()
    builder = ADAPTER_BUILDERS.get(normalized)
    return builder(
        settings,
        transport=transport,
        client_factory=client_factory,
    )


def available_integrations() -> list[dict[str, Any]]:
    return adapter_available()


def get_adapter(name: str, settings: Settings | None = None) -> ExternalSyncAdapter:
    return build_adapter(name, settings)


__all__ = [
    "ADAPTER_BUILDERS",
    "ExternalSyncAdapter",
    "INTEGRATION_REGISTRY",
    "SyncResult",
    "available_integrations",
    "build_adapter",
    "get_adapter",
]
