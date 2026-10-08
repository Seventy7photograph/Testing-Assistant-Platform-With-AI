"""导出器注册表。"""
from __future__ import annotations

from app.core.registry import Registry
from app.exporters.base import Exporter
from app.exporters.excel_exporter import ExcelExporter
from app.exporters.json_exporter import JsonExporter

EXPORTER_REGISTRY: Registry[Exporter] = Registry("导出器")

# 预留：XMindExporter / CsvExporter / TestLinkXmlExporter
# 实现 Exporter 子类后调用 register_exporter()，API 与前端会自动感知新格式。


def register_exporter(exporter: Exporter, *, override: bool = False) -> Exporter:
    return EXPORTER_REGISTRY.register(
        exporter.name,
        exporter,
        meta={"label": exporter.label, "media_type": exporter.media_type, "extension": exporter.extension},
        override=override,
    )


register_exporter(ExcelExporter())
register_exporter(JsonExporter())


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