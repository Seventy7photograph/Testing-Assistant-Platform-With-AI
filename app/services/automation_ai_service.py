"""V2.3.2 自动化资产受控 AI 建议与应用服务。

模型只产出待人工确认的建议、断言提案、数据配方与只读审查意见。
本服务不会改写 AutomationArtifact、cases.json、确定性断言或生成器模板。
"""
from __future__ import annotations

import time
import re
from collections.abc import Iterable
from hashlib import sha256
from typing import Any, Literal

from pydantic import ValidationError

from app.automation.pytest_generator import build_pytest_artifact
from app.automation.validators import SECRET_PATTERNS, validate_generated_files
from app.core.config import Settings, get_settings
from app.core.exceptions import BadRequestError, ConflictError, LLMNotConfiguredError, NotFoundError
from app.core.logging import get_logger, sanitize_log_text
from app.core.utils import dump_json, new_id, now_iso, truncate
from app.llm.base import LLMProvider
from app.llm.prompt_registry import (
    PROMPT_AUTOMATION_FAILURE_ASSERTION,
    PROMPT_AUTOMATION_FIXTURE_RECIPE,
    PROMPT_AUTOMATION_OPERATION_GAP,
    PROMPT_AUTOMATION_SCRIPT_REVIEW,
    PromptSpec,
)
from app.llm.prompts import (
    build_automation_failure_assertion_messages,
    build_automation_fixture_recipe_messages,
    build_automation_operation_gap_messages,
    build_automation_script_review_messages,
)
from app.repository import Repository, get_repository
from app.schemas.api_testing import ApiAssertion, ApiCaseSpec, ApiOperation, ApiSpec
from app.schemas.automation_ai import (
    AIApiCaseProposal,
    AIAssertionProposal,
    AutomationAIFinding,
    AutomationAIKind,
    AutomationAIMeta,
    AutomationAIRequest,
    AutomationAIReview,
    AutomationFixtureRecipe,
    FixtureEnvironmentVariable,
    ReviewDecision,
)
from app.schemas.execution import AutomationArtifact, GeneratedFile, TestRun
from app.services.execution_service import ExecutionService

logger = get_logger(__name__)
_MAX_REVIEW_FINDINGS = 8
_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_UNSAFE_RECIPE_PATTERNS = (
    re.compile(r"(?i)\bsubprocess\b"),
    re.compile(r"(?i)\beval\s*\("),
    re.compile(r"(?i)\bexec\s*\("),
    re.compile(r"(?i)\bos\.system\b"),
    re.compile(r"(?i)\bInvoke-Expression\b"),
    re.compile(r"(?i)\brm\s+-rf\b"),
)


class _PreparedReview:
    def __init__(
        self,
        *,
        prompt: PromptSpec,
        messages: list[Any],
        context: dict[str, Any],
        allowed_operations: set[str] | None = None,
        allowed_cases: set[str] | None = None,
        allowed_sources: set[str] | None = None,
        case_operation_map: dict[str, str] | None = None,
        operation_sources: dict[str, set[str]] | None = None,
        case_sources: dict[str, set[str]] | None = None,
        fallback_summary: str = "",
    ) -> None:
        self.prompt = prompt
        self.messages = messages
        self.context = context
        self.allowed_operations = allowed_operations or set()
        self.allowed_cases = allowed_cases or set()
        self.allowed_sources = allowed_sources or set()
        self.case_operation_map = case_operation_map or {}
        self.operation_sources = operation_sources or {}
        self.case_sources = case_sources or {}
        self.fallback_summary = fallback_summary


