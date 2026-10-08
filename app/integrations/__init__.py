"""外部系统集成（架构预留，V1.0 不实现具体逻辑）。

设计动机：禅道/Jira 的差异（字段名、鉴权、分页）必须收敛在适配器内部，
否则后期每接一个平台就要改一次主干代码。
"""
from app.integrations.base import (
    INTEGRATION_REGISTRY,
    ExternalSyncAdapter,
    JiraAdapter,
    SyncResult,
    ZentaoAdapter,
    available_integrations,
    get_adapter,
)

__all__ = [
    "INTEGRATION_REGISTRY",
    "ExternalSyncAdapter",
    "JiraAdapter",
    "SyncResult",
    "ZentaoAdapter",
    "available_integrations",
    "get_adapter",
]