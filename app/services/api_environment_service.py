"""Project-scoped API execution environment profiles."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from app.core.config import Settings, get_settings
from app.core.context import get_current_actor, get_current_project_id
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.utils import new_id, now_iso
from app.repository import Repository, get_repository
from app.schemas.platform_execution import (
    ApiEnvironmentCreate,
    ApiEnvironmentProfile,
    ApiEnvironmentUpdate,
)
from app.services.project_service import ProjectService

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SENSITIVE_HEADERS = {"authorization", "cookie", "proxy-authorization", "x-api-key"}


class ApiEnvironmentService:
    def __init__(
        self,
        settings: Settings | None = None,
        repository: Repository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or get_repository()
        self.project_id = get_current_project_id() or "PRJ-default"
        self.projects = ProjectService(self.settings)

    def list(self) -> list[ApiEnvironmentProfile]:
        return self.repository.api_environments.list_recent(
            limit=200,
            predicate=lambda item: item.project_id == self.project_id,
        )

    def get(self, environment_id: str) -> ApiEnvironmentProfile:
        item = self.repository.api_environments.get(environment_id)
        if item.project_id != self.project_id:
            raise NotFoundError(
                "接口测试环境不存在。",
                detail={"environment_id": environment_id},
            )
        return item

    def create(self, payload: ApiEnvironmentCreate) -> ApiEnvironmentProfile:
        self._validate(payload.base_url, payload.variables, payload.headers)
        stamp = now_iso()
        item = ApiEnvironmentProfile(
            environment_id=new_id("ENV-"),
            project_id=self.project_id,
            name=payload.name.strip(),
            base_url=payload.base_url.strip().rstrip("/"),
            variables=dict(payload.variables),
            headers=dict(payload.headers),
            created_at=stamp,
            updated_at=stamp,
        )
        self.repository.api_environments.save(item)
        self._audit("environment.create", item.environment_id)
        return item

    def update(
        self,
        environment_id: str,
        payload: ApiEnvironmentUpdate,
    ) -> ApiEnvironmentProfile:
        item = self.get(environment_id)
        base_url = item.base_url if payload.base_url is None else payload.base_url
        variables = item.variables if payload.variables is None else payload.variables
        headers = item.headers if payload.headers is None else payload.headers
        self._validate(base_url, variables, headers)
        if payload.name is not None:
            item.name = payload.name.strip()
        item.base_url = base_url.strip().rstrip("/")
        item.variables = dict(variables)
        item.headers = dict(headers)
        item.updated_at = now_iso()
        self.repository.api_environments.save(item)
        self._audit("environment.update", item.environment_id)
        return item

    def delete(self, environment_id: str) -> dict[str, bool | str]:
        item = self.get(environment_id)
        self.repository.api_environments.delete(item.environment_id)
        self._audit("environment.delete", item.environment_id)
        return {"deleted": True, "environment_id": item.environment_id}

    @staticmethod
    def _validate(
        base_url: str,
        variables: dict[str, str],
        headers: dict[str, str],
    ) -> None:
        if base_url:
            parsed = urlparse(base_url.strip())
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise BadRequestError("环境 Base URL 必须是合法的 HTTP(S) 地址。")
        if len(variables) > 100 or len(headers) > 30:
            raise BadRequestError("单个环境最多配置 100 个变量和 30 个 Header。")
        for name, value in variables.items():
            if not _NAME_RE.fullmatch(name):
                raise BadRequestError(f"环境变量名不合法：{name}")
            if len(str(value)) > 4000:
                raise BadRequestError(f"环境变量过长：{name}")
        for name, value in headers.items():
            normalized = name.strip()
            if not normalized or len(normalized) > 100 or len(str(value)) > 4000:
                raise BadRequestError("Header 名称或值不合法。")
            if normalized.lower() in {"host", "content-length"}:
                raise BadRequestError(f"不允许配置 Header：{normalized}")
            if (
                normalized.lower() in _SENSITIVE_HEADERS
                and "{{" not in str(value)
            ):
                raise BadRequestError(
                    f"{normalized} 必须使用变量占位符，不能把密钥明文保存到环境配置。"
                )

    def _audit(self, action: str, resource_id: str) -> None:
        self.projects.audit(
            action=action,
            resource_type="api_environment",
            resource_id=resource_id,
            project_id=self.project_id,
            actor=get_current_actor(),
        )


__all__ = ["ApiEnvironmentService"]