class AutomationAIService:
    def __init__(
        self,
        settings: Settings | None = None,
        repository: Repository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or get_repository()

    async def create_review(
        self,
        request: AutomationAIRequest,
        llm: LLMProvider,
    ) -> AutomationAIReview:
        if not llm.available:
            raise LLMNotConfiguredError(
                "当前没有可用的大模型，无法执行自动化受控增强。"
                "确定性资产生成、下载与 JUnit 回收仍可正常使用。"
            )
        self._ensure_not_running(request)
        prepared = self._prepare(request)
        review = AutomationAIReview(
            review_id=new_id("AIR-"),
            kind=request.kind,
            spec_id=request.spec_id,
            artifact_id=request.artifact_id,
            run_id=request.run_id,
            focus=request.focus.strip(),
            status="running",
            summary="正在生成受控建议…",
            context=prepared.context,
            meta=AutomationAIMeta(
                used=False,
                status="running",
                provider=llm.name,
                model=llm.model,
                prompt_id=prepared.prompt.prompt_id,
                prompt_version=prepared.prompt.version,
                temperature=prepared.prompt.temperature,
            ),
        )
        self.repository.automation_ai_reviews.save(review)
        self._event("automation.ai_review", "running", review)

        if not prepared.messages:
            review.status = "completed"
            review.summary = prepared.fallback_summary
            review.meta.status = "completed"
            review.updated_at = now_iso()
            self.repository.automation_ai_reviews.save(review)
            self._event("automation.ai_review", "completed", review)
            return review

        started = time.perf_counter()
        try:
            response = await llm.complete_json(
                prepared.messages,
                prompt=prepared.prompt,
                expect=dict,
            )
            review.meta.llm_calls = 1
            review.meta.used = True
            self._apply_response(review, prepared, response.parsed)
            review.status = "completed"
            review.meta.status = "completed"
            review.summary = review.summary or prepared.fallback_summary
        except Exception as exc:  # noqa: BLE001 - 失败状态必须落盘
            review.status = "failed"
            review.meta.status = "failed"
            review.summary = "AI 建议生成失败，确定性资产保持不变。"
            review.meta.warnings.append(sanitize_log_text(f"AI 增强失败：{exc}", 800))
            logger.warning("自动化 AI 增强失败 review=%s kind=%s: %s", review.review_id, review.kind, exc)
        review.meta.elapsed_ms = int((time.perf_counter() - started) * 1000)
        review.updated_at = now_iso()
        self.repository.automation_ai_reviews.save(review)
        self._event("automation.ai_review", review.status, review)
        return review

    def list_reviews(
        self,
        *,
        spec_id: str | None = None,
        artifact_id: str | None = None,
        run_id: str | None = None,
        kind: AutomationAIKind | None = None,
        limit: int = 30,
    ) -> list[AutomationAIReview]:
        return self.repository.automation_ai_reviews.list_recent(
            min(max(limit, 1), 100),
            predicate=lambda item: (
                (spec_id is None or item.spec_id == spec_id)
                and (artifact_id is None or item.artifact_id == artifact_id)
                and (run_id is None or item.run_id == run_id)
                and (kind is None or item.kind == kind)
            ),
        )

    def get_review(self, review_id: str) -> AutomationAIReview:
        return self.repository.automation_ai_reviews.get(review_id)

    def set_finding_disposition(
        self,
        review_id: str,
        finding_id: str,
        disposition: Literal["accepted", "rejected"],
    ) -> AutomationAIReview:
        review = self.get_review(review_id)
        if review.status != "completed":
            raise ConflictError("只有已完成的 AI 建议才能人工采纳或驳回。")
        if review.applied_artifact_id:
            raise ConflictError("该建议已经生成派生资产，不能再修改决定。")
        finding = next((item for item in review.findings if item.finding_id == finding_id), None)
        if finding is None:
            raise NotFoundError(f"AI 建议项不存在：{finding_id}")
        finding.disposition = disposition
        review.updated_at = now_iso()
        self.repository.automation_ai_reviews.save(review)
        self._event("automation.ai_review.decision", "completed", review)
        return review

    def set_review_decision(
        self,
        review_id: str,
        decision: Literal["accepted", "rejected"],
    ) -> AutomationAIReview:
        review = self.get_review(review_id)
        if review.status != "completed":
            raise ConflictError("只有已完成的 AI 建议才能人工采纳或驳回。")
        if review.applied_artifact_id:
            raise ConflictError("该建议已经生成派生资产，不能再修改决定。")
        review.decision = decision
        review.updated_at = now_iso()
        self.repository.automation_ai_reviews.save(review)
        self._event("automation.ai_review.decision", "completed", review)
        return review

    def apply_review(self, review_id: str) -> AutomationArtifact:
        """把已采纳建议应用到派生版本，原资产与源 case 保持不可变。"""
        review = self.get_review(review_id)
        if review.status != "completed":
            raise ConflictError("只有已完成的 AI 建议才能生成新资产版本。")
        if review.applied_artifact_id:
            raise ConflictError(
                "该 AI 建议已经生成过派生资产。",
                detail={"applied_artifact_id": review.applied_artifact_id},
            )
        if review.kind == "script_review":
            raise BadRequestError("脚本只读审查不能自动生成新资产，请人工修改生成模板后重新生成。")
        if not review.artifact_id:
            raise BadRequestError("该 AI 建议没有关联自动化资产。")
        source_artifact = self._artifact_for_spec(review.artifact_id, review.spec_id)
        if source_artifact is None:
            raise NotFoundError(f"自动化资产不存在：{review.artifact_id}")
        if source_artifact.status != "validated":
            raise BadRequestError("源自动化资产未通过安全校验，不能派生新版本。")

        spec = self.repository.api_specs.get(review.spec_id)
        all_cases = {item.case_id: item for item in self._cases_for_spec(review.spec_id)}
        selected_cases: list[ApiCaseSpec] = []
        for case_id in source_artifact.case_ids:
            case = all_cases.get(case_id) or self.repository.api_cases.try_get(case_id)
            if case is not None:
                selected_cases.append(case)
        if not selected_cases:
            raise BadRequestError("源自动化资产没有可读取的接口用例。")

        changes: list[str] = []
        if review.kind == "operation_gap":
            accepted = [
                item
                for item in review.findings
                if item.disposition == "accepted" and item.proposed_case is not None
            ]
            if not accepted:
                raise BadRequestError("没有已采纳且结构完整的 case 提案可应用。")
            for finding in accepted:
                proposal = finding.proposed_case
                assert proposal is not None
                base = self._resolve_base_case(proposal, all_cases)
                new_case = self._new_case_from_proposal(base, proposal)
                self.repository.api_cases.save(new_case)
                selected_cases.append(new_case)
                all_cases[new_case.case_id] = new_case
                changes.append(f"新增 AI case：{new_case.title}")
        elif review.kind == "failure_assertion":
            accepted = [
                item
                for item in review.findings
                if item.disposition == "accepted" and item.proposed_assertion is not None
            ]
            if not accepted:
                raise BadRequestError("没有已采纳且结构完整的 assertion 提案可应用。")
            groups: dict[str, list[AIAssertionProposal]] = {}
            for finding in accepted:
                assert finding.proposed_assertion is not None
                if finding.case_id:
                    groups.setdefault(finding.case_id, []).append(finding.proposed_assertion)
            replacement: dict[str, ApiCaseSpec] = {}
            for case_id, assertions in groups.items():
                base = all_cases.get(case_id)
                if base is None:
                    continue
                new_case = self._copy_case_with_assertions(base, assertions)
                self.repository.api_cases.save(new_case)
                replacement[case_id] = new_case
                changes.append(f"派生断言版本：{base.case_id} → {new_case.case_id}")
            if not replacement:
                raise BadRequestError("已采纳断言没有匹配到当前规范中的 case。")
            selected_cases = [
                replacement.get(case.case_id, case) for case in selected_cases
            ]
        else:
            if review.decision != "accepted" or review.recipe is None:
                raise BadRequestError("请先采纳数据配方，再生成新资产版本。")

        artifact = build_pytest_artifact(
            spec,
            selected_cases,
            artifact_id=new_id("AUTO-"),
            revision=self.repository.next_artifact_revision(spec.spec_id),
        )
        artifact.parent_artifact_id = source_artifact.artifact_id
        artifact.source_review_id = review.review_id
        artifact.change_summary = changes

        if review.kind == "fixture_recipe" and review.recipe is not None:
            artifact.files = self._merge_recipe_into_files(artifact.files, review)
            artifact.change_summary = [
                "生成 fixtures.json",
                "生成 test_data.json",
                "更新 .env.example",
            ]

        validation = validate_generated_files(artifact.files)
        artifact.validation_errors = validation.errors
        artifact.warnings.extend(validation.warnings)
        artifact.status = "validated" if validation.ok else "rejected"
        self.repository.automation_artifacts.save(artifact)

        review.applied_artifact_id = artifact.artifact_id
        review.applied_at = now_iso()
        review.updated_at = review.applied_at
        self.repository.automation_ai_reviews.save(review)
        self._event("automation.ai_apply", artifact.status, review)
        return artifact

    def recipe_download(self, review_id: str) -> tuple[bytes, str]:
        review = self.get_review(review_id)
        if review.recipe is None:
            raise NotFoundError(f"AI 建议不包含数据配方：{review_id}")
        payload = {
            "review_id": review.review_id,
            "kind": review.kind,
            "spec_id": review.spec_id,
            "artifact_id": review.artifact_id,
            "decision": review.decision,
            "summary": review.recipe.summary or review.summary,
            "recipe": review.recipe.model_dump(mode="json"),
            "meta": review.meta.model_dump(mode="json"),
            "disclaimer": "AI 生成建议，仅供人工审查；不是可执行代码。",
        }
        return dump_json(payload).encode("utf-8"), f"{review.review_id}-fixture-recipe.json"

    # ------------------------------------------------------------------
    # Context preparation
    # ------------------------------------------------------------------
    def _prepare(self, request: AutomationAIRequest) -> _PreparedReview:
        spec = self.repository.api_specs.get(request.spec_id)
        if request.kind == "operation_gap":
            return self._prepare_operation_gap(spec, request)
        if request.kind == "failure_assertion":
            return self._prepare_failure_assertion(spec, request)
        if request.kind == "fixture_recipe":
            return self._prepare_fixture_recipe(spec, request)
        return self._prepare_script_review(spec, request)

    def _prepare_operation_gap(
        self,
        spec: ApiSpec,
        request: AutomationAIRequest,
    ) -> _PreparedReview:
        artifact = self._artifact_for_spec(request.artifact_id, spec.spec_id)
        cases = self._cases_for_spec(spec.spec_id)
        covered = (
            set(artifact.operation_ids)
            if artifact is not None
            else {item.operation_id for item in cases}
        )
        operations = [item for item in spec.operations if item.operation_id not in covered]
        allowed_refs = _allowed_source_refs(operations)
        context = {
            "artifact_id": artifact.artifact_id if artifact else None,
            "covered_operation_count": len(covered),
            "uncovered_operations": [item.operation_id for item in operations[:12]],
            "uncovered_operation_total": len(operations),
        }
        if not operations:
            return _PreparedReview(
                prompt=PROMPT_AUTOMATION_OPERATION_GAP,
                messages=[],
                context=context,
                fallback_summary="当前自动化资产已覆盖全部 operation，没有需要 AI 补充的覆盖缺口。",
            )
        selected = operations[:12]
        digest = dump_json(
            [
                {
                    "operation_id": item.operation_id,
                    "method": item.method,
                    "path": item.path,
                    "summary": item.summary,
                    "parameters": [
                        {
                            "name": parameter.name,
                            "in": parameter.location,
                            "required": parameter.required,
                            "schema": _schema_digest(parameter.schema_),
                            "source_ref": parameter.source_ref,
                        }
                        for parameter in item.parameters
                    ],
                    "request_body_required": bool(item.request_body and item.request_body.required),
                    "response_statuses": [response.status_code for response in item.responses],
                    "security_required": bool(item.security),
                    "source_ref": item.source_ref,
                }
                for item in selected
            ]
        )
        return _PreparedReview(
            prompt=PROMPT_AUTOMATION_OPERATION_GAP,
            messages=build_automation_operation_gap_messages(
                digest,
                allowed_operation_ids=[item.operation_id for item in selected],
                allowed_source_refs=allowed_refs,
                focus=request.focus,
            ),
            context=context,
            allowed_operations={item.operation_id for item in selected},
            allowed_sources=set(allowed_refs),
            operation_sources={
                item.operation_id: set(_allowed_source_refs([item]))
                for item in selected
            },
            fallback_summary="AI 未返回可确认的 operation 覆盖建议。",
        )

    def _prepare_failure_assertion(
        self,
        spec: ApiSpec,
        request: AutomationAIRequest,
    ) -> _PreparedReview:
        if not request.run_id:
            raise BadRequestError("失败断言建议必须选择一条执行记录。")
        run = self.repository.test_runs.get(request.run_id)
        if run.spec_id and run.spec_id != spec.spec_id:
            raise BadRequestError("执行记录不属于当前接口规范。")
        if request.artifact_id and run.artifact_id and request.artifact_id != run.artifact_id:
            raise BadRequestError("执行记录与所选自动化资产不一致。")
        if run.artifact_id:
            run_artifact = self.repository.automation_artifacts.get(run.artifact_id)
            if run_artifact.spec_id != spec.spec_id:
                raise BadRequestError("执行记录关联的资产不属于当前接口规范。")
        failures = [
            item for item in [*run.cases, *run.unmatched_cases]
            if item.status in {"failed", "error"}
        ]
        cases = {item.case_id: item for item in self._cases_for_spec(spec.spec_id)}
        matched = [
            (result, cases[result.case_id])
            for result in failures
            if result.case_id and result.case_id in cases
        ][:8]
        allowed_cases = {case.case_id for _result, case in matched}
        allowed_sources = _case_source_refs([case for _result, case in matched])
        allowed_ops = {case.operation_id for _result, case in matched}
        context = {
            "run_id": run.run_id,
            "source_file": run.source_file,
            "failed": run.failed,
            "errors": run.errors,
            "unmatched": run.unmatched,
            "candidate_cases": sorted(allowed_cases),
        }
        if not matched:
            return _PreparedReview(
                prompt=PROMPT_AUTOMATION_FAILURE_ASSERTION,
                messages=[],
                context=context,
                fallback_summary="该运行没有可映射到当前规范的失败 case，无法生成断言建议。",
            )
        digest = dump_json(
            [
                {
                    "case_id": case.case_id,
                    "operation_id": case.operation_id,
                    "title": case.title,
                    "method": case.method,
                    "path": case.path,
                    "failure_status": result.status,
                    "failure_message": truncate(result.message, 1200),
                    "current_assertions": [
                        {
                            "kind": assertion.kind,
                            "path": assertion.path,
                            "operator": assertion.operator,
                            "expected": assertion.expected,
                            "source_ref": assertion.source_ref,
                            "status": assertion.status,
                        }
                        for assertion in case.assertions
                    ],
                    "case_source_ref": case.source_ref,
                }
                for result, case in matched
            ]
        )
        return _PreparedReview(
            prompt=PROMPT_AUTOMATION_FAILURE_ASSERTION,
            messages=build_automation_failure_assertion_messages(
                digest,
                allowed_case_ids=sorted(allowed_cases),
                allowed_source_refs=allowed_sources,
                focus=request.focus,
            ),
            context=context,
            allowed_operations=allowed_ops,
            allowed_cases=allowed_cases,
            allowed_sources=set(allowed_sources),
            case_operation_map={case.case_id: case.operation_id for _result, case in matched},
            case_sources={
                case.case_id: set(_case_source_refs([case]))
                for _result, case in matched
            },
            fallback_summary="AI 未返回可确认的断言补充建议。",
        )

    def _prepare_fixture_recipe(
        self,
        spec: ApiSpec,
        request: AutomationAIRequest,
    ) -> _PreparedReview:
        artifact = self._artifact_for_spec(request.artifact_id, spec.spec_id)
        cases = self._cases_for_spec(spec.spec_id)
        if artifact:
            selected_ids = set(artifact.case_ids)
            cases = [item for item in cases if item.case_id in selected_ids]
        cases = cases[:80]
        context = {
            "artifact_id": artifact.artifact_id if artifact else None,
            "case_count": len(cases),
            "operations": list(dict.fromkeys(item.operation_id for item in cases)),
        }
        if not cases:
            return _PreparedReview(
                prompt=PROMPT_AUTOMATION_FIXTURE_RECIPE,
                messages=[],
                context=context,
                fallback_summary="没有可用于生成数据配方的接口用例。",
            )
        digest = dump_json([_fixture_case_digest(item) for item in cases])
        return _PreparedReview(
            prompt=PROMPT_AUTOMATION_FIXTURE_RECIPE,
            messages=build_automation_fixture_recipe_messages(
                digest,
                allowed_case_ids=[item.case_id for item in cases],
                focus=request.focus,
            ),
            context=context,
            allowed_cases={item.case_id for item in cases},
            fallback_summary="AI 未返回可用的 fixture 与测试数据配方。",
        )

    def _prepare_script_review(
        self,
        spec: ApiSpec,
        request: AutomationAIRequest,
    ) -> _PreparedReview:
        if not request.artifact_id:
            raise BadRequestError("只读脚本审查必须选择一个自动化资产。")
        artifact = self._artifact_for_spec(request.artifact_id, spec.spec_id)
        if artifact is None:
            raise NotFoundError(f"自动化资产不存在：{request.artifact_id}")
        if artifact.status != "validated":
            raise BadRequestError(
                "未通过安全校验的资产不能发送给模型做源码审查。",
                detail={"artifact_id": artifact.artifact_id},
            )
        allowed_refs = [item.path for item in artifact.files]
        script_files = [
            item
            for item in artifact.files
            if item.path.endswith(".py") or item.path in {"README.md", "requirements.txt"}
        ]
        digest = "\n\n".join(
            f"### FILE: {item.path}\nSHA256: {sha256(item.content.encode('utf-8')).hexdigest()}\n{item.content}"
            for item in script_files
        )
        digest += "\n\n### CASES SUMMARY\n" + dump_json(
            {
                "case_count": len(artifact.case_ids),
                "operation_count": len(artifact.operation_ids),
                "operations": artifact.operation_ids[:80],
            }
        )
        context = {
            "artifact_id": artifact.artifact_id,
            "artifact_status": artifact.status,
            "file_count": len(artifact.files),
            "python_file_count": sum(1 for item in artifact.files if item.path.endswith(".py")),
            "template_version": artifact.template_version,
        }
        return _PreparedReview(
            prompt=PROMPT_AUTOMATION_SCRIPT_REVIEW,
            messages=build_automation_script_review_messages(
                file_digest=digest,
                allowed_source_refs=allowed_refs,
                focus=request.focus,
            ),
            context=context,
            allowed_sources=set(allowed_refs),
            fallback_summary="AI 未返回可确认的脚本审查意见。",
        )

    # ------------------------------------------------------------------
    # Response validation
    # ------------------------------------------------------------------
    def _apply_response(
        self,
        review: AutomationAIReview,
        prepared: _PreparedReview,
        parsed: Any,
    ) -> None:
        if not isinstance(parsed, dict):
            raise ValueError("模型顶层结果不是 JSON 对象。")
        review.summary = truncate(str(parsed.get("summary") or prepared.fallback_summary), 500)
        if review.kind == "fixture_recipe":
            recipe_raw = parsed.get("recipe")
            if not isinstance(recipe_raw, dict):
                raise ValueError("数据配方缺少 recipe 对象。")
            review.recipe = self._validate_recipe(recipe_raw, prepared, review.meta)
            return

        raw_findings = parsed.get("findings")
        if raw_findings is None:
            raw_findings = []
        if not isinstance(raw_findings, list):
            raise ValueError("模型结果 findings 必须是数组。")
        findings: list[AutomationAIFinding] = []
        seen: set[tuple[str, str, str]] = set()
        invalid = 0
        for raw in raw_findings:
            if len(findings) >= _MAX_REVIEW_FINDINGS:
                break
            if not isinstance(raw, dict):
                invalid += 1
                continue
            try:
                finding = self._validate_finding(raw, review.kind, prepared)
            except (ValidationError, ValueError):
                invalid += 1
                continue
            key = (finding.operation_id or "", finding.case_id or "", finding.issue)
            if key in seen:
                continue
            seen.add(key)
            findings.append(finding)
        review.findings = findings
        if invalid:
            review.meta.warnings.append(f"已丢弃 {invalid} 条悬空、越界或不合法的 AI 建议。")

    def _validate_finding(
        self,
        raw: dict[str, Any],
        kind: AutomationAIKind,
        prepared: _PreparedReview,
    ) -> AutomationAIFinding:
        operation_id = str(raw.get("operation_id") or "").strip() or None
        case_id = str(raw.get("case_id") or "").strip() or None
        source_ref = str(raw.get("source_ref") or "").strip()
        if kind == "operation_gap":
            if operation_id not in prepared.allowed_operations:
                raise ValueError("operation_id 不在未覆盖清单。")
            if source_ref not in prepared.operation_sources.get(operation_id, set()):
                raise ValueError("source_ref 不属于当前 operation。")
        elif kind == "failure_assertion":
            if case_id not in prepared.allowed_cases:
                raise ValueError("case_id 不在失败候选清单。")
            operation_id = prepared.case_operation_map.get(case_id or "")
            if operation_id not in prepared.allowed_operations:
                raise ValueError("失败 case 的 operation_id 不合法。")
            if source_ref not in prepared.case_sources.get(case_id or "", set()):
                raise ValueError("source_ref 不属于当前失败 case。")
        else:
            operation_id = None
            case_id = None
        if source_ref not in prepared.allowed_sources:
            raise ValueError("source_ref 不在允许清单。")
        issue = truncate(str(raw.get("issue") or "").strip(), 1600)
        if not issue:
            raise ValueError("issue 不能为空。")
        proposed = None
        allowed_assertion_sources = prepared.allowed_sources
        if kind == "failure_assertion" and isinstance(raw.get("proposed_assertion"), dict):
            allowed_assertion_sources = prepared.case_sources.get(case_id or "", set())
            proposed = self._parse_assertion_proposal(
                raw["proposed_assertion"],
                allowed_assertion_sources,
                source_ref,
            )
        proposed_case = None
        if kind == "operation_gap" and isinstance(raw.get("proposed_case"), dict):
            case_raw = dict(raw["proposed_case"])
            case_operation_id = str(case_raw.get("operation_id") or "").strip()
            if case_operation_id != operation_id:
                raise ValueError("proposed_case 的 operation_id 与 finding 不一致。")
            case_source_ref = str(case_raw.get("source_ref") or source_ref).strip()
            operation_sources = prepared.operation_sources.get(operation_id, set())
            if case_source_ref not in operation_sources:
                raise ValueError("proposed_case 的 source_ref 不属于当前 operation。")
            assertions = case_raw.get("assertions") or []
            if not isinstance(assertions, list):
                raise ValueError("proposed_case.assertions 必须是数组。")
            parsed_assertions = [
                self._parse_assertion_proposal(item, operation_sources, case_source_ref)
                for item in assertions[:12]
                if isinstance(item, dict)
            ]
            base_case_id = str(case_raw.get("base_case_id") or "").strip()
            proposed_case = AIApiCaseProposal(
                base_case_id=base_case_id,
                operation_id=case_operation_id,
                title=truncate(str(case_raw.get("title") or "").strip(), 300),
                category=str(case_raw.get("category") or "positive"),
                priority=str(case_raw.get("priority") or "P2"),
                request=case_raw.get("request") if isinstance(case_raw.get("request"), dict) else None,
                assertions=parsed_assertions,
                preconditions=[
                    truncate(str(item), 500)
                    for item in (case_raw.get("preconditions") or [])[:20]
                ],
                tags=[
                    truncate(str(item), 100)
                    for item in (case_raw.get("tags") or [])[:20]
                ],
                source_ref=case_source_ref,
            )
            if not proposed_case.title:
                raise ValueError("proposed_case.title 不能为空。")
        return AutomationAIFinding(
            finding_id=new_id("AIF-"),
            category={
                "operation_gap": "operation_coverage",
                "failure_assertion": "failure_assertion",
                "script_review": "script_review",
            }[kind],
            severity="warning" if raw.get("severity") == "warning" else "info",
            operation_id=operation_id,
            case_id=case_id,
            target=truncate(str(raw.get("target") or ""), 500),
            issue=issue,
            suggestion=truncate(str(raw.get("suggestion") or ""), 1800),
            rationale=truncate(str(raw.get("rationale") or ""), 1800),
            source_ref=source_ref,
            claim_status="inferred",
            proposed_assertion=proposed,
            proposed_case=proposed_case,
        )

    @staticmethod
    def _parse_assertion_proposal(
        raw: dict[str, Any],
        allowed_sources: set[str],
        default_source_ref: str,
    ) -> AIAssertionProposal:
        proposal_ref = str(raw.get("source_ref") or default_source_ref).strip()
        if proposal_ref not in allowed_sources:
            raise ValueError("断言提案的 source_ref 不合法。")
        operator = str(raw.get("operator") or "").strip()
        if operator not in {"equals", "exists", "type", "in", "gte", "lte"}:
            raise ValueError("断言提案的 operator 不合法。")
        return AIAssertionProposal(
            kind=str(raw.get("kind") or "json"),
            path=truncate(str(raw.get("path") or ""), 300),
            operator=operator,
            expected=raw.get("expected"),
            description=truncate(str(raw.get("description") or ""), 1000),
            source_ref=proposal_ref,
        )

    def _validate_recipe(
        self,
        raw: dict[str, Any],
        prepared: _PreparedReview,
        meta: AutomationAIMeta,
    ) -> AutomationFixtureRecipe:
        serialized = dump_json(raw)
        if any(pattern.search(serialized) for pattern in SECRET_PATTERNS):
            raise ValueError("配方的环境变量或测试数据包含疑似明文密钥。")
        if any(pattern.search(serialized) for pattern in _UNSAFE_RECIPE_PATTERNS):
            raise ValueError("配方包含可执行代码或危险操作，已拒绝。")
        try:
            recipe = AutomationFixtureRecipe.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"配方结构不合法：{exc}") from exc

        valid_env: list[FixtureEnvironmentVariable] = []
        seen_env: set[str] = set()
        for item in recipe.environment_variables:
            name = item.name.strip()
            if not _ENV_NAME_RE.fullmatch(name):
                meta.warnings.append(f"已忽略不合法的环境变量名：{name or '(空)'}")
                continue
            if name in seen_env:
                continue
            seen_env.add(name)
            valid_env.append(
                FixtureEnvironmentVariable(
                    name=name,
                    description=truncate(item.description, 500),
                    secret=item.secret,
                    placeholder=(name if item.secret else truncate(item.placeholder, 300)),
                )
            )
        recipe.environment_variables = valid_env
        recipe.test_data = [
            item for item in recipe.test_data
            if not item.case_id or item.case_id in prepared.allowed_cases
        ][:100]
        recipe.fixtures = recipe.fixtures[:30]
        if len(recipe.test_data) < len(raw.get("test_data") or []):
            meta.warnings.append("已移除 case_id 越界或不存在的测试数据建议。")
        recipe.warnings = [truncate(item, 500) for item in recipe.warnings[:30]]
        recipe.preconditions = [truncate(item, 500) for item in recipe.preconditions[:30]]
        recipe.execution_notes = [truncate(item, 500) for item in recipe.execution_notes[:30]]
        return recipe

    # ------------------------------------------------------------------
    def _ensure_not_running(self, request: AutomationAIRequest) -> None:
        running = self.repository.automation_ai_reviews.list_recent(
            limit=1,
            predicate=lambda item: (
                item.status == "running"
                and item.kind == request.kind
                and item.spec_id == request.spec_id
                and item.artifact_id == request.artifact_id
                and item.run_id == request.run_id
            ),
        )
        if running:
            raise ConflictError(
                "同类 AI 受控增强任务正在执行，请等待完成。",
                detail={"review_id": running[0].review_id},
            )

    def _cases_for_spec(self, spec_id: str) -> list[ApiCaseSpec]:
        return self.repository.api_cases.list_recent(
            limit=20_000,
            predicate=lambda item: item.spec_id == spec_id,
        )

    def _artifact_for_spec(
        self,
        artifact_id: str | None,
        spec_id: str,
    ) -> AutomationArtifact | None:
        if not artifact_id:
            return None
        artifact = self.repository.automation_artifacts.get(artifact_id)
        if artifact.spec_id != spec_id:
            raise BadRequestError(
                "自动化资产不属于当前接口规范。",
                detail={"artifact_id": artifact_id, "spec_id": spec_id},
            )
        return artifact

    @staticmethod
    def _resolve_base_case(
        proposal: AIApiCaseProposal,
        cases: dict[str, ApiCaseSpec],
    ) -> ApiCaseSpec:
        if proposal.base_case_id:
            base = cases.get(proposal.base_case_id)
            if base is None:
                raise BadRequestError(
                    "case 提案引用的 base_case_id 不存在。",
                    detail={"base_case_id": proposal.base_case_id},
                )
            if base.operation_id != proposal.operation_id:
                raise BadRequestError("case 提案与 base case 的 operation 不一致。")
            return base
        candidates = [
            item for item in cases.values()
            if item.operation_id == proposal.operation_id
        ]
        if not candidates:
            raise BadRequestError(
                "case 提案找不到同 operation 的确定性 base case。",
                detail={"operation_id": proposal.operation_id},
            )
        candidates.sort(key=lambda item: (item.category != "positive", item.case_id))
        return candidates[0]

    def _new_case_from_proposal(
        self,
        base: ApiCaseSpec,
        proposal: AIApiCaseProposal,
    ) -> ApiCaseSpec:
        new_case = base.model_copy(deep=True)
        new_case.case_id = new_id("API-AI-")
        new_case.title = proposal.title
        new_case.category = proposal.category
        new_case.priority = proposal.priority
        new_case.source_ref = proposal.source_ref
        new_case.created_at = now_iso()
        execution = new_case.execution.model_copy(deep=True)
        if proposal.request is not None:
            fields = proposal.request.model_fields_set
            if "query" in fields and proposal.request.query is not None:
                execution.query = _string_mapping(proposal.request.query)
            if "path_params" in fields and proposal.request.path_params is not None:
                execution.path_params = _string_mapping(proposal.request.path_params)
            if "headers" in fields and proposal.request.headers is not None:
                execution.headers = _string_mapping(proposal.request.headers)
            if "cookies" in fields and proposal.request.cookies is not None:
                execution.cookies = _string_mapping(proposal.request.cookies)
            if "body" in fields:
                execution.body = proposal.request.body
        new_case.execution = execution
        _append_unique_assertions(new_case, self._to_api_assertions(proposal.assertions))
        new_case.preconditions = list(
            dict.fromkeys([*new_case.preconditions, *proposal.preconditions, "AI 建议经人工采纳"])
        )
        new_case.tags = list(
            dict.fromkeys([*new_case.tags, *proposal.tags, "AI补充", "人工已采纳"])
        )
        new_case.warnings = list(
            dict.fromkeys([
                *new_case.warnings,
                f"由受控 AI 建议派生，来源 case={base.case_id}",
            ])
        )
        return new_case

    def _copy_case_with_assertions(
        self,
        base: ApiCaseSpec,
        assertions: list[AIAssertionProposal],
    ) -> ApiCaseSpec:
        new_case = base.model_copy(deep=True)
        new_case.case_id = new_id("API-AI-")
        new_case.created_at = now_iso()
        _append_unique_assertions(new_case, self._to_api_assertions(assertions))
        new_case.tags = list(
            dict.fromkeys([*new_case.tags, "AI断言补充", "人工已采纳"])
        )
        new_case.warnings = list(
            dict.fromkeys([
                *new_case.warnings,
                f"断言由受控 AI 建议派生，来源 case={base.case_id}",
            ])
        )
        return new_case

    @staticmethod
    def _to_api_assertions(
        proposals: list[AIAssertionProposal],
    ) -> list[ApiAssertion]:
        return [
            ApiAssertion(
                kind=item.kind,
                path=item.path,
                operator=item.operator,
                expected=item.expected,
                description=item.description,
                source_ref=item.source_ref,
                status="defined",
            )
            for item in proposals
        ]

    def _merge_recipe_into_files(
        self,
        files: list[GeneratedFile],
        review: AutomationAIReview,
    ) -> list[GeneratedFile]:
        assert review.recipe is not None
        recipe = review.recipe
        replacements = {
            "fixtures.json": dump_json(
                {
                    "fixtures": [item.model_dump(mode="json") for item in recipe.fixtures],
                    "preconditions": recipe.preconditions,
                    "warnings": recipe.warnings,
                }
            ),
            "test_data.json": dump_json(
                {
                    "test_data": [item.model_dump(mode="json") for item in recipe.test_data],
                    "execution_notes": recipe.execution_notes,
                }
            ),
        }
        merged: list[GeneratedFile] = []
        seen = set()
        for item in files:
            if item.path == ".env.example":
                merged.append(
                    item.model_copy(
                        update={
                            "content": _merge_env_example(item.content, recipe),
                        }
                    )
                )
                seen.add(item.path)
            elif item.path in replacements:
                merged.append(
                    item.model_copy(
                        update={
                            "content": replacements[item.path],
                            "media_type": "application/json",
                        }
                    )
                )
                seen.add(item.path)
            else:
                merged.append(item)
        if ".env.example" not in seen:
            merged.append(
                GeneratedFile(
                    path=".env.example",
                    content=_merge_env_example("", recipe),
                )
            )
        for path, content in replacements.items():
            if path not in seen:
                merged.append(
                    GeneratedFile(path=path, content=content, media_type="application/json")
                )
        return merged

    def _event(self, action: str, status: str, review: AutomationAIReview) -> None:
        ExecutionService(self.settings, self.repository).add_event(
            trace_id=new_id("TRACE-"),
            action=action,
            status=status,
            artifact_id=review.artifact_id,
            run_id=review.run_id,
            message=f"kind={review.kind}; review={review.review_id}; decision={review.decision}",
        )


