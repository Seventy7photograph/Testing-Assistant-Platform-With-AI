"""需求解析结果查询与（重新）解析。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.exceptions import NotFoundError

from app.api.deps import PipelineServiceDep, RepositoryDep, RequirementServiceDep
from app.schemas.api import ApiResponse, RequirementParseRequest, ok
from app.schemas.requirement import RequirementDoc
from app.schemas.testcase import TestCaseSuite
from app.schemas.traceability import RequirementDiff, TraceabilityMatrix

router = APIRouter(tags=["需求"])


@router.post("/requirements/parse", response_model=ApiResponse[RequirementDoc], summary="解析需求为结构化模型")
async def parse_requirement(payload: RequirementParseRequest, service: RequirementServiceDep) -> dict:
    if payload.doc_id:
        doc = await service.parse_document(
            payload.doc_id, title=payload.title, use_llm=payload.use_llm, max_items=payload.max_items
        )
    else:
        doc = await service.parse_text(
            payload.text or "",
            title=payload.title,
            use_llm=payload.use_llm,
            max_items=payload.max_items,
        )
    return ok(doc, message="需求解析完成")


@router.get("/requirements/{doc_id}", response_model=ApiResponse[RequirementDoc], summary="获取已解析的需求模型")
async def get_requirement(doc_id: str, service: RequirementServiceDep) -> dict:
    return ok(service.get(doc_id))


@router.get(
    "/requirements/{doc_id}/diff",
    response_model=ApiResponse[RequirementDiff],
    summary="需求变更差异对比（doc_id 为新版，against 为旧版）",
)
async def diff_requirement(
    doc_id: str,
    service: RequirementServiceDep,
    against: str = Query(..., description="用于对比的旧版本需求/文档 ID"),
) -> dict:
    """对比两版需求解析结果，输出新增 / 删除 / 修改清单。

    两版都必须是**已解析**的需求模型（``storage/data/requirements`` 里有记录）：
    没有解析结果就无从比对条目与字段约束，因此这里对缺失的一方明确报 404，
    而不是拿原文做一次模糊文本 diff 交差。
    """
    diff = service.diff(doc_id, against)
    return ok(diff, message=diff.summary)


@router.get(
    "/requirements/{doc_id}/traceability",
    response_model=ApiResponse[TraceabilityMatrix],
    summary="需求-用例双向追溯矩阵",
)
async def requirement_traceability(
    doc_id: str,
    service: RequirementServiceDep,
    suite_limit: int = Query(default=5, ge=1, le=50, description="参与追溯的最近用例集数量"),
) -> dict:
    matrix = service.traceability(doc_id, suite_limit=suite_limit)
    return ok(matrix, message=matrix.summary)


@router.post(
    "/requirements/{doc_id}/testcases",
    response_model=ApiResponse[TestCaseSuite],
    summary="基于已解析需求直接生成用例",
)
async def generate_from_parsed(
    doc_id: str,
    service: RequirementServiceDep,
    pipeline: PipelineServiceDep,
    methods: str | None = Query(
        default=None,
        description="设计方法，逗号分隔（equivalence,boundary,scenario）；省略则使用全部已实现方法。",
    ),
    use_llm_in_design: bool = Query(
        default=False, description="生成阶段是否调用大模型补充场景法用例。"
    ),
    max_cases_per_requirement: int | None = Query(
        default=None,
        ge=10,
        le=2000,
        description="单条需求最多生成多少条用例；省略则用服务端默认值。",
    ),
    llm_design_mode: str = Query(
        default="scenario",
        description="生成阶段大模型的参与方式：scenario / review / enhance（仅在 use_llm_in_design=true 时生效）。",
    ),
) -> dict:
    requirement_doc = service.get(doc_id)
    parsed_methods = [item.strip() for item in methods.split(",") if item.strip()] if methods else None
    suite = await pipeline.generate_from_requirement(
        requirement_doc,
        methods=parsed_methods,
        use_llm_in_design=use_llm_in_design,
        max_cases_per_requirement=max_cases_per_requirement,
        llm_design_mode=llm_design_mode,
    )
    return ok(suite, message="用例生成完成")


@router.delete("/requirements/{doc_id}", response_model=ApiResponse[dict], summary="删除已解析的需求模型")
async def delete_requirement(doc_id: str, repository: RepositoryDep) -> dict:
    if not repository.requirements.delete(doc_id):
        raise NotFoundError(f"需求解析结果不存在：{doc_id}")
    return ok({"deleted": True, "doc_id": doc_id}, message="需求解析结果已删除")
