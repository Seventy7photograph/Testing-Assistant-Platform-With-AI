"""JSON 导出器：便于与外部系统对接 / 二次加工。"""
from __future__ import annotations

import json

from app.core.exceptions import ExportError
from app.exporters.base import Exporter, ExportResult
from app.schemas.testcase import TestCaseSuite


class JsonExporter(Exporter):
    name = "json"
    label = "JSON"
    extension = "json"
    media_type = "application/json; charset=utf-8"

    def export(self, suite: TestCaseSuite, *, options: dict | None = None) -> ExportResult:
        try:
            payload = suite.model_dump(mode="json")
            content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ExportError(f"JSON 序列化失败：{exc}") from exc
        return ExportResult(content=content, filename=self.build_filename(suite), media_type=self.media_type)