def _allowed_source_refs(operations: Iterable[ApiOperation]) -> list[str]:
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
    return list(dict.fromkeys(item for item in refs if item))


def _case_source_refs(cases: Iterable[ApiCaseSpec]) -> list[str]:
    refs: list[str] = []
    for case in cases:
        refs.append(case.source_ref)
        refs.extend(item.source_ref for item in case.assertions if item.source_ref)
    return list(dict.fromkeys(item for item in refs if item))


def _schema_digest(schema: Any, depth: int = 0) -> Any:
    if depth > 5:
        return {"$truncated": True}
    if isinstance(schema, list):
        return [_schema_digest(item, depth + 1) for item in schema]
    if not isinstance(schema, dict):
        return schema
    allowed = {
        "type",
        "format",
        "required",
        "enum",
        "const",
        "pattern",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "nullable",
        "items",
        "properties",
        "allOf",
        "oneOf",
        "anyOf",
    }
    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in allowed:
            continue
        if key == "properties" and isinstance(value, dict):
            result[key] = {name: _schema_digest(item, depth + 1) for name, item in value.items()}
        elif key in {"items", "allOf", "oneOf", "anyOf"}:
            result[key] = _schema_digest(value, depth + 1)
        else:
            result[key] = value
    return result


def _fixture_case_digest(case: ApiCaseSpec) -> dict[str, Any]:
    execution = case.execution
    return {
        "case_id": case.case_id,
        "operation_id": case.operation_id,
        "title": truncate(case.title, 300),
        "method": case.method,
        "path": case.path,
        "category": case.category,
        "headers": sorted(execution.headers.keys()),
        "query_keys": sorted(execution.query.keys()),
        "path_parameter_keys": sorted(execution.path_params.keys()),
        "cookie_keys": sorted(execution.cookies.keys()),
        "body_shape": _value_shape(execution.body),
        "environment_variables": [
            {
                "name": str(item.get("name") or ""),
                "description": truncate(str(item.get("description") or ""), 300),
                "secret": bool(item.get("secret")),
            }
            for item in execution.environment_variables
        ],
        "assertion_summary": [
            {
                "kind": item.kind,
                "path": item.path,
                "operator": item.operator,
                "status": item.status,
            }
            for item in case.assertions
        ],
    }


