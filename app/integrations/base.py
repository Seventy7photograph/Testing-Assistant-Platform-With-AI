"""外部系统集成抽象（预留，未实现）。

V1.0 只定义接口与占位实现：调用即返回 501 + 版本说明，
保证"架构预留"是真的可插拔，而不是事后返工。
"""
from __future__ import annotations

import abc

from pydantic import BaseModel, Field

from app.core.exceptions import FeatureNotAvailableError
from app.core.registry import Registry
from app.schemas.testcase import TestCaseSuite


class SyncResult(BaseModel):
    """同步结果。"""

    success: bool = False
    external_ids: list[str] = Field(default_factory=list)
    message: str = ""
    detail: dict = Field(default_factory=dict)


class ExternalSyncAdapter(abc.ABC):
    """测试管理平台适配器基类（禅道 / Jira / TestLink ...）。"""

    name: str = "base"
    label: str = "基础适配器"
    implemented: bool = False

    @abc.abstractmethod
    async def push_cases(
        self, suite: TestCaseSuite, *, project_key: str = "", options: dict | None = None
    ) -> SyncResult:
        """把用例集推送到外部平台。"""

    @abc.abstractmethod
    async def pull_requirements(self, *, project_key: str = "", options: dict | None = None) -> list[str]:
        """从外部平台拉取需求条目（用于上游需求自动同步）。"""

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """连通性与鉴权检查。"""


class _NotImplementedAdapter(ExternalSyncAdapter):
    implemented = False

    async def push_cases(self, suite: TestCaseSuite, *, project_key: str = "", options: dict | None = None) -> SyncResult:
        raise FeatureNotAvailableError(
            f"「{self.label}」集成当前版本尚未实现，请先导出 Excel 后手工导入。",
            detail={"adapter": self.name, "implemented": False},
        )

    async def pull_requirements(self, *, project_key: str = "", options: dict | None = None) -> list[str]:
        raise FeatureNotAvailableError(
            f"「{self.label}」需求拉取当前版本尚未实现。", detail={"adapter": self.name}
        )

    async def health_check(self) -> bool:
        return False


class ZentaoAdapter(_NotImplementedAdapter):
    name = "zentao"
    label = "禅道"


class JiraAdapter(_NotImplementedAdapter):
    name = "jira"
    label = "Jira"


INTEGRATION_REGISTRY: Registry[ExternalSyncAdapter] = Registry("外部集成适配器")
INTEGRATION_REGISTRY.register("zentao", ZentaoAdapter())
INTEGRATION_REGISTRY.register("jira", JiraAdapter())


def available_integrations() -> list[dict]:
    return [
        {"name": name, "label": adapter.label, "implemented": adapter.implemented}
        for name, adapter in INTEGRATION_REGISTRY.items()
    ]


def get_adapter(name: str) -> ExternalSyncAdapter:
    return INTEGRATION_REGISTRY.get((name or "").strip().lower())
