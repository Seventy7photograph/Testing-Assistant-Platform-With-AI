"""外部系统同步适配器（v3.0：Jira / 禅道）。"""
from app.integrations.base import (
    INTEGRATION_REGISTRY,
    ExternalSyncAdapter,
    SyncResult,
    available_integrations,
    build_adapter,
    get_adapter,
)
from app.integrations.jira import JiraAdapter
from app.integrations.zentao import ZentaoAdapter

__all__ = [
    "INTEGRATION_REGISTRY",
    "ExternalSyncAdapter",
    "JiraAdapter",
    "SyncResult",
    "ZentaoAdapter",
    "available_integrations",
    "build_adapter",
    "get_adapter",
]
