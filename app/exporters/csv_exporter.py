"""CSV 导出器。

为什么 V2.0 要补一个纯 CSV：Excel 适合人看，CSV 适合**机器吃** ——
CI 里做用例数量比对、diff 两轮用例、把用例喂给自研平台，都只需要一个扁平表，
没必要为此解析 xlsx。

两个关键工程细节：

  1. **编码用 ``utf-8-sig``**：不带 BOM 的 UTF-8 CSV 在中文 Windows 的 Excel 里
     会整片乱码，这是使用者最容易踩、又最难自查的坑；BOM 对标准 CSV 解析器无害。
  2. **公式注入防护**：以 ``= + @`` 或 ``-`` 开头的单元格会被 Excel 当公式执行。
     用例数据来自需求文档与模型输出，属于不完全可信输入，因此统一加前导单引号
     转义（``-1`` 这类合法数字不加，避免破坏边界数据）。
"""
from __future__ import annotations

import csv
import io
import re

from app.core.exceptions import ExportError
from app.exporters.base import Exporter, ExportResult
from app.schemas.testcase import TestCase, TestCaseSuite

CSV_HEADERS: tuple[tuple[str, str], ...] = (
    ("case_id", "用例编号"),
    ("module", "所属模块"),
    ("title", "用例标题"),
    ("design_method", "设计方法"),
    ("case_type", "用例类型"),
    ("priority", "优先级"),
    ("requirement_ids", "关联需求"),
    ("preconditions", "前置条件"),
    ("steps", "测试步骤"),
    ("expected_result", "预期结果"),
    ("test_data", "测试数据"),
    ("tags", "标签"),
    ("remarks", "备注"),
    ("source", "来源"),
    ("covered_methods", "覆盖方法"),
)

SOURCE_LABELS = {"rule": "规则引擎", "llm": "LLM", "hybrid": "混合"}

#: Excel / WPS 会把这些前导字符当公式解析。
_FORMULA_PREFIX_RE = re.compile(r"^[=+@]|^-\D")
_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")


class CsvExporter(Exporter):
    name = "csv"
    label = "CSV"
    extension = "csv"
    media_type = "text/csv; charset=utf-8"

    def export(self, suite: TestCaseSuite, *, options: dict | None = None) -> ExportResult:
        try:
            buffer = io.StringIO(newline="")
            writer = csv.writer(buffer)
            writer.writerow([header for _, header in CSV_HEADERS])
            for case in suite.cases:
                writer.writerow([sanitize_cell(cell_value(key, case)) for key, _ in CSV_HEADERS])
            content = buffer.getvalue().encode("utf-8-sig")
        except (csv.Error, ValueError) as exc:
            raise ExportError(f"CSV 导出失败：{exc}", detail={"error": str(exc)}) from exc
        return ExportResult(content=content, filename=self.build_filename(suite), media_type=self.media_type)


def cell_value(key: str, case: TestCase) -> str:
    if key == "design_method":
        return case.design_method.label
    if key == "case_type":
        return case.case_type.value
    if key == "priority":
        return case.priority.value
    if key == "requirement_ids":
        return "、".join(case.requirement_ids)
    if key == "preconditions":
        return "\n".join(case.preconditions)
    if key == "steps":
        return case.step_text()
    if key == "test_data":
        return case.data_text()
    if key == "tags":
        return "、".join(case.tags)
    if key == "source":
        return SOURCE_LABELS.get(case.source.value, case.source.value)
    if key == "covered_methods":
        methods = case.covered_methods or [case.design_method]
        return "、".join(method.label for method in methods)
    return str(getattr(case, key, "") or "")


def sanitize_cell(value: str) -> str:
    """中和 Excel 公式注入，同时保留 ``-1`` 这类合法负数。"""
    text = value or ""
    if not text:
        return text
    if _NUMBER_RE.match(text):
        return text
    return "'" + text if _FORMULA_PREFIX_RE.match(text) else text


__all__ = ["CSV_HEADERS", "CsvExporter", "cell_value", "sanitize_cell"]
