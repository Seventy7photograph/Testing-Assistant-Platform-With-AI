"""本地工作事项、筛选与提醒服务。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundError, SchemaValidationError
from app.core.utils import new_id, now_iso
from app.repository import Repository, get_repository
from app.schemas.work_item import (
    WorkItem,
    WorkItemCreate,
    WorkItemLink,
    WorkItemSummary,
    WorkItemUpdate,
)

try:
    TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # Windows 未安装 tzdata 时仍保持 UTC+8 的确定行为
    TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
ViewName = Literal["inbox", "today", "upcoming", "overdue", "all", "completed"]


def local_now() -> datetime:
    return datetime.now(TZ)


def _parse_local(raw: str | None) -> datetime | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SchemaValidationError(
            "日期时间格式不合法，必须使用 ISO 8601。",
            detail={"value": raw},
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return parsed.astimezone(TZ)


def _normalize_optional(raw: str | None) -> str | None:
    parsed = _parse_local(raw)
    return parsed.isoformat(timespec="seconds") if parsed else None


def _rank_priority(value: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(value, 9)


class WorkItemService:
    def __init__(
        self,
        settings: Settings | None = None,
        repository: Repository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or get_repository()

    def create(self, payload: WorkItemCreate) -> WorkItem:
        item = WorkItem(
            work_item_id=new_id("WI-"),
            item_type=payload.item_type,
            title=payload.title.strip(),
            body=payload.body,
            status=payload.status,
            priority=payload.priority,
            due_at=_normalize_optional(payload.due_at),
            remind_at=_normalize_optional(payload.remind_at),
            tags=self._normalize_tags(payload.tags),
            pinned=payload.pinned,
            links=self._normalize_links(payload.links),
            created_at=now_iso(),
            updated_at=now_iso(),
        )
        self.repository.work_items.save(item)
        self._event("work_item.create", item)
        return item

    def get(self, work_item_id: str) -> WorkItem:
        return self.repository.work_items.get(work_item_id)

    def update(self, work_item_id: str, payload: WorkItemUpdate) -> WorkItem:
        item = self.get(work_item_id)
        fields = payload.model_fields_set
        if "title" in fields and payload.title is not None:
            item.title = payload.title.strip()
        if "body" in fields and payload.body is not None:
            item.body = payload.body
        if "status" in fields and payload.status is not None:
            item.status = payload.status
            item.completed_at = now_iso() if payload.status == "done" else None
        if "priority" in fields and payload.priority is not None:
            item.priority = payload.priority
        if "due_at" in fields:
            item.due_at = _normalize_optional(payload.due_at)
        if "remind_at" in fields:
            next_remind_at = _normalize_optional(payload.remind_at)
            if next_remind_at != item.remind_at:
                item.reminded_at = None
            item.remind_at = next_remind_at
        if "tags" in fields and payload.tags is not None:
            item.tags = self._normalize_tags(payload.tags)
        if "pinned" in fields and payload.pinned is not None:
            item.pinned = payload.pinned
        if "links" in fields and payload.links is not None:
            item.links = self._normalize_links(payload.links)
        item.updated_at = now_iso()
        self.repository.work_items.save(item)
        self._event("work_item.update", item)
        return item

    def complete(self, work_item_id: str) -> WorkItem:
        item = self.get(work_item_id)
        item.status = "done"
        item.completed_at = now_iso()
        item.updated_at = item.completed_at
        self.repository.work_items.save(item)
        self._event("work_item.complete", item)
        return item

    def archive(self, work_item_id: str) -> WorkItem:
        item = self.get(work_item_id)
        item.status = "archived"
        item.updated_at = now_iso()
        self.repository.work_items.save(item)
        self._event("work_item.archive", item)
        return item

    def delete(self, work_item_id: str) -> bool:
        if not self.repository.work_items.delete(work_item_id):
            raise NotFoundError(f"工作事项不存在：{work_item_id}")
        self._event(
            "work_item.delete",
            WorkItem(work_item_id=work_item_id, title="已删除事项", status="archived"),
        )
        return True

    def list_items(
        self,
        *,
        view: ViewName = "all",
        q: str = "",
        status: str | None = None,
        priority: str | None = None,
        tag: str | None = None,
        limit: int = 200,
    ) -> list[WorkItem]:
        now = local_now()
        today = now.date()
        upcoming_end = today + timedelta(days=7)
        needle = q.strip().lower()
        tag_needle = (tag or "").strip().lower()
        items = self.repository.work_items.list_recent(limit=10_000)
        selected: list[WorkItem] = []
        for item in items:
            due = _parse_local(item.due_at)
            due_date = due.date() if due else None
            if view == "completed":
                if item.status != "done":
                    continue
            elif item.status in {"done", "archived"}:
                continue
            elif view == "inbox":
                if due_date is not None:
                    continue
            elif view == "today":
                if due_date != today:
                    continue
            elif view == "upcoming":
                if due_date is None or not (today < due_date <= upcoming_end):
                    continue
            elif view == "overdue":
                if due_date is None or due_date >= today:
                    continue
            if status and item.status != status:
                continue
            if priority and item.priority != priority:
                continue
            if needle and needle not in f"{item.title}\n{item.body}\n{' '.join(item.tags)}".lower():
                continue
            if tag_needle and tag_needle not in {name.lower() for name in item.tags}:
                continue
            selected.append(item)

        def sort_key(item: WorkItem) -> tuple:
            due = _parse_local(item.due_at)
            return (
                0 if item.pinned else 1,
                due.timestamp() if due else float("inf"),
                _rank_priority(item.priority),
                -datetime.fromisoformat(item.updated_at).timestamp(),
            )

        selected.sort(key=sort_key)
        return selected[: min(max(limit, 1), 500)]

    def summary(self) -> WorkItemSummary:
        open_items = self.list_items(view="all", limit=500)
        now = local_now()
        today = now.date()
        upcoming_end = today + timedelta(days=7)
        inbox = 0
        today_count = 0
        upcoming = 0
        overdue = 0
        for item in open_items:
            due = _parse_local(item.due_at)
            if due is None:
                inbox += 1
                continue
            if due.date() < today:
                overdue += 1
            elif due.date() == today:
                today_count += 1
            elif due.date() <= upcoming_end:
                upcoming += 1
        completed = sum(
            1
            for item in self.repository.work_items.list_recent(limit=10_000)
            if item.status == "done"
        )
        notes = [
            item
            for item in self.repository.work_items.list_recent(limit=20)
            if item.item_type == "note"
        ][:4]
        tasks = [item for item in open_items if item.item_type == "task"][:4]
        return WorkItemSummary(
            inbox=inbox,
            today=today_count,
            upcoming=upcoming,
            overdue=overdue,
            open_tasks=sum(1 for item in open_items if item.item_type == "task"),
            completed=completed,
            due_reminders=len(self.due_reminders()),
            recent_notes=notes,
            recent_tasks=tasks,
        )

    def due_reminders(self, *, limit: int = 100) -> list[WorkItem]:
        now = local_now()
        items = self.repository.work_items.list_recent(
            limit=10_000,
            predicate=lambda item: item.reminded_at is None
            and item.status not in {"done", "archived"}
            and _parse_local(item.remind_at) is not None
            and _parse_local(item.remind_at) <= now,
        )
        items.sort(key=lambda item: item.remind_at or "")
        return items[: min(max(limit, 1), 200)]

    def acknowledge_reminders(self, ids: list[str]) -> list[WorkItem]:
        updated: list[WorkItem] = []
        stamp = now_iso()
        for work_item_id in dict.fromkeys(ids):
            item = self.repository.work_items.try_get(work_item_id)
            if item is None or item.status in {"done", "archived"}:
                continue
            if item.reminded_at is None:
                item.reminded_at = stamp
                item.updated_at = stamp
                self.repository.work_items.save(item)
                self._event("work_item.reminder", item)
            updated.append(item)
        return updated

    def _event(self, action: str, item: WorkItem) -> None:
        from app.services.execution_service import ExecutionService

        ExecutionService(self.settings, self.repository).add_event(
            trace_id=new_id("TRACE-"),
            action=action,
            status="completed",
            work_item_id=item.work_item_id,
            message=f"type={item.item_type}; status={item.status}",
        )

    @staticmethod
    def _normalize_tags(tags: list[str]) -> list[str]:
        result: list[str] = []
        for raw in tags:
            value = raw.strip()
            if not value:
                continue
            if len(value) > 32:
                raise SchemaValidationError("单个标签不能超过 32 个字符。", detail={"tag": value})
            if value not in result:
                result.append(value)
        if len(result) > 20:
            raise SchemaValidationError("一个事项最多 20 个标签。")
        return result

    @staticmethod
    def _normalize_links(links: list[WorkItemLink]) -> list[WorkItemLink]:
        result = []
        for link in links:
            if not link.resource_id.strip() and link.resource_type != "external":
                raise SchemaValidationError(
                    "关联资源 ID 不能为空。",
                    detail={"resource_type": link.resource_type},
                )
            result.append(
                WorkItemLink(
                    resource_type=link.resource_type,
                    resource_id=link.resource_id.strip(),
                    label=link.label.strip()[:200],
                    href=link.href.strip()[:500],
                )
            )
        return result


__all__ = ["WorkItemService", "local_now"]
