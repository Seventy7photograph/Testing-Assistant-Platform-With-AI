"""V2.3 本地工作事项与提醒模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.utils import now_iso

WorkItemType = Literal["note", "task"]
WorkItemStatus = Literal["inbox", "todo", "doing", "done", "archived"]
WorkItemPriority = Literal["P0", "P1", "P2", "P3"]
ResourceType = Literal[
    "document",
    "requirement",
    "suite",
    "api_spec",
    "test_run",
    "report",
    "external",
]


class WorkItemLink(BaseModel):
    resource_type: ResourceType
    resource_id: str = ""
    label: str = ""
    href: str = ""


class WorkItem(BaseModel):
    work_item_id: str
    item_type: WorkItemType = "task"
    title: str
    body: str = ""
    status: WorkItemStatus = "inbox"
    priority: WorkItemPriority = "P2"
    due_at: str | None = None
    remind_at: str | None = None
    reminded_at: str | None = None
    tags: list[str] = Field(default_factory=list)
    pinned: bool = False
    links: list[WorkItemLink] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    completed_at: str | None = None


class WorkItemCreate(BaseModel):
    item_type: WorkItemType = "task"
    title: str = Field(..., min_length=1, max_length=240)
    body: str = Field(default="", max_length=50_000)
    status: WorkItemStatus = "inbox"
    priority: WorkItemPriority = "P2"
    due_at: str | None = None
    remind_at: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    pinned: bool = False
    links: list[WorkItemLink] = Field(default_factory=list, max_length=10)


class WorkItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    body: str | None = Field(default=None, max_length=50_000)
    status: WorkItemStatus | None = None
    priority: WorkItemPriority | None = None
    due_at: str | None = None
    remind_at: str | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    pinned: bool | None = None
    links: list[WorkItemLink] | None = Field(default=None, max_length=10)


class WorkItemSummary(BaseModel):
    inbox: int = 0
    today: int = 0
    upcoming: int = 0
    overdue: int = 0
    open_tasks: int = 0
    completed: int = 0
    due_reminders: int = 0
    recent_notes: list[WorkItem] = Field(default_factory=list)
    recent_tasks: list[WorkItem] = Field(default_factory=list)


class ReminderAck(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=200)


__all__ = [
    "ReminderAck",
    "ResourceType",
    "WorkItem",
    "WorkItemCreate",
    "WorkItemLink",
    "WorkItemPriority",
    "WorkItemStatus",
    "WorkItemSummary",
    "WorkItemType",
    "WorkItemUpdate",
]
