"""v3.0 项目级知识索引与检索接口。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import RepositoryDep, SettingsDep
from app.knowledge.indexer import KnowledgeService
from app.schemas.api import ApiResponse, ok
from app.schemas.knowledge import (
    KnowledgeIndexStats,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
)

router = APIRouter(tags=["知识库"])


@router.get(
    "/knowledge/stats",
    response_model=ApiResponse[KnowledgeIndexStats],
    summary="当前项目知识索引统计",
)
async def knowledge_stats(settings: SettingsDep, repository: RepositoryDep) -> dict:
    return ok(KnowledgeService(settings, repository).stats())


@router.post(
    "/knowledge/search",
    response_model=ApiResponse[KnowledgeSearchResult],
    summary="项目内全文检索（返回来源、版本与定位）",
)
async def search_knowledge(
    payload: KnowledgeSearchRequest,
    settings: SettingsDep,
    repository: RepositoryDep,
) -> dict:
    return ok(KnowledgeService(settings, repository).search(payload))


@router.post(
    "/knowledge/sync",
    response_model=ApiResponse[KnowledgeIndexStats],
    summary="重建当前项目知识索引",
)
async def sync_knowledge(settings: SettingsDep, repository: RepositoryDep) -> dict:
    result = KnowledgeService(settings, repository).sync_all()
    return ok(result, message=f"已索引 {result.indexed} 个知识源。")


__all__ = ["router"]
