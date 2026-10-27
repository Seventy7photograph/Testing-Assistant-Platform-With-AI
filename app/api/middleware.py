"""v3.0 项目上下文与可选鉴权中间件。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Settings
from app.core.context import current_actor, current_project_id, current_role
from app.core.exceptions import AppError
from app.services.project_service import ProjectService

_PUBLIC_SUFFIXES = {"/health", "/integrations"}


class ProjectContextMiddleware(BaseHTTPMiddleware):
    """解析 API Key 与项目头，并把验证后的身份放入 ContextVar。"""

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        prefix = self.settings.api_prefix.rstrip("/")
        if not request.url.path.startswith(f"{prefix}/"):
            return await call_next(request)

        suffix = request.url.path[len(prefix) :]
        if suffix in _PUBLIC_SUFFIXES:
            return await call_next(request)

        service = ProjectService(self.settings)
        api_key = request.headers.get(self.settings.auth_header, "")
        requested = request.headers.get(self.settings.project_header, "").strip()
        try:
            project, actor, role = service.resolve_request(
                api_key=api_key,
                requested_project=requested,
            )
        except AppError as exc:
            if requested:
                try:
                    service.audit(
                        action="request.denied",
                        resource_type="request",
                        resource_id=request.url.path,
                        project_id=requested,
                        outcome="denied",
                        detail={"code": exc.code},
                    )
                except Exception:  # noqa: BLE001 - 审计失败不能覆盖原始拒绝原因
                    pass
            return JSONResponse(status_code=exc.http_status, content=exc.to_dict())
        if (
            role == "viewer" or project.status == "archived"
        ) and request.method not in {"GET", "HEAD", "OPTIONS"}:
            service.audit(
                action="request.readonly_denied",
                resource_type="request",
                resource_id=request.url.path,
                project_id=project.project_id,
                outcome="denied",
                actor=actor,
                role=role,
            )
            return JSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "code": "FORBIDDEN",
                    "message": (
                        "项目已归档，不能执行写操作。"
                        if project.status == "archived"
                        else "当前项目角色为只读，不能执行写操作。"
                    ),
                    "detail": {
                        "role": role,
                        "status": project.status,
                        "method": request.method,
                    },
                },
            )

        tokens = (
            current_project_id.set(project.project_id),
            current_actor.set(actor),
            current_role.set(role),
        )
        try:
            response = await call_next(request)
            response.headers["X-Project-ID"] = project.project_id
            return response
        finally:
            current_project_id.reset(tokens[0])
            current_actor.reset(tokens[1])
            current_role.reset(tokens[2])


__all__ = ["ProjectContextMiddleware"]
