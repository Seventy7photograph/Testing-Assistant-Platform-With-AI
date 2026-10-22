"""接口资产导入、查询与生命周期管理。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    ConflictError,
    LLMNotConfiguredError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedFormatError,
)
from app.core.utils import new_id, now_iso
from app.design.api_cases import generate_api_cases
from app.design.api_review import review_api_cases
from app.llm.base import LLMProvider
from app.parsers.openapi_parser import parse_openapi
from app.repository import Repository, get_repository
from app.schemas.api_testing import (
    ApiCaseCollection,
    ApiCaseSpec,
    ApiImportResult,
    ApiOperation,
    ApiReviewMeta,
    ApiReviewResult,
    ApiSpec,
    ApiSpecDeleteResult,
    ApiSpecSummary,
)

SUPPORTED_OPENAPI_EXTENSIONS = {".json", ".yaml", ".yml"}
REVIEW_STALE_SECONDS = 15 * 60


def _review_is_running(result: ApiReviewResult | None) -> bool:
    if result is None or result.meta.status != "running":
        return False
    try:
        started = datetime.fromisoformat(result.created_at)
        return (datetime.now().astimezone() - started).total_seconds() < REVIEW_STALE_SECONDS
    except (TypeError, ValueError):
        return False


class ApiService:
    def __init__(
        self,
        settings: Settings | None = None,
        repository: Repository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or get_repository()

    def import_spec(
        self,
        *,
        filename: str,
        data: bytes,
        title: str | None = None,
    ) -> ApiImportResult:
        extension = Path(filename or "").suffix.lower()
        if extension not in SUPPORTED_OPENAPI_EXTENSIONS:
            raise UnsupportedFormatError(
                "接口规范只支持 OpenAPI 3 JSON / YAML（.json / .yaml / .yml）。",
                detail={
                    "filename": filename,
                    "supported": sorted(SUPPORTED_OPENAPI_EXTENSIONS),
                },
            )
        if len(data) > self.settings.max_upload_size_bytes:
            raise PayloadTooLargeError(
                f"OpenAPI 文件超过 {self.settings.max_upload_size_mb} MB 上限。",
                detail={"size_bytes": len(data), "max_mb": self.settings.max_upload_size_mb},
            )

        spec_id = new_id("API-")
        spec = parse_openapi(
            data,
            filename=filename or f"openapi{extension}",
            spec_id=spec_id,
        )
        if title and title.strip():
            spec.title = title.strip()
        generated = generate_api_cases(spec)
        spec.stats.operations = len(spec.operations)
        spec.stats.cases = len(generated.cases)

        # 先落规格再落用例：用例里带 spec_id，若中途失败，规格详情仍能显示
        # “0 条用例”而不是留下无法追溯的孤儿用例。
        self.repository.api_specs.save(spec)
        for case in generated.cases:
            self.repository.api_cases.save(case)
        archive_warning = self._archive_source(spec, data, extension)
        if archive_warning:
            spec.warnings.append(archive_warning)
            self.repository.api_specs.save(spec)
        return ApiImportResult(
            spec=spec,
            cases=generated.cases,
            warnings=list(spec.warnings),
        )

    def _archive_source(self, spec: ApiSpec, data: bytes, extension: str) -> str:
        directory = self.settings.upload_dir / "api_specs"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{spec.spec_id}{extension}").write_bytes(data)
        except OSError as exc:
            return f"源规范留档失败（不影响解析结果）：{exc}"
        return ""

    def list_specs(self, limit: int = 30) -> list[ApiSpecSummary]:
        return [
            spec.summary()
            for spec in self.repository.api_specs.list_recent(max(1, min(limit, 100)))
        ]

    def get_spec(self, spec_id: str) -> ApiSpec:
        return self.repository.api_specs.get(spec_id)

    def list_operations(self, spec_id: str) -> list[ApiOperation]:
        return self.get_spec(spec_id).operations

    def get_operation(self, spec_id: str, operation_id: str) -> ApiOperation:
        spec = self.get_spec(spec_id)
        operation = next(
            (item for item in spec.operations if item.operation_id == operation_id),
            None,
        )
        if operation is None:
            raise NotFoundError(
                f"接口 operation 不存在：{operation_id}",
                detail={"spec_id": spec_id, "operation_id": operation_id},
            )
        return operation

    def list_cases(
        self,
        spec_id: str,
        *,
        operation_id: str | None = None,
    ) -> ApiCaseCollection:
        self.get_spec(spec_id)
        cases = [
            case
            for case in self.repository.api_cases.list_recent(limit=10_000)
            if case.spec_id == spec_id
            and (operation_id is None or case.operation_id == operation_id)
        ]
        cases.sort(key=lambda item: (item.operation_id, item.category != "positive", item.case_id))
        return ApiCaseCollection(
            spec_id=spec_id,
            operation_id=operation_id,
            cases=cases,
        )

    def get_case(self, spec_id: str, case_id: str) -> ApiCaseSpec:
        case = self.repository.api_cases.get(case_id)
        if case.spec_id != spec_id:
            raise NotFoundError(
                f"接口用例 {case_id} 不属于规范 {spec_id}。",
                detail={"spec_id": spec_id, "case_id": case_id},
            )
        return case

    async def review_spec(self, spec_id: str, llm: LLMProvider) -> ApiReviewResult:
        """显式执行大模型只读复核，并持久化最近一次结果。"""
        spec = self.get_spec(spec_id)
        if _review_is_running(spec.ai_review):
            raise ConflictError(
                "该接口规范正在执行 AI 复核，请等待当前任务完成。",
                detail={"spec_id": spec_id},
            )
        if (
            spec.ai_review is not None
            and spec.ai_review.meta.status == "completed"
            and spec.ai_review.meta.used
        ):
            raise ConflictError(
                "该接口规范已完成 AI 复核，无需重复执行。",
                detail={"spec_id": spec_id, "review_id": spec.ai_review.created_at},
            )
        if not llm.available:
            raise LLMNotConfiguredError(
                "当前没有可用的大模型，无法执行接口用例复核。"
                "可先配置模型，或继续使用确定性契约用例。"
            )
        cases = self.list_cases(spec_id).cases
        running = ApiReviewResult(
            spec_id=spec_id,
            findings=[],
            meta=ApiReviewMeta(
                requested=True,
                used=False,
                status="running",
                provider=llm.name,
                model=llm.model,
                prompt_id="api.case_review",
                prompt_version="2.2.0",
                temperature=0.1,
            ),
            created_at=now_iso(),
        )
        spec.ai_review = running
        self.repository.api_specs.save(spec)
        try:
            result = await review_api_cases(spec, cases, llm)
        except Exception as exc:  # noqa: BLE001 - 失败状态必须落盘，不能留下永久 running
            result = ApiReviewResult(
                spec_id=spec_id,
                findings=[],
                meta=ApiReviewMeta(
                    requested=True,
                    used=False,
                    status="failed",
                    provider=llm.name,
                    model=llm.model,
                    prompt_id="api.case_review",
                    prompt_version="2.2.0",
                    temperature=0.1,
                    warnings=[f"AI 复核失败：{exc}"],
                ),
                created_at=now_iso(),
            )
        spec.ai_review = result
        self.repository.api_specs.save(spec)
        return result

    def delete_spec(self, spec_id: str) -> ApiSpecDeleteResult:
        if not self.repository.api_specs.delete(spec_id):
            raise NotFoundError(f"接口规范不存在：{spec_id}")
        case_ids = [
            case_id
            for case_id in self.repository.api_cases.list_ids()
            if self._case_belongs_to(case_id, spec_id)
        ]
        deleted_cases = sum(
            1 for case_id in case_ids if self.repository.api_cases.delete(case_id)
        )
        for extension in SUPPORTED_OPENAPI_EXTENSIONS:
            path = self.settings.upload_dir / "api_specs" / f"{spec_id}{extension}"
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        return ApiSpecDeleteResult(
            deleted=True,
            spec_id=spec_id,
            deleted_cases=deleted_cases,
        )

    def _case_belongs_to(self, case_id: str, spec_id: str) -> bool:
        case = self.repository.api_cases.try_get(case_id)
        return case is not None and case.spec_id == spec_id


__all__ = ["ApiService", "SUPPORTED_OPENAPI_EXTENSIONS"]
