"""助手可调用的白名单只读工具。

模型永远拿不到数据库、文件系统或 shell；它只能看到这里返回的结构化观察结果。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from app.core.config import Settings
from app.core.context import get_current_project_id
from app.knowledge.indexer import KnowledgeService
from app.llm.factory import get_llm_provider
from app.repository import Repository
from app.schemas.assistant import AssistantLink
from app.schemas.knowledge import KnowledgeSearchRequest
from app.services.work_item_service import WorkItemService


@dataclass(slots=True)
class ToolObservation:
    name: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    links: list[AssistantLink] = field(default_factory=list)
    citations: list[Any] = field(default_factory=list)


class ReadonlyToolbox:
    def __init__(self, settings: Settings, repository: Repository) -> None:
        self.settings = settings
        self.repository = repository
        self.project_id = get_current_project_id() or "PRJ-default"
        self.knowledge = KnowledgeService(settings, repository)
        self._tools: dict[str, Callable[..., ToolObservation]] = {
            "health_status": self.health_status,
            "recent_resources": self.recent_resources,
            "resource_detail": self.resource_detail,
            "knowledge_search": self.knowledge_search,
            "job_status": self.job_status,
            "work_items_today": self.work_items_today,
            "work_items_overdue": self.work_items_overdue,
            "assistant_context": self.assistant_context,
        }

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "description": getattr(fn, "__doc__", "").strip(), "readonly": True}
            for name, fn in self._tools.items()
        ]

    def call(self, name: str, **kwargs: Any) -> ToolObservation:
        tool = self._tools.get(name)
        if tool is None:
            raise PermissionError(f"未授权的工具：{name}")
        return tool(**kwargs)

    def health_status(self) -> ToolObservation:
        """读取平台健康、模型降级原因与受控执行限制。"""
        llm = get_llm_provider()
        data = {
            "status": "ok",
            "version": self.settings.app_version,
            "llm_provider": llm.name,
            "llm_model": llm.model,
            "llm_available": llm.available,
            "degraded_reason": llm.degraded_reason,
            "project_id": self.project_id,
            "isolation_enabled": self.settings.project_isolation_enabled,
            "execution_limits": {
                "timeout_seconds": self.settings.execution_timeout_seconds,
                "max_cases": self.settings.execution_max_cases,
                "max_response_bytes": self.settings.execution_max_response_bytes,
            },
        }
        summary = (
            "平台服务正常；大模型可用。"
            if llm.available
            else f"平台服务正常；大模型未启用：{llm.degraded_reason or '未配置'}"
        )
        return ToolObservation(
            name="health_status",
            summary=summary,
            data=data,
            links=[AssistantLink(label="健康与阈值", href="/settings")],
        )

    def recent_resources(self) -> ToolObservation:
        """列出当前项目最近生成的文档、用例集与执行记录。"""
        documents = self.repository.documents.list_recent(5)
        suites = self.repository.suites.list_recent(5)
        runs = self.repository.test_runs.list_recent(5)
        data = {
            "documents": [
                {"id": item.doc_id, "title": item.filename, "created_at": item.created_at}
                for item in documents
            ],
            "suites": [
                {
                    "id": item.suite_id,
                    "title": item.doc_title,
                    "cases": item.stats.total,
                    "revision": item.revision,
                    "created_at": item.created_at,
                }
                for item in suites
            ],
            "test_runs": [item.summary().model_dump(mode="json") for item in runs],
        }
        links = [
            *[AssistantLink(label=item.filename, href=f"/documents/{item.doc_id}/requirement") for item in documents[:3]],
            *[AssistantLink(label=item.doc_title or item.suite_id, href=f"/suites/{item.suite_id}") for item in suites[:3]],
        ]
        return ToolObservation(
            name="recent_resources",
            summary=f"最近有 {len(documents)} 份文档、{len(suites)} 份用例集、{len(runs)} 次执行。",
            data=data,
            links=links,
        )

    def resource_detail(self, resource_type: str, resource_id: str) -> ToolObservation:
        """读取当前项目中的一个文档、用例集或接口规范的详情摘要。"""
        if resource_type == "document":
            item = self.repository.documents.get(resource_id)
            data = {
                "type": "document",
                "id": item.doc_id,
                "title": item.filename,
                "chars": item.char_count,
                "external_source": item.external_source,
                "external_status": item.external_status,
                "preview": item.preview(800),
            }
            link = AssistantLink(
                label=item.filename,
                href=f"/documents/{item.doc_id}/requirement",
                resource_type="document",
                resource_id=item.doc_id,
            )
        elif resource_type == "suite":
            item = self.repository.suites.get(resource_id)
            data = {
                "type": "suite",
                "id": item.suite_id,
                "title": item.doc_title,
                "cases": item.stats.total,
                "revision": item.revision,
                "external_links": item.external_links,
            }
            link = AssistantLink(
                label=item.doc_title or item.suite_id,
                href=f"/suites/{item.suite_id}",
                resource_type="suite",
                resource_id=item.suite_id,
            )
        elif resource_type == "api_spec":
            item = self.repository.api_specs.get(resource_id)
            data = {
                "type": "api_spec",
                "id": item.spec_id,
                "title": item.title,
                "version": item.version,
                "operations": len(item.operations),
            }
            link = AssistantLink(
                label=item.title,
                href=f"/apis/{item.spec_id}",
                resource_type="api_spec",
                resource_id=item.spec_id,
            )
        else:
            raise ValueError("resource_type 仅支持 document / suite / api_spec。")
        return ToolObservation(
            name="resource_detail",
            summary=f"已读取 {resource_type} {resource_id}。",
            data=data,
            links=[link],
        )

    def knowledge_search(self, query: str, limit: int = 5) -> ToolObservation:
        """在项目知识库检索并返回带来源、版本和定位的引用。"""
        result = self.knowledge.search(
            KnowledgeSearchRequest(
                query=query,
                limit=min(limit, self.settings.assistant_max_knowledge_results),
            )
        )
        return ToolObservation(
            name="knowledge_search",
            summary=f"知识库命中 {result.total} 条引用。",
            data={
                "query": query,
                "total": result.total,
                "degraded_reason": result.degraded_reason,
            },
            citations=result.citations,
        )

    def job_status(self, job_id: str = "") -> ToolObservation:
        """读取当前项目任务状态、事件与最近 Agent 工具调用。"""
        if job_id:
            job = self.repository.jobs.get(job_id)
            if job.project_id != self.project_id:
                raise ValueError("任务不属于当前项目。")
            events = self.repository.job_events.list_recent(
                50, predicate=lambda item: item.job_id == job_id
            )
            data = {
                "job": job.model_dump(mode="json"),
                "events": [item.model_dump(mode="json") for item in events],
            }
            summary = f"任务 {job_id} 当前状态：{job.status}。"
        else:
            jobs = self.repository.jobs.list_recent(
                10, predicate=lambda item: item.project_id == self.project_id
            )
            data = {"jobs": [item.model_dump(mode="json") for item in jobs]}
            summary = f"当前项目最近有 {len(jobs)} 个任务。"
        return ToolObservation(
            name="job_status",
            summary=summary,
            data=data,
            links=[AssistantLink(label="运行治理", href="/platform?tab=jobs")],
        )

    def work_items_today(self) -> ToolObservation:
        """读取今天与即将到期的工作事项，不经过 RAG。"""
        service = WorkItemService(self.settings, self.repository)
        items = service.list_items(view="today", limit=50)
        return ToolObservation(
            name="work_items_today",
            summary=f"今天有 {len(items)} 条工作事项。",
            data={"items": [item.model_dump(mode="json") for item in items]},
            links=[AssistantLink(label="交付工作台", href="/workspace")],
        )

    def work_items_overdue(self) -> ToolObservation:
        """读取逾期工作事项，不经过 RAG。"""
        service = WorkItemService(self.settings, self.repository)
        items = service.list_items(view="overdue", limit=50)
        return ToolObservation(
            name="work_items_overdue",
            summary=f"有 {len(items)} 条逾期工作事项。",
            data={"items": [item.model_dump(mode="json") for item in items]},
            links=[AssistantLink(label="交付工作台", href="/workspace")],
        )

    def assistant_context(self, current_path: str = "") -> ToolObservation:
        """读取当前项目与页面上下文，不包含其他项目数据。"""
        return ToolObservation(
            name="assistant_context",
            summary=f"当前项目 {self.project_id}，页面 {current_path or '/' }。",
            data={
                "project_id": self.project_id,
                "current_path": current_path,
                "now": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
        )


__all__ = ["ReadonlyToolbox", "ToolObservation"]
