"""外部需求同步与用例回写编排。"""
from __future__ import annotations

from app.core.config import Settings, get_settings
from app.core.context import get_current_actor, get_current_project_id
from app.core.exceptions import BadRequestError, NotFoundError
from app.repository import Repository, get_repository
from app.schemas.document import DocumentSummary
from app.schemas.integrations import (
    ExternalStatus,
    IntegrationHealth,
    IntegrationPullResult,
    IntegrationPushRequest,
    IntegrationPushResult,
    IntegrationSyncRequest,
)
from app.services.document_service import DocumentService
from app.services.project_service import ProjectService


class IntegrationService:
    def __init__(
        self,
        settings: Settings | None = None,
        repository: Repository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or get_repository()
        self.project_id = get_current_project_id() or "PRJ-default"
        self.projects = ProjectService(self.settings)

    def _adapter(self, name: str):
        from app.integrations.jira import JiraAdapter
        from app.integrations.zentao import ZentaoAdapter

        mapping = {"jira": JiraAdapter, "zentao": ZentaoAdapter}
        cls = mapping.get(name)
        if cls is None:
            raise NotFoundError(
                "未知的外部集成。",
                detail={"name": name, "available": sorted(mapping)},
            )
        return cls(self.settings)

    async def health(
        self,
        name: str,
        payload: IntegrationSyncRequest | None = None,
    ) -> IntegrationHealth:
        adapter = self._adapter(name)
        options = payload.options if payload else {}
        project_key = payload.project_key if payload else ""
        try:
            ok, message = await adapter.health_check(
                project_key=project_key,
                options=options,
            )
        except Exception as exc:  # noqa: BLE001 - health 必须返回可展示原因
            return IntegrationHealth(
                name=name,
                label=adapter.label,
                configured=False,
                available=False,
                message="健康检查失败。",
                degraded_reason=str(exc),
            )
        configured = bool(
            options.get("base_url")
            or (name == "jira" and self.settings.jira_base_url)
            or (name == "zentao" and self.settings.zentao_base_url)
        )
        return IntegrationHealth(
            name=name,
            label=adapter.label,
            configured=configured,
            available=ok,
            message=message,
            degraded_reason="" if ok else message,
        )

    async def pull(
        self,
        name: str,
        payload: IntegrationSyncRequest,
    ) -> IntegrationPullResult:
        adapter = self._adapter(name)
        requirements = await adapter.pull_requirements(
            project_key=payload.project_key,
            options=payload.options,
        )
        service = DocumentService(self.settings, self.repository)
        documents: list[DocumentSummary] = []
        created = 0
        updated = 0
        for item in requirements:
            existing = self.repository.documents.list_recent(
                limit=1,
                predicate=lambda doc: (
                    doc.external_source == name
                    and doc.external_id == item.external_id
                ),
            )
            if existing:
                record = existing[0]
                record.text = item.body
                record.text_base = item.body
                record.char_count = len(item.body)
                record.line_count = item.body.count("\n") + 1
                record.external_status = item.status
                record.external_version = item.version
                record.external_url = item.url
                record.sync_metadata = item.metadata
                self.repository.documents.save(record)
                updated += 1
            else:
                record = service.save_text(
                    text=item.body,
                    title=f"{name.upper()} {item.external_id} {item.title}",
                )
                record.external_source = name
                record.external_id = item.external_id
                record.external_url = item.url
                record.external_version = item.version
                record.external_status = item.status
                record.sync_metadata = item.metadata
                self.repository.documents.save(record)
                created += 1
            documents.append(DocumentSummary.from_record(record))
        self.projects.audit(
            action="integration.pull",
            resource_type="integration",
            resource_id=name,
            project_id=self.project_id,
            actor=get_current_actor(),
            detail={"fetched": len(requirements), "created": created, "updated": updated},
        )
        return IntegrationPullResult(
            integration=name,
            fetched=len(requirements),
            created=created,
            updated=updated,
            requirements=requirements,
            documents=documents,
        )

    async def push(
        self,
        name: str,
        suite_id: str,
        payload: IntegrationPushRequest,
    ) -> IntegrationPushResult:
        suite = self.repository.suites.get(suite_id)
        adapter = self._adapter(name)
        options = dict(payload.options)
        options.setdefault("issue_key", payload.issue_key)
        options.setdefault("create_issue", payload.create_issue)
        result = await adapter.push_cases(
            suite,
            project_key=payload.project_key,
            options=options,
        )
        if result.external_ids:
            suite.external_links.append(
                {
                    "integration": name,
                    "external_ids": result.external_ids,
                    "message": result.message,
                }
            )
            self.repository.suites.save(suite)
        self.projects.audit(
            action="integration.push",
            resource_type="suite",
            resource_id=suite_id,
            project_id=self.project_id,
            actor=get_current_actor(),
            detail={"integration": name, "external_ids": result.external_ids},
        )
        return IntegrationPushResult(
            integration=name,
            suite_id=suite_id,
            external_ids=result.external_ids,
            message=result.message,
            warnings=result.warnings,
        )

    async def status(
        self,
        name: str,
        external_id: str,
        payload: IntegrationSyncRequest | None = None,
    ) -> ExternalStatus:
        return await self._adapter(name).read_status(
            external_id,
            options=payload.options if payload else {},
        )

    async def import_fixture(
        self,
        name: str,
        payload: IntegrationSyncRequest,
    ) -> IntegrationPullResult:
        fixture = payload.options.get("requirements")
        if not isinstance(fixture, list):
            raise BadRequestError(
                "文件导入模式的 options.requirements 必须是需求数组。",
                detail={"integration": name},
            )
        return await self.pull(name, payload)


__all__ = ["IntegrationService"]
