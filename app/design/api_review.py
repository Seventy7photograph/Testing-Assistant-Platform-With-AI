"""接口用例的可选大模型只读复核。

模型只能提出缺口与人工补充建议，不能改写 operation、请求参数、schema 断言
或确定性生成用例。这个边界确保接口契约仍由 OpenAPI 单独决定。
"""
from __future__ import annotations

import copy
import time
from typing import Any

from pydantic import ValidationError

from app.core.exceptions import LLMError, LLMNotConfiguredError
from app.core.utils import dump_json, now_iso, truncate
from app.llm.base import LLMProvider
from app.llm.prompt_registry import PROMPT_API_CASE_REVIEW
from app.llm.prompts import build_api_case_review_messages
from app.schemas.api_testing import (
    ApiCaseSpec,
    ApiOperation,
    ApiReviewFinding,
    ApiReviewMeta,
    ApiReviewResult,
    ApiSpec,
)

MAX_OPERATIONS_PER_BATCH = 12
MAX_REVIEW_CALLS = 6
MAX_FINDINGS_PER_BATCH = 8

_SCHEMA_KEYS = {
    "$ref",
    "type",
    "format",
    "required",
    "nullable",
    "enum",
    "const",
    "pattern",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "properties",
    "items",
    "allOf",
    "oneOf",
    "anyOf",
    "additionalProperties",
    "title",
    "description",
}


def _schema_digest(schema: Any, *, depth: int = 0) -> Any:
    """只保留结构/约束，不把 example/default 等可能含敏感值的字段送入模型。"""
    if depth > 7:
        return {"$truncated": "schema depth limit"}
    if isinstance(schema, list):
        return [_schema_digest(item, depth=depth + 1) for item in schema]
    if not isinstance(schema, dict):
        return schema
    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in _SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            result[key] = {
                name: _schema_digest(item, depth=depth + 1)
                for name, item in value.items()
            }
        elif key in {"allOf", "oneOf", "anyOf"} and isinstance(value, list):
            result[key] = [_schema_digest(item, depth=depth + 1) for item in value]
        elif key in {"items", "additionalProperties"} and isinstance(value, (dict, bool)):
            result[key] = (
                _schema_digest(value, depth=depth + 1)
                if isinstance(value, dict)
                else value
            )
        else:
            result[key] = copy.deepcopy(value)
    return result


def _allowed_source_refs(operations: list[ApiOperation]) -> list[str]:
    refs: list[str] = []
    for operation in operations:
        refs.append(operation.source_ref)
        refs.extend(item.source_ref for item in operation.parameters if item.source_ref)
        if operation.request_body:
            refs.append(operation.request_body.source_ref)
            refs.extend(item.source_ref for item in operation.request_body.content)
        for response in operation.responses:
            refs.append(response.source_ref)
            refs.extend(item.source_ref for item in response.content)
            refs.extend(item.source_ref for item in response.headers if item.source_ref)
    return list(dict.fromkeys(item for item in refs if item))


def _operation_digest(
    operations: list[ApiOperation],
    cases: list[ApiCaseSpec],
) -> str:
    cases_by_operation: dict[str, list[ApiCaseSpec]] = {}
    for case in cases:
        cases_by_operation.setdefault(case.operation_id, []).append(case)

    payload: list[dict[str, Any]] = []
    for operation in operations:
        request_media = operation.request_body.content if operation.request_body else []
        payload.append(
            {
                "operation_id": operation.operation_id,
                "method": operation.method,
                "path": operation.path,
                "summary": operation.summary,
                "source_ref": operation.source_ref,
                "parameters": [
                    {
                        "name": item.name,
                        "in": item.location,
                        "required": item.required,
                        "source_ref": item.source_ref,
                        "schema": _schema_digest(item.schema_),
                    }
                    for item in operation.parameters
                ],
                "request_body": (
                    {
                        "required": operation.request_body.required,
                        "source_ref": operation.request_body.source_ref,
                        "content": [
                            {
                                "content_type": item.content_type,
                                "schema": _schema_digest(item.schema_),
                            }
                            for item in request_media
                        ],
                    }
                    if operation.request_body
                    else None
                ),
                "responses": [
                    {
                        "status": response.status_code,
                        "source_ref": response.source_ref,
                        "content": [
                            {
                                "content_type": item.content_type,
                                "schema": _schema_digest(item.schema_),
                            }
                            for item in response.content
                        ],
                    }
                    for response in operation.responses
                ],
                "security": operation.security,
                "warnings": operation.warnings,
                "generated_cases": [
                    {
                        "case_id": item.case_id,
                        "category": item.category,
                        "title": item.title,
                        "assertions": len(item.assertions),
                        "manual_assertions": sum(
                            1 for assertion in item.assertions if assertion.status == "manual"
                        ),
                        "warnings": item.warnings,
                    }
                    for item in cases_by_operation.get(operation.operation_id, [])
                ],
            }
        )
    return truncate(dump_json(payload, indent=None), 12000)


