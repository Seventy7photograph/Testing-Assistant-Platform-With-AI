"""导出器抽象。"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime

from app.core.utils import slugify_filename
from app.schemas.testcase import TestCaseSuite


@dataclass(slots=True)
class ExportResult:
    """导出结果：内容 + 建议文件名 + MIME 类型。"""

    content: bytes
    filename: str
    media_type: str

    @property
    def size_bytes(self) -> int:
        return len(self.content)


class Exporter(abc.ABC):
    """导出器基类。"""

    name: str = "base"
    label: str = "基础导出器"
    extension: str = "dat"
    media_type: str = "application/octet-stream"
    implemented: bool = True

    @abc.abstractmethod
    def export(self, suite: TestCaseSuite, *, options: dict | None = None) -> ExportResult:
        """把用例集渲染为字节流。实现方需自行捕获底层异常并抛出 ExportError。"""

    def build_filename(self, suite: TestCaseSuite, *, suffix: str = "测试用例") -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = slugify_filename(suite.doc_title or "用例集", fallback="testcases")
        return f"{stem}_{suffix}_{stamp}.{self.extension}"