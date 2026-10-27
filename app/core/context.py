"""请求级安全上下文。

项目 ID 与操作者只从经过鉴权中间件验证的请求进入 ContextVar。
业务服务不读取客户端传来的任意项目字段，避免跨项目 ID 混淆。
"""
from __future__ import annotations

from contextvars import ContextVar

current_project_id: ContextVar[str] = ContextVar("current_project_id", default="")
current_actor: ContextVar[str] = ContextVar("current_actor", default="local")
current_role: ContextVar[str] = ContextVar("current_role", default="owner")


def get_current_project_id() -> str:
    return current_project_id.get()


def get_current_actor() -> str:
    return current_actor.get()


def get_current_role() -> str:
    return current_role.get()


desktop_request_context = (current_project_id, current_actor, current_role)


__all__ = [
    "current_actor",
    "current_project_id",
    "current_role",
    "desktop_request_context",
    "get_current_actor",
    "get_current_project_id",
    "get_current_role",
]
