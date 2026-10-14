"""测试用例生成与查询。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.exceptions import NotFoundError

from app.api.deps import DesignEngineDep, PipelineServiceDep, RepositoryDep
from app.design.coverage import analyze_coverage
from app.schemas.api import (
    ApiResponse,
    BatchDeleteRequest,
    BatchDeleteResult,
    GenerateRequest,
    MethodInfo,
    ok,
)
from app.schemas.coverage import CoverageReport
from app.schemas.testcase import TestCaseSuite, TestCaseSuiteSummary

router = APIRouter(tags=["测试用例"])


@router.get("/testcases/methods", response_model=ApiResponse[list[MethodInfo]], summary="可用设计方法清单")
async def list_methods(engine: DesignEngineDep) -> dict:
    return ok([MethodInfo(**item) for item in engine.available_methods()])


@router.get(
    "/testcases/suites",
    response_model=ApiResponse[list[TestCaseSuiteSummary]],
    summary="最近生成的用例集（不含用例明细）",
)
async def list_suites(
    repository: RepositoryDep,
    limit: int = Query(default=10, ge=1, le=50),
    doc_id: str | None = Query(
        default=None, description="只列出来自该需求 / 文档的用例集（用于需求页反向追溯）"
    ),
) -> dict:
    # 只返回列表需要的字段：用例明细走 GET /testcases/{suite_id}
    def from_doc(suite: TestCaseSuite) -> bool:
        return doc_id is None or suite.doc_id == doc_id

    return ok([suite.summary() for suite in repository.suites.list_recent(limit, predicate=from_doc)])


@router.post("/testcases/generate", response_model=ApiResponse[TestCaseSuite], summary="生成测试用例")
async def generate_testcases(payload: GenerateRequest, pipeline: PipelineServiceDep) -> dict:
    result = await pipeline.run(
        doc_id=payload.doc_id,
        text=payload.text,
        title=payload.title,
        methods=payload.methods,
        use_llm=payload.use_llm,
        use_llm_in_design=payload.use_llm_in_design,
        max_items=payload.max_items,
        max_cases_per_requirement=payload.max_cases_per_requirement,
        llm_design_mode=payload.llm_design_mode,
    )
    return ok(result.suite, message=f"已生成 {result.suite.stats.total} 条测试用例")


@router.get("/testcases/{suite_id}", response_model=ApiResponse[TestCaseSuite], summary="用例集详情")
async def get_suite(suite_id: str, repository: RepositoryDep) -> dict:
    return ok(repository.suites.get(suite_id))


@router.get(
    "/testcases/{suite_id}/coverage",
    response_model=ApiResponse[CoverageReport],
    summary="用例集覆盖率分析（字段 / 边界 / 规则三维 + 缺口清单）",
)
async def suite_coverage(suite_id: str, repository: RepositoryDep) -> dict:
    """相对源需求计算覆盖率。

    用例集里只存了需求 ID，字段与规则的原始约束在需求模型里，因此必须先取到
    需求解析结果才能算覆盖 —— 找不到时如实报错，而不是返回一份「覆盖率 0%」，
    后者会被误读成「这条需求一条都没测」。
    """
    suite = repository.suites.get(suite_id)
    doc = repository.requirements.try_get(suite.doc_id)
    if doc is None:
        raise NotFoundError(
            f"用例集 {suite_id} 的源需求（{suite.doc_id}）已不存在，无法计算覆盖率。"
            "请重新解析需求后再生成用例。",
            detail={"suite_id": suite_id, "doc_id": suite.doc_id},
        )
    report = analyze_coverage(doc, suite)
    return ok(report, message=report.summary)
@router.delete("/testcases/{suite_id}", response_model=ApiResponse[dict], summary="删除用例集")
async def delete_suite(suite_id: str, repository: RepositoryDep) -> dict:
    if not repository.suites.delete(suite_id):
        raise NotFoundError(f"用例集不存在：{suite_id}")
    repository.purge_orphan_requirements()
    return ok({"deleted": True, "suite_id": suite_id}, message="用例集已删除")


@router.post(
    "/testcases/batch-delete",
    response_model=ApiResponse[BatchDeleteResult],
    summary="批量删除用例集",
)
async def batch_delete_suites(payload: BatchDeleteRequest, repository: RepositoryDep) -> dict:
    deleted = 0
    missing: list[str] = []
    for suite_id in dict.fromkeys(payload.ids):
        if repository.suites.delete(suite_id):
            deleted += 1
        else:
            missing.append(suite_id)
    repository.purge_orphan_requirements()
    message = f"已删除 {deleted} 份用例集" + (f"，{len(missing)} 份未找到" if missing else "")
    return ok(BatchDeleteResult(deleted=deleted, missing=missing), message=message)
