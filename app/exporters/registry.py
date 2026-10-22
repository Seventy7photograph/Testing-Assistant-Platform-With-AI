"""导出器注册表。"""
from __future__ import annotations

from app.core.registry import Registry
from app.exporters.base import Exporter
from app.exporters.csv_exporter import CsvExporter
from app.exporters.excel_exporter import ExcelExporter
from app.exporters.json_exporter import JsonExporter
from app.exporters.postman_exporter import PostmanExporter
from app.exporters.testlink_exporter import TestLinkXmlExporter
from app.exporters.xmind_exporter import XMindExporter

EXPORTER_REGISTRY: Registry[Exporter] = Registry("导出器")


def register_exporter(exporter: Exporter, *, override: bool = False) -> Exporter:
    return EXPORTER_REGISTRY.register(
        exporter.name,
        exporter,
        meta={"label": exporter.label, "media_type": exporter.media_type, "extension": exporter.extension},
        override=override,
    )


register_exporter(ExcelExporter())
register_exporter(JsonExporter())
# V2.0 S3：新增三种可被目标工具直接导入的格式。
# register_exporter() 之后 /export/formats 与前端下拉框会自动出现，无需改接口。
register_exporter(XMindExporter())
register_exporter(CsvExporter())
register_exporter(TestLinkXmlExporter())
# V2.2：接口用例导出。格式在能力清单中可见，但调用方必须提供接口资产。
register_exporter(PostmanExporter())


def available_formats() -> list[dict]:
    return [
        {
            "name": name,
            "label": exporter.label,
            "media_type": exporter.media_type,
            "extension": exporter.extension,
        }
        for name, exporter in EXPORTER_REGISTRY.items()
        if exporter.implemented
    ]


def get_exporter(name: str) -> Exporter:
    return EXPORTER_REGISTRY.get((name or "").strip().lower())
