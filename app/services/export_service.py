"""导出服务：选用导出器 + 落盘留档。"""
from __future__ import annotations

from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.exceptions import BadRequestError
from app.core.logging import get_logger
from app.exporters.base import ExportResult
from app.exporters.registry import get_exporter
from app.repository import Repository, get_repository
from app.schemas.api_testing import ApiCaseSpec, ApiSpec
from app.schemas.testcase import TestCaseSuite

logger = get_logger(__name__)


class ExportService:
    def __init__(self, settings: Settings | None = None, repository: Repository | None = None) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or get_repository()

    def export_suite(self, suite_id: str, fmt: str = "excel", *, options: dict | None = None) -> ExportResult:
        suite = self.repository.suites.get(suite_id)
        return self.export(suite, fmt, options=options)

    def export(self, suite: TestCaseSuite, fmt: str = "excel", *, options: dict | None = None) -> ExportResult:
        exporter = get_exporter(fmt)
        if exporter.name == "postman":
            raise BadRequestError(
                "Postman 是接口资产导出格式，请从接口规范详情页导出。",
                detail={"suite_id": suite.suite_id, "format": fmt},
            )
        result = exporter.export(suite, options=options)
        self._archive(suite, result)
        return result

    def export_api(self, spec: ApiSpec, cases: list[ApiCaseSpec]) -> ExportResult:
        """导出接口资产为 Postman Collection 2.1。"""
        exporter = get_exporter("postman")
        result = exporter.export(
            TestCaseSuite(suite_id=spec.spec_id, doc_id=spec.spec_id),
            options={"api_spec": spec, "api_cases": cases},
        )
        self._archive_result(result)
        return result

    def _archive(self, suite: TestCaseSuite, result: ExportResult) -> None:
        """把导出结果另存一份到 storage/exports，失败不影响下载（尽力而为）。"""
        self._archive_result(result)

    def _archive_result(self, result: ExportResult) -> None:
        path: Path = self.settings.export_dir / result.filename
        try:
            path.write_bytes(result.content)
            logger.info("导出文件已归档：%s（%d 字节）", path.name, result.size_bytes)
        except OSError as exc:  # pragma: no cover - 磁盘异常场景
            logger.warning("导出文件归档失败（不影响接口返回）：%s", exc)
