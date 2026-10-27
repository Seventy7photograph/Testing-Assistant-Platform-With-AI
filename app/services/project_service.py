"""项目注册、鉴权、配额与审计。"""
from __future__ import annotations

import hmac
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.logging import get_logger, sanitize_log_text
from app.core.utils import new_id, now_iso
from app.schemas.platform import AuditEvent, Project, ProjectCreate, ProjectQuota, ProjectUpdate

logger = get_logger(__name__)

_PROJECT_ID_RE = re.compile(r"^PRJ-(?:[0-9a-f]{8,16}|default)$")


class ProjectService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------
    def list_projects(self) -> list[Project]:
        projects = [item for _, item in self._read_registry().items()]
        projects.sort(key=lambda item: (item.status != "active", item.name.lower()))
        return projects

    def ensure_default(self) -> Project:
        projects = self._read_registry()
        current = projects.get("PRJ-default")
        if current is not None:
            return current
        project = Project(
            project_id="PRJ-default",
            key="DEFAULT",
            name="默认项目",
            description="兼容 v2.x 单工作区数据的默认分区。",
            quota=ProjectQuota(
                max_documents=self.settings.project_quota_documents,
                max_suites=self.settings.project_quota_suites,
                max_jobs=self.settings.project_quota_jobs,
            ),
        )
        projects[project.project_id] = project
        self._write_registry(projects)
        (self.settings.project_storage_dir(project.project_id) / "data").mkdir(
            parents=True, exist_ok=True
        )
        return project

    def get(self, project_id: str) -> Project:
        if not _PROJECT_ID_RE.match(project_id or ""):
            raise NotFoundError("项目不存在或 ID 不合法。", detail={"project_id": project_id})
        project = self._read_registry().get(project_id)
        if project is None:
            raise NotFoundError("项目不存在。", detail={"project_id": project_id})
        return project

    def create(self, payload: ProjectCreate) -> Project:
        projects = self._read_registry()
        if any(item.key == payload.key for item in projects.values()):
            raise ConflictError("项目 Key 已存在。", detail={"key": payload.key})
        quota = payload.quota or ProjectQuota(
            max_documents=self.settings.project_quota_documents,
            max_suites=self.settings.project_quota_suites,
            max_jobs=self.settings.project_quota_jobs,
        )
        project = Project(
            project_id=f"PRJ-{new_id()[:10]}",
            key=payload.key,
            name=payload.name.strip(),
            description=payload.description.strip(),
            quota=quota,
        )
        projects[project.project_id] = project
        self._write_registry(projects)
        self._ensure_project_dirs(project.project_id)
        self.audit(
            action="project.create",
            resource_type="project",
            resource_id=project.project_id,
            project_id=project.project_id,
            detail={"key": project.key},
        )
        return project

    def update(self, project_id: str, payload: ProjectUpdate) -> Project:
        projects = self._read_registry()
        project = projects.get(project_id)
        if project is None:
            raise NotFoundError("项目不存在。", detail={"project_id": project_id})
        changes = payload.model_dump(exclude_none=True)
        for key, value in changes.items():
            if key == "quota" and isinstance(value, dict):
                value = ProjectQuota.model_validate(value)
            setattr(project, key, value)
        project.updated_at = now_iso()
        projects[project_id] = project
        self._write_registry(projects)
        self.audit(
            action="project.update",
            resource_type="project",
            resource_id=project_id,
            project_id=project_id,
            detail={"fields": sorted(changes)},
        )
        return project

    # ------------------------------------------------------------------
    # Authentication / context
    # ------------------------------------------------------------------
    def token_map(self) -> dict[str, dict]:
        raw = (self.settings.auth_tokens or "{}").strip()
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("AUTH_TOKENS 不是合法 JSON；鉴权配置不可用。")
            raise BadRequestError(
                "AUTH_TOKENS 配置不是合法 JSON。",
                detail={"error": str(exc)},
            ) from exc
        if not isinstance(value, dict):
            raise BadRequestError("AUTH_TOKENS 必须是 token -> 身份 的 JSON 对象。")
        return {str(key): item for key, item in value.items() if isinstance(item, dict)}

    def authenticate(self, token: str) -> tuple[Project, str, str]:
        if not token:
            raise BadRequestError(
                "未提供 API Key。",
                detail={"header": self.settings.auth_header},
            )
        matched: dict | None = None
        matched_token = ""
        for candidate, principal in self.token_map().items():
            if hmac.compare_digest(candidate, token):
                matched, matched_token = principal, candidate
                break
        if matched is None:
            raise BadRequestError("API Key 无效。", detail={"auth": "denied"})
        project_id = str(matched.get("project_id") or "")
        project = self.get(project_id)
        actor = str(matched.get("actor") or f"token:{matched_token[:4]}…")
        role = str(matched.get("role") or "member")
        if role not in {"owner", "admin", "member", "viewer"}:
            role = "member"
        return project, actor, role

    def resolve_request(self, *, api_key: str, requested_project: str) -> tuple[Project, str, str]:
        auth_mode = self.settings.auth_enabled
        if auth_mode:
            project, actor, role = self.authenticate(api_key)
            if requested_project and requested_project != project.project_id:
                self.audit(
                    action="auth.project_mismatch",
                    resource_type="project",
                    resource_id=requested_project,
                    project_id=project.project_id,
                    outcome="denied",
                    detail={"requested_project": requested_project},
                )
                raise _Forbidden("API Key 与请求项目不匹配。")
            return project, actor, role

        default = self.ensure_default()
        if requested_project:
            project = self.get(requested_project)
            return project, "local", "owner"
        return default, "local", "owner"

    # ------------------------------------------------------------------
    # Quota
    # ------------------------------------------------------------------
    def check_quota(self, project: Project, *, resource: str, current: int) -> None:
        limits = {
            "documents": project.quota.max_documents,
            "suites": project.quota.max_suites,
            "jobs": project.quota.max_jobs,
        }
        if resource not in limits:
            return
        if current >= limits[resource]:
            raise ConflictError(
                f"项目 {project.key} 的 {resource} 配额已用尽。",
                detail={"resource": resource, "used": current, "limit": limits[resource]},
            )

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------
    def audit(
        self,
        *,
        action: str,
        resource_type: str,
        resource_id: str,
        project_id: str,
        outcome: str = "succeeded",
        actor: str = "local",
        role: str = "owner",
        trace_id: str = "",
        detail: dict | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            audit_id=new_id("AUD-"),
            project_id=project_id,
            actor=actor,
            role=role,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,  # type: ignore[arg-type]
            trace_id=trace_id,
            detail={
                str(key): sanitize_log_text(str(value))[:1000]
                for key, value in (detail or {}).items()
            },
        )
        path = self.settings.audit_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")
        return event

    def list_audit(
        self,
        *,
        project_id: str,
        action: str = "",
        limit: int = 100,
    ) -> list[AuditEvent]:
        path = self.settings.audit_path
        if not path.exists():
            return []
        found: list[AuditEvent] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in reversed(handle.readlines()):
                try:
                    event = AuditEvent.model_validate_json(line)
                except Exception:  # noqa: BLE001 - 损坏的审计行不能阻断查询
                    continue
                if event.project_id != project_id:
                    continue
                if action and event.action != action:
                    continue
                found.append(event)
                if len(found) >= min(max(limit, 1), 1000):
                    break
        return found

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _read_registry(self) -> dict[str, Project]:
        path = self.settings.project_registry_path
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConflictError(
                "项目注册表损坏，已停止读写以保护现有分区。",
                detail={"path": str(path), "error": str(exc)},
            ) from exc
        projects: dict[str, Project] = {}
        for item in raw.get("projects", []):
            project = Project.model_validate(item)
            projects[project.project_id] = project
        return projects

    def _write_registry(self, projects: dict[str, Project]) -> None:
        path = self.settings.project_registry_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "projects": [item.model_dump(mode="json") for item in projects.values()],
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _ensure_project_dirs(self, project_id: str) -> None:
        root = self.settings.project_storage_dir(project_id)
        for name in ("data", "uploads", "exports"):
            (root / name).mkdir(parents=True, exist_ok=True)


class _Forbidden(BadRequestError):
    code = "FORBIDDEN"
    http_status = 403
    default_message = "无权访问该项目"


__all__ = ["ProjectService"]
