"""依赖注入：把配置、Provider、仓储、服务统一装配到路由。

这是"LLM Provider / 导出器 / 设计策略 依赖注入"的落地位置：
路由只声明它需要什么，不关心如何构造，便于测试时整体替换。
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.core.config import Settings
from app.design.engine import DesignEngine
from app.llm.base import LLMProvider
from app.llm.factory import get_effective_settings, get_llm_provider
from app.repository import Repository, get_repository
from app.services.document_service import DocumentService
from app.services.export_service import ExportService
from app.services.pipeline_service import PipelineService
from app.services.requirement_service import RequirementService


def settings_dep() -> Settings:
    """返回「合并了界面覆盖」的生效配置（存储 / 设计引擎等非 LLM 项不受影响）。"""
    return get_effective_settings()


def repository_dep() -> Repository:
    return get_repository()


def llm_dep() -> LLMProvider:
    return get_llm_provider()


def document_service_dep(
    settings: Annotated[Settings, Depends(settings_dep)],
    repository: Annotated[Repository, Depends(repository_dep)],
) -> DocumentService:
    return DocumentService(settings, repository)


def requirement_service_dep(
    settings: Annotated[Settings, Depends(settings_dep)],
    llm: Annotated[LLMProvider, Depends(llm_dep)],
    repository: Annotated[Repository, Depends(repository_dep)],
) -> RequirementService:
    return RequirementService(settings, llm, repository)


def design_engine_dep(settings: Annotated[Settings, Depends(settings_dep)]) -> DesignEngine:
    return DesignEngine(settings)


def export_service_dep(
    settings: Annotated[Settings, Depends(settings_dep)],
    repository: Annotated[Repository, Depends(repository_dep)],
) -> ExportService:
    return ExportService(settings, repository)


def pipeline_service_dep(
    settings: Annotated[Settings, Depends(settings_dep)],
    llm: Annotated[LLMProvider, Depends(llm_dep)],
    repository: Annotated[Repository, Depends(repository_dep)],
) -> PipelineService:
    return PipelineService(settings, llm, repository)


SettingsDep = Annotated[Settings, Depends(settings_dep)]
RepositoryDep = Annotated[Repository, Depends(repository_dep)]
LLMDep = Annotated[LLMProvider, Depends(llm_dep)]
DocumentServiceDep = Annotated[DocumentService, Depends(document_service_dep)]
RequirementServiceDep = Annotated[RequirementService, Depends(requirement_service_dep)]
DesignEngineDep = Annotated[DesignEngine, Depends(design_engine_dep)]
ExportServiceDep = Annotated[ExportService, Depends(export_service_dep)]
PipelineServiceDep = Annotated[PipelineService, Depends(pipeline_service_dep)]
