"""平台总览接口：为首页仪表盘聚合各模块的状态与最近动态。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import DesignEngineDep, RepositoryDep, SettingsDep
from app.exporters.registry import available_formats
from app.integrations.base import available_integrations
from app.llm.factory import get_runtime_config_store
from app.parsers.registry import supported_extensions
from app.report import store as report_store
from app.report.config import verdict_thresholds
from app.report.llm import llm_settings
from app.schemas.api import ApiResponse, ok
from app.services.work_item_service import WorkItemService

router = APIRouter(tags=["总览"])


@router.get("/overview", response_model=ApiResponse[dict], summary="平台总览（首页仪表盘）")
async def overview(
    settings: SettingsDep,
    repository: RepositoryDep,
    engine: DesignEngineDep,
) -> dict:
    documents = repository.documents.list_recent(limit=6)
    suites = repository.suites.list_recent(limit=6)
    # 只统计能追溯到源文档的解析结果：孤儿解析结果在界面里没有入口，
    # 计入总览只会变成一个既看不到也删不掉的数字。
    requirements_count = repository.count_linked_requirements()
    work_summary = WorkItemService(settings, repository).summary()

    try:
        reports, reports_total = report_store.list_reports(limit=6, offset=0)
    except Exception:  # 报告库不可用不应让总览整页失败
        reports, reports_total = [], 0

    report_settings = llm_settings()
    provider_available = bool(settings.llm_api_key.strip()) and settings.llm_provider not in {
        "none",
        "null",
        "rule",
    }

    data: dict[str, Any] = {
        "platform": {
            "name": settings.app_name,
            "version": settings.app_version,
        },
        "llm": {
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "base_url": settings.llm_base_url,
            "available": provider_available,
            "source": "runtime" if get_runtime_config_store().read() else "env",
        },
        "counts": {
            "documents": repository.documents.count(),
            "requirements": requirements_count,
            "suites": repository.suites.count(),
            "cases": repository.count_cases(),
            "reports": reports_total,
            "automation_artifacts": repository.automation_artifacts.count(),
            "test_runs": repository.test_runs.count(),
            "work_items_open": work_summary.open_tasks,
            "work_items_overdue": work_summary.overdue,
        },
        "report": {
            "llm_configured": report_settings.configured,
            "thresholds": verdict_thresholds().as_dict(),
        },
        "recent": {
            "documents": [item.model_dump(mode="json") for item in documents],
            "suites": [item.summary().model_dump(mode="json") for item in suites],
            "reports": reports,
            "work_items": [
                item.model_dump(mode="json") for item in work_summary.recent_tasks
            ],
            "work_summary": work_summary.model_dump(mode="json"),
        },
        "capabilities": {
            "methods": engine.available_methods(),
            "export_formats": available_formats(),
            "integrations": available_integrations(),
            "extensions": supported_extensions(),
        },
    }
    return ok(data)
