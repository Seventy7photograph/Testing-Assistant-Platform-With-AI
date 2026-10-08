"""一键流水线：需求 -> 用例。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import PipelineServiceDep
from app.schemas.api import ApiResponse, GenerateRequest, GenerateResult, ok

router = APIRouter(tags=["流水线"])


@router.post(
    "/pipeline/generate",
    response_model=ApiResponse[GenerateResult],
    summary="一键：需求文档 -> 结构化需求 -> 测试用例",
)
async def run_pipeline(payload: GenerateRequest, pipeline: PipelineServiceDep) -> dict:
    result = await pipeline.run(
        doc_id=payload.doc_id,
        text=payload.text,
        title=payload.title,
        methods=payload.methods,
        use_llm=payload.use_llm,
        use_llm_in_design=payload.use_llm_in_design,
        max_items=payload.max_items,
    )
    payload_out = GenerateResult(
        requirement_doc=result.requirement_doc,
        suite=result.suite,
        warnings=result.warnings,
    )
    return ok(payload_out, message=f"流水线执行完成，共生成 {result.suite.stats.total} 条用例")