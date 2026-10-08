"""导出层：把 TestCaseSuite 渲染为目标格式。

扩展点：后续增加 XMind / CSV / TestLink XML 导出时，
实现 Exporter 子类并 register_exporter() 即可，API 层无需改动。
"""
from app.exporters.base import Exporter, ExportResult
from app.exporters.registry import (
    EXPORTER_REGISTRY,
    available_formats,
    get_exporter,
    register_exporter,
)

__all__ = [
    "Exporter",
    "ExportResult",
    "EXPORTER_REGISTRY",
    "available_formats",
    "get_exporter",
    "register_exporter",
]