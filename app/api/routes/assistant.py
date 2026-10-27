"""v3.0 只读 Agent 助手接口。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.agent.tools_readonly import ReadonlyToolbox
from app.api.deps import RepositoryDep, SettingsDep
from app.schemas.api import ApiResponse, ok
from app.schemas.assistant import (
    AssistantAnswer,
    AssistantAskRequest,
    AssistantConversation,
    AssistantConversationSummary,
    AssistantStatus,
    ToolCatalogItem,
)
from app.services.assistant_conversation_service import AssistantConversationService
from app.services.assistant_service import AssistantService

router = APIRouter(tags=["只读助手"])


@router.get(
    "/assistant/tools",
    response_model=ApiResponse[list[ToolCatalogItem]],
    summary="只读助手白名单工具",
)
async def assistant_tools(settings: SettingsDep, repository: RepositoryDep) -> dict:
    items = ReadonlyToolbox(settings, repository).catalog()
    return ok([ToolCatalogItem(**item) for item in items])


@router.get(
    "/assistant/status",
    response_model=ApiResponse[AssistantStatus],
    summary="助手模型与联网能力状态",
)
async def assistant_status(settings: SettingsDep, repository: RepositoryDep) -> dict:
    return ok(AssistantService(settings, repository).status())


@router.get(
    "/assistant/conversations",
    response_model=ApiResponse[list[AssistantConversationSummary]],
    summary="当前项目的助手会话",
)
async def assistant_conversations(
    settings: SettingsDep,
    repository: RepositoryDep,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    return ok(
        AssistantConversationService(settings, repository).list_recent(limit)
    )


@router.get(
    "/assistant/conversations/{conversation_id}",
    response_model=ApiResponse[AssistantConversation],
    summary="读取当前项目的助手会话",
)
async def assistant_conversation(
    conversation_id: str,
    settings: SettingsDep,
    repository: RepositoryDep,
) -> dict:
    return ok(
        AssistantConversationService(settings, repository).get(conversation_id)
    )


@router.post(
    "/assistant/ask",
    response_model=ApiResponse[AssistantAnswer],
    summary="基于当前项目状态与知识引用回答",
)
async def ask_assistant(
    payload: AssistantAskRequest,
    settings: SettingsDep,
    repository: RepositoryDep,
) -> dict:
    result = await AssistantService(settings, repository).ask(payload)
    return ok(result, message="已返回可追溯回答" if result.status != "refused" else "没有可引用依据")


__all__ = ["router"]
