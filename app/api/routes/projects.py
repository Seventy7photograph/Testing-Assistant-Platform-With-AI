"""v3.0 项目、当前上下文与审计查询。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import SettingsDep
from app.core.context import get_current_actor, get_current_project_id, get_current_role
from app.core.exceptions import BadRequestError
from app.schemas.api import ApiResponse, ok
from app.schemas.platform import (
    AuditEvent,
    Project,
    ProjectContextInfo,
    ProjectCreate,
    ProjectUpdate,
)
from app.services.project_service import ProjectService

router = APIRouter(tags=["项目与审计"])


def _require_admin() -> None:
    if get_current_role() not in {"owner", "admin"}:
        raise BadRequestError(
            "当前身份无权修改项目。",
            detail={"role": get_current_role()},
        )


@router.get(
    "/projects",
    response_model=ApiResponse[list[Project]],
    summary="项目列表",
)
async def list_projects(settings: SettingsDep) -> dict:
    service = ProjectService(settings)
    service.ensure_default()
    if settings.auth_enabled:
        return ok([service.get(get_current_project_id())])
    return ok(service.list_projects())


@router.post(
    "/projects",
    response_model=ApiResponse[Project],
    summary="创建项目分区",
)
async def create_project(payload: ProjectCreate, settings: SettingsDep) -> dict:
    _require_admin()
    project = ProjectService(settings).create(payload)
    return ok(project, message="项目已创建")


@router.get(
    "/projects/current",
    response_model=ApiResponse[ProjectContextInfo],
    summary="读取当前请求的项目上下文",
)
async def current_project(settings: SettingsDep) -> dict:
    service = ProjectService(settings)
    project = service.get(get_current_project_id() or service.ensure_default().project_id)
    return ok(
        ProjectContextInfo(
            project=project,
            actor=get_current_actor(),
            role=get_current_role(),  # type: ignore[arg-type]
            auth_enabled=settings.auth_enabled,
            isolation_enabled=settings.project_isolation_enabled,
            storage_backend=settings.storage_backend,
        )
    )


@router.patch(
    "/projects/{project_id}",
    response_model=ApiResponse[Project],
    summary="更新项目元数据与配额",
)
async def update_project(
    project_id: str,
    payload: ProjectUpdate,
    settings: SettingsDep,
) -> dict:
    _require_admin()
    if project_id != get_current_project_id():
        raise BadRequestError(
            "只能从当前项目上下文修改该项目；跨项目变更需先切换项目。",
            detail={"current": get_current_project_id(), "requested": project_id},
        )
    project = ProjectService(settings).update(project_id, payload)
    return ok(project, message="项目已更新")


@router.get(
    "/projects/{project_id}/audit",
    response_model=ApiResponse[list[AuditEvent]],
    summary="读取项目审计事件",
)
async def project_audit(
    project_id: str,
    settings: SettingsDep,
    action: str = Query(default="", max_length=120),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict:
    if project_id != get_current_project_id():
        raise BadRequestError(
            "不能从当前项目读取其他项目的审计事件。",
            detail={"current": get_current_project_id(), "requested": project_id},
        )
    return ok(
        ProjectService(settings).list_audit(
            project_id=project_id,
            action=action,
            limit=limit,
        )
    )


__all__ = ["router"]
