"""受控 HTTP 执行器：只执行已校验资产中的接口用例。"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import Settings, get_settings
from app.core.context import get_current_project_id
from app.core.exceptions import BadRequestError, ConflictError
from app.core.logging import sanitize_log_text
from app.core.utils import new_id, now_iso
from app.repository import Repository, get_repository
from app.schemas.api_testing import ApiAssertion, ApiCaseSpec
from app.schemas.execution import CaseResult, TestRun
from app.schemas.jobs import Job
from app.schemas.platform_execution import HttpExecutionRequest, HttpExecutionResponse
from app.services.execution_service import ExecutionService
from app.services.job_service import JobService

_PLACEHOLDER_RE = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)}}")
_SAFE_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
_SENSITIVE_HEADERS = {"authorization", "cookie", "x-api-key", "proxy-authorization"}
_ACTIVE_EXECUTIONS: set[tuple[str, str]] = set()
_ACTIVE_EXECUTIONS_LOCK = asyncio.Lock()


def _milliseconds(seconds: float) -> int:
    return max(int(seconds * 1000), 0)


@dataclass(slots=True)
class _CaseOutcome:
    result: CaseResult
    duration_ms: int


class ControlledHttpExecutor:
    def __init__(
        self,
        settings: Settings | None = None,
        repository: Repository | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or get_repository()
        self.transport = transport

    async def execute(self, request: HttpExecutionRequest) -> HttpExecutionResponse:
        project_id = get_current_project_id() or "PRJ-default"
        execution_key = (project_id, request.artifact_id)
        async with _ACTIVE_EXECUTIONS_LOCK:
            if execution_key in _ACTIVE_EXECUTIONS:
                raise ConflictError(
                    "该自动化资产已有执行任务正在进行，请等待完成后再试。",
                    detail={
                        "artifact_id": request.artifact_id,
                        "project_id": project_id,
                    },
                )
            _ACTIVE_EXECUTIONS.add(execution_key)
        try:
            return await self._execute(request)
        finally:
            async with _ACTIVE_EXECUTIONS_LOCK:
                _ACTIVE_EXECUTIONS.discard(execution_key)

    async def _execute(self, request: HttpExecutionRequest) -> HttpExecutionResponse:
        artifact = self.repository.automation_artifacts.get(request.artifact_id)
        if artifact.status != "validated":
            raise BadRequestError(
                "未通过静态安全校验的资产不能执行。",
                detail={"artifact_id": artifact.artifact_id, "status": artifact.status},
            )
        if not request.case_ids and not request.allow_all_cases:
            raise BadRequestError(
                "请指定要执行的用例 ID；执行全部用例必须显式确认。",
                detail={"artifact_id": artifact.artifact_id},
            )
        allowed_ids = list(dict.fromkeys(request.case_ids or artifact.case_ids))
        extras = [item for item in allowed_ids if item not in set(artifact.case_ids)]
        if extras:
            raise BadRequestError(
                "请求包含不属于该资产的接口用例。",
                detail={"case_ids": extras[:50]},
            )
        if len(allowed_ids) > self.settings.execution_max_cases:
            raise BadRequestError(
                f"单次最多执行 {self.settings.execution_max_cases} 条接口用例。",
                detail={"requested": len(allowed_ids)},
            )
        case_map = {
            item.case_id: item
            for item in self.repository.api_cases.list_recent(limit=20_000)
            if item.case_id in set(allowed_ids)
        }
        missing = [item for item in allowed_ids if item not in case_map]
        if missing:
            raise BadRequestError("部分接口用例已不存在。", detail={"missing": missing})
        cases = [case_map[item] for item in allowed_ids]
        spec = self.repository.api_specs.get(artifact.spec_id)
        allowed_hosts = self._allowed_hosts(spec.servers, request.base_url)
        if not allowed_hosts:
            raise BadRequestError(
                "没有可用于受控执行的目标地址。请在 OpenAPI servers 或本次 base_url 中指定。",
                detail={"artifact_id": artifact.artifact_id},
            )

        jobs = JobService(self.settings, self.repository)
        job = jobs.create(
            _job_create(
                artifact_id=artifact.artifact_id,
                case_count=len(cases),
                idempotency_key=request.idempotency_key,
            )
        )
        jobs.start(job)
        trace_id = job.trace_id
        semaphore = asyncio.Semaphore(max(self.settings.execution_max_concurrency, 1))

        async def run_case(case: ApiCaseSpec) -> _CaseOutcome:
            async with semaphore:
                return await self._execute_case(
                    case,
                    environment=dict(request.environment),
                    allowed_hosts=allowed_hosts,
                    default_base_url=str(
                        request.base_url
                        or (spec.servers[0].url if spec.servers else "")
                    ),
                )

        raw_outcomes = await asyncio.gather(
            *(run_case(case) for case in cases),
            return_exceptions=True,
        )
        outcomes: list[_CaseOutcome] = []
        for case, outcome in zip(cases, raw_outcomes, strict=True):
            if isinstance(outcome, Exception):
                outcomes.append(
                    _CaseOutcome(
                        result=CaseResult(
                            case_id=case.case_id,
                            name=case.title,
                            status="error",
                            operation_id=case.operation_id,
                            message=sanitize_log_text(str(outcome))[:2000],
                        ),
                        duration_ms=0,
                    )
                )
            else:
                outcomes.append(outcome)
        results = [item.result for item in outcomes]
        passed = sum(1 for item in results if item.status == "passed")
        failed = sum(1 for item in results if item.status == "failed")
        errors = sum(1 for item in results if item.status == "error")
        skipped = sum(1 for item in results if item.status == "skipped")
        run = TestRun(
            run_id=new_id("RUN-"),
            artifact_id=artifact.artifact_id,
            spec_id=artifact.spec_id,
            source_file=f"controlled-http:{artifact.artifact_id}",
            framework="controlled-http",
            total=len(results),
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            matched=len(results),
            unmatched=0,
            duration_ms=sum(item.duration_ms for item in outcomes),
            cases=results,
            warnings=[] if results else ["没有可执行的接口用例。"],
        )
        self.repository.test_runs.save(run)
        jobs.finish(
            job,
            succeeded=errors == 0 and failed == 0,
            result={
                "run_id": run.run_id,
                "total": run.total,
                "passed": run.passed,
                "failed": run.failed,
                "errors": run.errors,
            },
            error="" if errors == 0 and failed == 0 else f"执行未全部通过：{failed} failed / {errors} errors",
        )
        ExecutionService(self.settings, self.repository).add_event(
            trace_id=trace_id,
            action="execution.http",
            status="completed" if errors == 0 and failed == 0 else "failed",
            run_id=run.run_id,
            artifact_id=artifact.artifact_id,
            job_id=job.job_id,
            message=(
                f"cases={run.total}; passed={passed}; failed={failed}; "
                f"errors={errors}; skipped={skipped}"
            ),
        )
        return HttpExecutionResponse(job=job, run=run)

    async def _execute_case(
        self,
        case: ApiCaseSpec,
        *,
        environment: dict[str, str],
        allowed_hosts: set[str],
        default_base_url: str,
    ) -> _CaseOutcome:
        started = time.perf_counter()
        if default_base_url:
            environment.setdefault("baseUrl", default_base_url.rstrip("/"))
        execution = case.execution.model_dump(mode="json")
        resolved = self._resolve(execution, environment)
        if self._contains_placeholder(resolved):
            missing_variables = sorted(
                set(_PLACEHOLDER_RE.findall(json.dumps(resolved, ensure_ascii=False)))
            )
            return _CaseOutcome(
                result=CaseResult(
                    case_id=case.case_id,
                    name=case.title,
                    status="skipped",
                    operation_id=case.operation_id,
                    message=(
                        "执行环境缺少变量："
                        + ("、".join(missing_variables) or "未知")
                        + "；为避免发送占位符，请求未发出。"
                    ),
                ),
                duration_ms=_milliseconds(time.perf_counter() - started),
            )
        method = str(resolved.get("method") or case.method or "GET").upper()
        if method not in _SAFE_METHODS:
            return self._failed(case, started, f"不允许的 HTTP 方法：{method}")
        url = str(resolved.get("url") or "")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return self._failed(case, started, "执行 URL 不是合法 http(s) 地址。")
        if parsed.username or parsed.password:
            return self._failed(case, started, "执行 URL 不允许包含用户名或密码。")
        host_key = f"{parsed.hostname}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}"
        if host_key not in allowed_hosts and parsed.hostname not in allowed_hosts:
            return self._failed(case, started, "执行目标不在 OpenAPI servers 或本次 base_url 白名单内。")

        headers = {
            str(key): str(value)
            for key, value in (resolved.get("headers") or {}).items()
            if str(key).lower() not in {"host", "content-length"}
        }
        params = resolved.get("query") or {}
        cookies = resolved.get("cookies") or {}
        kwargs: dict[str, Any] = {"headers": headers, "params": params}
        if cookies:
            kwargs["cookies"] = cookies
        body = resolved.get("body")
        if body is not None:
            if resolved.get("body_kind") == "json":
                kwargs["json"] = body
            else:
                kwargs["content"] = str(body)
        request = httpx.Request(method, url, **kwargs)
        client_kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(self.settings.execution_timeout_seconds, connect=5.0),
            "follow_redirects": False,
        }
        if self.transport is not None:
            client_kwargs["transport"] = self.transport
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.send(request, stream=True)
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self.settings.execution_max_response_bytes:
                        await response.aclose()
                        return self._failed(case, started, "响应体超过受控执行上限，已中止读取。")
                    chunks.append(chunk)
                await response.aclose()
                content = b"".join(chunks)
        except httpx.TimeoutException:
            return self._failed(case, started, f"请求超时（>{self.settings.execution_timeout_seconds}s）。")
        except httpx.HTTPError as exc:
            return self._failed(case, started, f"请求失败：{exc}")

        failures = self._assertions(case.assertions, response, content)
        duration = _milliseconds(time.perf_counter() - started)
        return _CaseOutcome(
            result=CaseResult(
                case_id=case.case_id,
                name=case.title,
                status="failed" if failures else "passed",
                duration_ms=duration,
                operation_id=case.operation_id,
                message="；".join(failures)[:4000],
                stdout=json.dumps(
                    {
                        "status_code": response.status_code,
                        "content_type": response.headers.get("content-type", ""),
                        "response_bytes": len(content),
                    },
                    ensure_ascii=False,
                ),
            ),
            duration_ms=duration,
        )

    def _assertions(
        self,
        assertions: list[ApiAssertion],
        response: httpx.Response,
        content: bytes,
    ) -> list[str]:
        failures: list[str] = []
        payload: Any = None
        parsed = False
        for assertion in assertions:
            if assertion.status != "defined":
                continue
            try:
                if assertion.kind == "status":
                    if response.status_code != int(assertion.expected):
                        failures.append(
                            f"status 期望 {assertion.expected}，实际 {response.status_code}"
                        )
                elif assertion.kind == "header":
                    actual = response.headers.get(assertion.path)
                    if actual is None:
                        failures.append(f"缺少响应头 {assertion.path}")
                    elif assertion.operator == "equals" and actual != str(assertion.expected):
                        failures.append(f"响应头 {assertion.path} 不匹配")
                elif assertion.kind == "json":
                    if not parsed:
                        try:
                            payload = json.loads(content.decode("utf-8"))
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            failures.append("响应不是合法 JSON")
                            parsed = True
                            continue
                        parsed = True
                    values = _values_at_path(payload, assertion.path)
                    failures.extend(_assert_json(assertion, values))
            except (TypeError, ValueError) as exc:
                failures.append(f"断言执行失败：{exc}")
        return failures

    @staticmethod
    def _allowed_hosts(servers: list[Any], base_url: str) -> set[str]:
        urls = [base_url, *(getattr(item, "url", "") for item in servers)]
        result: set[str] = set()
        for raw in urls:
            if not raw:
                continue
            parsed = urlparse(str(raw))
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                continue
            result.add(parsed.hostname)
            result.add(
                f"{parsed.hostname}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}"
            )
        return result

    @classmethod
    def _resolve(cls, value: Any, environment: dict[str, str]) -> Any:
        if isinstance(value, str):
            return _PLACEHOLDER_RE.sub(
                lambda match: str(environment.get(match.group(1), match.group(0))),
                value,
            )
        if isinstance(value, list):
            return [cls._resolve(item, environment) for item in value]
        if isinstance(value, dict):
            return {key: cls._resolve(item, environment) for key, item in value.items()}
        return value

    @classmethod
    def _contains_placeholder(cls, value: Any) -> bool:
        if isinstance(value, str):
            return bool(_PLACEHOLDER_RE.search(value))
        if isinstance(value, list):
            return any(cls._contains_placeholder(item) for item in value)
        if isinstance(value, dict):
            return any(cls._contains_placeholder(item) for item in value.values())
        return False

    @staticmethod
    def _failed(case: ApiCaseSpec, started: float, message: str) -> _CaseOutcome:
        duration = _milliseconds(time.perf_counter() - started)
        return _CaseOutcome(
            result=CaseResult(
                case_id=case.case_id,
                name=case.title,
                status="error",
                duration_ms=duration,
                operation_id=case.operation_id,
                message=sanitize_log_text(message)[:2000],
            ),
            duration_ms=duration,
        )


def _values_at_path(payload: Any, path: str) -> list[Any]:
    if path in {"", "$"}:
        return [payload]
    tokens = re.findall(r"[^.\[\]]+|\[(?:\*|\d+)\]", path.removeprefix("$"))
    values = [payload]
    for token in tokens:
        next_values: list[Any] = []
        if token == "[*]":
            for value in values:
                if isinstance(value, list):
                    next_values.extend(value)
        elif token.startswith("[") and token.endswith("]"):
            index = int(token[1:-1])
            for value in values:
                if isinstance(value, list) and index < len(value):
                    next_values.append(value[index])
        else:
            name = token.removeprefix(".")
            for value in values:
                if isinstance(value, dict) and name in value:
                    next_values.append(value[name])
                elif isinstance(value, list):
                    next_values.extend(
                        item[name]
                        for item in value
                        if isinstance(item, dict) and name in item
                    )
        values = next_values
    return values


def _assert_json(assertion: ApiAssertion, values: list[Any]) -> list[str]:
    if assertion.operator == "nullable":
        # nullable 表示“可为 null”，不是“必须为 null”。类型断言负责校验非空值。
        if assertion.expected is False and any(item is None for item in values):
            return [f"{assertion.path} 不允许为 null"]
        return []
    if assertion.operator == "exists":
        return [] if values and all(item is not None for item in values) else ["字段不存在"]
    if not values:
        return [f"路径不存在：{assertion.path}"]
    expected = assertion.expected
    if assertion.operator == "equals":
        expected_values = expected if isinstance(expected, list) else [expected]
        return [] if values == expected_values else [f"{assertion.path} 值不匹配"]
    checks = {
        "string": lambda value: isinstance(value, str),
        "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
        "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": lambda value: isinstance(value, bool),
        "array": lambda value: isinstance(value, list),
        "object": lambda value: isinstance(value, dict),
        "null": lambda value: value is None,
    }
    try:
        if assertion.operator == "type":
            check = checks.get(str(expected))
            return [] if check and all(check(item) for item in values) else ["类型不匹配"]
        if assertion.operator == "in":
            return [] if all(item in (expected or []) for item in values) else ["枚举不匹配"]
        if assertion.operator == "minLength":
            return [] if all(len(str(item)) >= int(expected) for item in values) else ["长度过短"]
        if assertion.operator == "maxLength":
            return [] if all(len(str(item)) <= int(expected) for item in values) else ["长度过长"]
        if assertion.operator == "gte":
            return [] if all(item >= expected for item in values) else ["数值过小"]
        if assertion.operator == "lte":
            return [] if all(item <= expected for item in values) else ["数值过大"]
    except (TypeError, ValueError):
        return [f"断言值不合法：{assertion.operator}"]
    return [f"未知断言操作：{assertion.operator}"]


def _job_create(*, artifact_id: str, case_count: int, idempotency_key: str):
    from app.schemas.jobs import JobCreate

    return JobCreate(
        kind="execution.http",
        timeout_seconds=600,
        idempotency_key=idempotency_key,
        payload_summary={"artifact_id": artifact_id, "case_count": case_count},
    )


__all__ = ["ControlledHttpExecutor"]
