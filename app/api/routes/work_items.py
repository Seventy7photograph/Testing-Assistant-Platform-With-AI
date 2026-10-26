"""V2.3 工作事项、过滤器、摘要与提醒接口。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import WorkItemServiceDep
from app.schemas.api import ApiResponse, ok
from app.schemas.work_item import (
    ReminderAck,
    WorkItem,
    WorkItemCreate,
    WorkItemSummary,
    WorkItemUpdate,
)

router = APIRouter(tags=["工作事项"])


@router.get(
    "/work-items/summary",
    response_model=ApiResponse[WorkItemSummary],
    summary="工作事项摘要",
)
async def work_item_summary(service: WorkItemServiceDep) -> dict:
    return ok(service.summary())


@router.get(
    "/work-items/reminders/due",
    response_model=ApiResponse[list[WorkItem]],
    summary="到期且尚未提醒的工作事项",
)
async def due_work_item_reminders(
    service: WorkItemServiceDep,
    limit: int = Query(default=100, ge=1, le=200),
) -> dict:
    return ok(service.due_reminders(limit=limit))


@router.post(
    "/work-items/reminders/ack",
    response_model=ApiResponse[list[WorkItem]],
    summary="确认已展示提醒（幂等）",
)
async def acknowledge_work_item_reminders(
    payload: ReminderAck,
    service: WorkItemServiceDep,
) -> dict:
    return ok(service.acknowledge_reminders(payload.ids))


@router.get(
    "/work-items",
    response_model=ApiResponse[list[WorkItem]],
    summary="工作事项列表",
)
async def list_work_items(
    service: WorkItemServiceDep,
    view: str = Query(default="all"),
    q: str = Query(default="", max_length=200),
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    allowed = {"inbox", "today", "upcoming", "overdue", "all", "completed"}
    selected = view if view in allowed else "all"
    return ok(
        service.list_items(
            view=selected,  # type: ignore[arg-type]
            q=q,
            status=status,
            priority=priority,
            tag=tag,
            limit=limit,
        )
    )


@router.post(
    "/work-items",
    response_model=ApiResponse[WorkItem],
    summary="创建工作事项",
)
async def create_work_item(payload: WorkItemCreate, service: WorkItemServiceDep) -> dict:
    return ok(service.create(payload), message="工作事项已创建")


@router.get(
    "/work-items/{work_item_id}",
    response_model=ApiResponse[WorkItem],
    summary="工作事项详情",
)
async def get_work_item(work_item_id: str, service: WorkItemServiceDep) -> dict:
    return ok(service.get(work_item_id))


@router.put(
    "/work-items/{work_item_id}",
    response_model=ApiResponse[WorkItem],
    summary="更新工作事项",
)
async def update_work_item(
    work_item_id: str,
    payload: WorkItemUpdate,
    service: WorkItemServiceDep,
) -> dict:
    return ok(service.update(work_item_id, payload), message="工作事项已保存")


@router.post(
    "/work-items/{work_item_id}/complete",
    response_model=ApiResponse[WorkItem],
    summary="完成工作事项",
)
async def complete_work_item(work_item_id: str, service: WorkItemServiceDep) -> dict:
    return ok(service.complete(work_item_id), message="工作事项已完成")


@router.post(
    "/work-items/{work_item_id}/archive",
    response_model=ApiResponse[WorkItem],
    summary="归档工作事项",
)
async def archive_work_item(work_item_id: str, service: WorkItemServiceDep) -> dict:
    return ok(service.archive(work_item_id), message="工作事项已归档")


@router.delete(
    "/work-items/{work_item_id}",
    response_model=ApiResponse[dict[str, bool]],
    summary="删除工作事项",
)
async def delete_work_item(work_item_id: str, service: WorkItemServiceDep) -> dict:
    return ok({"deleted": service.delete(work_item_id)}, message="工作事项已删除")


__all__ = ["router"]
