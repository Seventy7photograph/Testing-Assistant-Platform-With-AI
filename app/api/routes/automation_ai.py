"""自动化资产受控 AI 增强接口。"""
from __future__ import annotations

from fastapi import APIRouter, Query, Response

from app.api.deps import AutomationAIServiceDep, LLMDep
from app.api.responses import build_download_response
from app.schemas.api import ApiResponse, ok
from app.schemas.automation_ai import (
    AutomationAIKind,
    AutomationAIRequest,
    AutomationAIReview,
    FindingDecisionRequest,
    ReviewDecisionRequest,
)

router = APIRouter(tags=["自动化 AI 增强"])


@router.post(
    "/automation/ai/reviews",
    response_model=ApiResponse[AutomationAIReview],
    summary="生成受控 AI 建议（覆盖缺口 / 失败断言 / 数据配方 / 脚本审查）",
)
async def create_automation_ai_review(
    payload: AutomationAIRequest,
    service: AutomationAIServiceDep,
    llm: LLMDep,
) -> dict:
    review = await service.create_review(payload, llm)
    return ok(
        review,
        message=(
            f"AI 建议已生成：{len(review.findings)} 条"
            if review.status == "completed"
            else "AI 建议未完成，确定性资产保持不变"
        ),
    )


@router.get(
    "/automation/ai/reviews",
    response_model=ApiResponse[list[AutomationAIReview]],
    summary="自动化受控 AI 建议列表",
)
async def list_automation_ai_reviews(
    service: AutomationAIServiceDep,
    spec_id: str | None = Query(default=None),
    artifact_id: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    kind: AutomationAIKind | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
) -> dict:
    return ok(
        service.list_reviews(
            spec_id=spec_id,
            artifact_id=artifact_id,
            run_id=run_id,
            kind=kind,
            limit=limit,
        )
    )


@router.get(
    "/automation/ai/reviews/{review_id}",
    response_model=ApiResponse[AutomationAIReview],
    summary="自动化受控 AI 建议详情",
)
async def get_automation_ai_review(
    review_id: str,
    service: AutomationAIServiceDep,
) -> dict:
    return ok(service.get_review(review_id))


@router.put(
    "/automation/ai/reviews/{review_id}/findings/{finding_id}",
    response_model=ApiResponse[AutomationAIReview],
    summary="人工采纳或驳回单条 AI 建议",
)
async def decide_automation_ai_finding(
    review_id: str,
    finding_id: str,
    payload: FindingDecisionRequest,
    service: AutomationAIServiceDep,
) -> dict:
    return ok(
        service.set_finding_disposition(review_id, finding_id, payload.disposition),
        message="AI 建议状态已更新",
    )


@router.put(
    "/automation/ai/reviews/{review_id}/decision",
    response_model=ApiResponse[AutomationAIReview],
    summary="人工采纳或驳回整份数据配方建议",
)
async def decide_automation_ai_review(
    review_id: str,
    payload: ReviewDecisionRequest,
    service: AutomationAIServiceDep,
) -> dict:
    return ok(
        service.set_review_decision(review_id, payload.decision),
        message="AI 配方建议状态已更新",
    )


@router.get(
    "/automation/ai/reviews/{review_id}/recipe",
    summary="下载 AI 生成的 fixture / 测试数据配方 JSON",
)
async def download_automation_ai_recipe(
    review_id: str,
    service: AutomationAIServiceDep,
) -> Response:
    content, filename = service.recipe_download(review_id)
    return build_download_response(content, filename, "application/json")


__all__ = ["router"]
