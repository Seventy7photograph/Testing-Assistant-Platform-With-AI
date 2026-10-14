"""导出层：把 TestCaseSuite 渲染为目标格式。

已落地：Excel（人看）、JSON（二次加工）、CSV（机器吃）、XMind（评审视图）、
TestLink XML（导入测试管理工具）。

扩展点：继续增加格式时实现 Exporter 子类并 register_exporter() 即可，
API 层与前端下拉框无需改动。
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