def _value_shape(value: Any, depth: int = 0) -> Any:
    """只发送数据结构，不把真实请求值送入模型。"""
    if depth > 5:
        return "truncated"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return [_value_shape(item, depth + 1) for item in value[:5]]
    if isinstance(value, dict):
        return {str(key): _value_shape(item, depth + 1) for key, item in list(value.items())[:50]}
    return type(value).__name__


def _string_mapping(raw: dict[str, Any]) -> dict[str, str]:
    return {str(key): str(value) for key, value in raw.items()}


def _append_unique_assertions(case: ApiCaseSpec, additions: list[ApiAssertion]) -> None:
    existing = {
        (
            item.kind,
            item.path,
            item.operator,
            dump_json(item.expected, indent=None),
            item.status,
        )
        for item in case.assertions
    }
    for item in additions:
        key = (
            item.kind,
            item.path,
            item.operator,
            dump_json(item.expected, indent=None),
            item.status,
        )
        if key in existing:
            continue
        existing.add(key)
        case.assertions.append(item)


def _merge_env_example(content: str, recipe: AutomationFixtureRecipe) -> str:
    lines = [line.rstrip() for line in content.splitlines()]
    existing_names = {
        line.split("=", 1)[0].strip()
        for line in lines
        if "=" in line and not line.lstrip().startswith("#")
    }
    additions = ["", "# Applied from an accepted AI fixture recipe. Never commit real credentials."]
    for item in recipe.environment_variables:
        if item.name in existing_names:
            continue
        additions.append(f"# {item.name}: {item.description}{' (secret)' if item.secret else ''}")
        value = "" if item.secret else item.placeholder
        additions.append(f"{item.name}={value}")
        existing_names.add(item.name)
    return "\n".join([*lines, *additions]).strip() + "\n"


__all__ = ["AutomationAIService"]
