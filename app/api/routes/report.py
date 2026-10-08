"""测试报告接口：指标计算、AI 报告生成（含流式）、存档、趋势、导出、阈值配置。

统一放在 `/api/v1/report/*` 前缀下，响应体沿用平台的 `{success, code, message, data}` 契约
（流式接口除外，它返回 SSE）。
"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from app.core.exceptions import LLMError, LLMNotConfiguredError, NotFoundError
from app.core.logging import get_logger
from app.report import store
from app.report.config import (
    env_defaults,
    save_thresholds,
    thresholds_source,
    verdict_thresholds,
)
from app.report.llm import complete, llm_settings, probe, stream as llm_stream
from app.report.metrics import compute_metrics
from app.report.prompts import build_user_prompt
from app.report.samples import SAMPLES
from app.schemas.api import ApiResponse, BatchDeleteRequest, BatchDeleteResult, ok
from app.report.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    MetricsRequest,
    MetricsResult,
    ReportLLMTestResponse,
    ReportDetail,
    ReportListResponse,
    SampleDataset,
    ThresholdUpdate,
    ThresholdView,
    TrendPoint,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/report", tags=["测试报告"])

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# 送进模型的原文上限。指标永远基于完整数据计算，只有 prompt 里的原文会被截断 ——
# 粘贴一份几 MB 的执行日志否则会直接打满上下文并白白烧额度。
_MAX_PROMPT_DATA = 20000


def _prepare(req: AnalyzeRequest) -> tuple[MetricsResult, str]:
    """先算指标，再把原始数据整理成便于模型阅读的形式。"""

    result = compute_metrics(req.test_data, verdict_thresholds())
    normalized = req.test_data
    try:
        normalized = json.dumps(json.loads(req.test_data), ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, TypeError):
        pass

    if len(normalized) > _MAX_PROMPT_DATA:
        result.warnings.append(
            f"原始数据 {len(normalized)} 字符，超过 {_MAX_PROMPT_DATA} 字符上限；"
            "指标仍按完整数据计算，但送入模型的原文已截断。"
        )
        normalized = normalized[:_MAX_PROMPT_DATA] + "\n…（原文过长已截断）"

    return result, normalized


def _default_title(req: AnalyzeRequest, result: MetricsResult) -> str:
    if req.title and req.title.strip():
        return req.title.strip()
    if result.version:
        return f"测试报告 {result.version}"
    return "测试报告"


def _record_payload(
    *,
    req: AnalyzeRequest,
    result: MetricsResult,
    report: str,
    settings: Any,
    created_at: str,
    elapsed_ms: int,
    usage: dict[str, Any] | None,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "created_at": created_at,
        "title": _default_title(req, result),
        "version": result.version,
        "model": settings.model,
        "provider": settings.provider,
        "instruction": req.instruction,
        "source_data": req.test_data,
        "report": report,
        "metrics": result.metrics.model_dump() if result.metrics else None,
        "defects": [defect.model_dump() for defect in result.defects],
        "usage": usage,
        "warnings": warnings,
        "elapsed_ms": elapsed_ms,
    }


@router.get("/status", response_model=ApiResponse[dict], summary="报告模块运行状态")
async def report_status() -> dict:
    settings = llm_settings()
    try:
        count = store.count_reports()
    except Exception:  # 存档不可用不应拖垮整个界面
        count = 0
    return ok(
        {
            "llm_configured": settings.configured,
            "provider": settings.provider,
            "model": settings.model,
            "base_url": settings.base_url,
            "thresholds": verdict_thresholds().as_dict(),
            "storage_backend": "SQLite",
            "storage_path": str(store.db_path()),
            "report_count": count,
        }
    )


@router.post("/metrics", response_model=ApiResponse[MetricsResult], summary="只算指标，不调模型")
async def compute_only(payload: MetricsRequest) -> dict:
    return ok(compute_metrics(payload.test_data, verdict_thresholds()))


@router.get("/samples", response_model=ApiResponse[list[SampleDataset]], summary="内置示例数据集")
async def list_samples() -> dict:
    return ok(SAMPLES)


@router.post("/analyze", response_model=ApiResponse[AnalyzeResponse], summary="指标 + AI 报告（一次性返回）")
async def analyze(payload: AnalyzeRequest) -> dict:
    result, normalized = _prepare(payload)
    settings = llm_settings(model=payload.model, temperature=payload.temperature)

    if not settings.configured:
        raise LLMNotConfiguredError(
            "未配置 LLM_API_KEY，无法生成 AI 报告。请先在「大模型配置」页填写并保存。"
        )

    user_prompt = build_user_prompt(result, normalized, payload.instruction)
    started = time.perf_counter()
    try:
        report, usage = await complete(user_prompt, settings)
    except HTTPException as exc:
        raise LLMError(str(exc.detail)) from exc
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    created_at = store.utc_now_iso()
    warnings = list(result.warnings)
    report_id: str | None = None
    if payload.save:
        try:
            report_id = store.save_report(
                _record_payload(
                    req=payload,
                    result=result,
                    report=report,
                    settings=settings,
                    created_at=created_at,
                    elapsed_ms=elapsed_ms,
                    usage=usage,
                    warnings=warnings,
                )
            )
        except Exception as exc:  # 存档失败不应该让报告丢失
            warnings.append(f"存档写入失败：{exc}")

    response = AnalyzeResponse(
        id=report_id,
        report=report,
        model=settings.model,
        provider=settings.provider,
        metrics=result.metrics,
        warnings=warnings,
        version=result.version,
        created_at=created_at,
        elapsed_ms=elapsed_ms,
        usage=usage,
    )
    return ok(response, message="报告已生成")


def _sse(event: str, payload: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/analyze/stream", summary="指标 + AI 报告（SSE 流式）")
async def analyze_stream(payload: AnalyzeRequest) -> StreamingResponse:
    """流式生成。事件顺序：meta → metrics → delta* → done（或 error）。"""

    result, normalized = _prepare(payload)
    settings = llm_settings(model=payload.model, temperature=payload.temperature)
    user_prompt = build_user_prompt(result, normalized, payload.instruction)
    created_at = store.utc_now_iso()

    async def event_stream() -> AsyncIterator[str]:
        yield _sse(
            "meta",
            {
                "model": settings.model,
                "provider": settings.provider,
                "created_at": created_at,
                "version": result.version,
                "warnings": result.warnings,
            },
        )
        if result.metrics:
            yield _sse("metrics", result.metrics.model_dump())

        if not settings.configured:
            yield _sse(
                "error",
                {"detail": "未配置 LLM_API_KEY，无法生成 AI 报告。请先在「大模型配置」中填写。", "status": 503},
            )
            return

        started = time.perf_counter()
        chunks: list[str] = []
        usage: dict[str, Any] = {}
        try:
            # stream 拿到 usage 分片时回调这里，归档才记得到 token 用量。
            async for delta in llm_stream(user_prompt, settings, usage.update):
                chunks.append(delta)
                yield _sse("delta", {"text": delta})
        except HTTPException as exc:
            yield _sse("error", {"detail": exc.detail, "status": exc.status_code})
            return
        except Exception as exc:  # 兜底，避免流悬挂
            yield _sse("error", {"detail": f"生成中断：{exc}", "status": 500})
            return

        report = "".join(chunks)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        warnings = list(result.warnings)
        report_id: str | None = None
        if payload.save and report.strip():
            try:
                report_id = store.save_report(
                    _record_payload(
                        req=payload,
                        result=result,
                        report=report,
                        settings=settings,
                        created_at=created_at,
                        elapsed_ms=elapsed_ms,
                        usage=usage or None,
                        warnings=warnings,
                    )
                )
            except Exception as exc:
                warnings.append(f"存档写入失败：{exc}")

        yield _sse(
            "done",
            {
                "id": report_id,
                "elapsed_ms": elapsed_ms,
                "warnings": warnings,
                "saved": bool(report_id),
            },
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/probe", response_model=ApiResponse[ReportLLMTestResponse], summary="报告链路模型探活")
async def report_probe() -> dict:
    settings = llm_settings()
    if not settings.configured:
        return ok(
            ReportLLMTestResponse(
                ok=False,
                model=settings.model,
                provider=settings.provider,
                message="未配置 API Key，报告链路当前不可用。",
            )
        )
    try:
        latency, reply = await probe(settings)
    except HTTPException as exc:
        return ok(
            ReportLLMTestResponse(
                ok=False,
                model=settings.model,
                provider=settings.provider,
                message=str(exc.detail),
            )
        )
    return ok(
        ReportLLMTestResponse(
            ok=True,
            model=settings.model,
            provider=settings.provider,
            latency_ms=latency,
            message=reply or "服务正常",
        )
    )


# ------------------------------------------------------------------ 存档

@router.get("/reports", response_model=ApiResponse[ReportListResponse], summary="历史报告列表")
async def list_reports(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, description="按标题/版本/模型/正文搜索"),
    verdict: str | None = Query(None, description="按判定过滤"),
) -> dict:
    items, total = store.list_reports(limit=limit, offset=offset, query=q, verdict=verdict)
    return ok(ReportListResponse(items=items, total=total))


@router.get("/trends", response_model=ApiResponse[list[TrendPoint]], summary="趋势数据点")
async def trends(limit: int = Query(12, ge=2, le=50)) -> dict:
    return ok([TrendPoint(**point) for point in store.trend_points(limit=limit)])


@router.get("/reports/{report_id}", response_model=ApiResponse[ReportDetail], summary="报告详情")
async def get_report(report_id: str) -> dict:
    record = store.get_report(report_id)
    if record is None:
        raise NotFoundError(f"报告存档不存在：{report_id}")
    return ok(ReportDetail(**record))


@router.delete("/reports/{report_id}", response_model=ApiResponse[dict], summary="删除报告")
async def delete_report(report_id: str) -> dict:
    if not store.delete_report(report_id):
        raise NotFoundError(f"报告存档不存在：{report_id}")
    return ok({"deleted": True, "id": report_id}, message="已删除")


@router.post(
    "/reports/batch-delete",
    response_model=ApiResponse[BatchDeleteResult],
    summary="批量删除报告存档",
)
async def batch_delete_reports(payload: BatchDeleteRequest) -> dict:
    deleted = 0
    missing: list[str] = []
    for report_id in dict.fromkeys(payload.ids):
        if store.delete_report(report_id):
            deleted += 1
        else:
            missing.append(report_id)
    message = f"已删除 {deleted} 份报告" + (f"，{len(missing)} 份未找到" if missing else "")
    return ok(BatchDeleteResult(deleted=deleted, missing=missing), message=message)


@router.get("/reports/{report_id}/export", summary="导出报告（md / html / docx / json）")
async def export_report(
    report_id: str,
    export_format: str = Query("md", alias="format", pattern="^(md|html|docx|json)$"),
) -> Response:
    from urllib.parse import quote

    from app.report.exporters import to_docx, to_html, to_markdown

    record = store.get_report(report_id)
    if record is None:
        raise NotFoundError(f"报告存档不存在：{report_id}")

    stem = (record.get("title") or "测试报告").strip().replace("/", "-").replace("\\", "-")
    filename = f"{stem}_{report_id}.{export_format}"
    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"

    if export_format == "md":
        return Response(
            content=to_markdown(record),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": disposition},
        )
    if export_format == "html":
        return Response(
            content=to_html(record),
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": disposition},
        )
    if export_format == "docx":
        return Response(
            content=to_docx(record),
            media_type=_DOCX_MIME,
            headers={"Content-Disposition": disposition},
        )
    return Response(
        content=json.dumps(record, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": disposition},
    )


# ------------------------------------------------------------------ 判定阈值

@router.get("/thresholds", response_model=ApiResponse[ThresholdView], summary="发版判定阈值")
async def read_thresholds() -> dict:
    view = ThresholdView(
        thresholds=verdict_thresholds().as_dict(),
        defaults=env_defaults(),
        sources=thresholds_source(),
    )
    return ok(view)


@router.put("/thresholds", response_model=ApiResponse[ThresholdView], summary="保存发版判定阈值")
async def update_thresholds(payload: ThresholdUpdate) -> dict:
    if payload.reset:
        from app.report.config import clear_thresholds

        clear_thresholds()
    else:
        values = payload.model_dump(exclude={"reset"}, exclude_unset=True)
        if values:
            save_thresholds(values)
    view = ThresholdView(
        thresholds=verdict_thresholds().as_dict(),
        defaults=env_defaults(),
        sources=thresholds_source(),
    )
    return ok(view, message="已保存判定阈值")


@router.delete("/thresholds", response_model=ApiResponse[ThresholdView], summary="恢复阈值到 .env 默认")
async def reset_thresholds() -> dict:
    from app.report.config import clear_thresholds

    clear_thresholds()
    view = ThresholdView(
        thresholds=verdict_thresholds().as_dict(),
        defaults=env_defaults(),
        sources=thresholds_source(),
    )
    return ok(view, message="已恢复 .env 默认阈值")