async def review_api_cases(
    spec: ApiSpec,
    cases: list[ApiCaseSpec],
    llm: LLMProvider,
    *,
    max_calls: int = MAX_REVIEW_CALLS,
    batch_size: int = MAX_OPERATIONS_PER_BATCH,
) -> ApiReviewResult:
    """显式调用模型复核一批接口资产，返回意见而不改动用例。"""
    if not llm.available:
        raise LLMNotConfiguredError(
            "当前没有可用的大模型，无法执行接口用例复核。"
            "可先配置模型，或继续使用确定性契约用例。"
        )

    started = time.perf_counter()
    findings: list[ApiReviewFinding] = []
    warnings: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    reviewed_operations = 0
    calls = 0
    operations = spec.operations
    batches = [
        operations[index : index + max(1, batch_size)]
        for index in range(0, len(operations), max(1, batch_size))
    ]
    batches = batches[: max(max_calls, 0)]
    if len(batches) * max(1, batch_size) < len(operations):
        warnings.append(
            f"本次只复核前 {min(len(operations), len(batches) * max(1, batch_size))} "
            f"个 operation；完整规范共 {len(operations)} 个。"
        )

    for batch in batches:
        allowed_ops = [item.operation_id for item in batch]
        allowed_refs = _allowed_source_refs(batch)
        messages = build_api_case_review_messages(
            _operation_digest(batch, cases),
            allowed_operation_ids=allowed_ops,
            allowed_source_refs=allowed_refs,
        )
        try:
            response = await llm.complete_json(
                messages,
                prompt=PROMPT_API_CASE_REVIEW,
                expect=dict,
            )
        except LLMError as exc:
            warnings.append(f"第 {calls + 1} 批复核失败：{exc.message}")
            break
        calls += 1
        reviewed_operations += len(batch)
        raw_findings = response.parsed.get("findings") if isinstance(response.parsed, dict) else None
        if not isinstance(raw_findings, list):
            warnings.append(f"第 {calls} 批模型结果缺少 findings 数组。")
            continue
        allowed_op_set = set(allowed_ops)
        allowed_ref_set = set(allowed_refs)
        invalid = 0
        accepted = 0
        for raw in raw_findings:
            if accepted >= MAX_FINDINGS_PER_BATCH:
                break
            if not isinstance(raw, dict):
                invalid += 1
                continue
            candidate = dict(raw)
            candidate["claim_status"] = "inferred"
            try:
                finding = ApiReviewFinding.model_validate(candidate)
            except ValidationError:
                invalid += 1
                continue
            if finding.operation_id not in allowed_op_set:
                invalid += 1
                continue
            if finding.source_ref not in allowed_ref_set:
                invalid += 1
                continue
            if not finding.issue.strip():
                invalid += 1
                continue
            key = (finding.operation_id, finding.target, finding.issue)
            if key in seen:
                continue
            seen.add(key)
            findings.append(finding)
            accepted += 1
        if invalid:
            warnings.append(f"第 {calls} 批丢弃 {invalid} 条悬空或不合法的模型意见。")

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return ApiReviewResult(
        spec_id=spec.spec_id,
        findings=findings,
        meta=ApiReviewMeta(
            requested=True,
            used=calls > 0,
            status="completed" if calls > 0 else "failed",
            provider=llm.name,
            model=llm.model,
            prompt_id=PROMPT_API_CASE_REVIEW.prompt_id,
            prompt_version=PROMPT_API_CASE_REVIEW.version,
            temperature=PROMPT_API_CASE_REVIEW.temperature,
            llm_calls=calls,
            reviewed_operations=reviewed_operations,
            elapsed_ms=elapsed_ms,
            warnings=warnings,
        ),
        created_at=now_iso(),
    )


__all__ = ["review_api_cases"]
