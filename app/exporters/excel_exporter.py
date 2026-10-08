"""Excel 导出器（openpyxl）。

输出 4 个工作表：
    测试用例  —— 标准用例明细，可直接导入禅道/Jira/TestLink
    用例统计  —— 按设计方法/类型/优先级分布
    需求追溯  —— 需求条目 -> 用例数，便于覆盖率人工核对
    生成信息  —— Provider / 模型 / 告警，保证可追溯

异常策略：所有底层异常统一包装为 ExportError，并给出可操作提示
（如「文件被占用，请先关闭已打开的 Excel」）。
"""
from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.core.exceptions import ExportError
from app.core.utils import truncate
from app.exporters.base import Exporter, ExportResult
from app.schemas.testcase import TestCase, TestCaseSuite

CASE_HEADERS: tuple[tuple[str, str, int], ...] = (
    ("case_id", "用例编号", 14),
    ("module", "所属模块", 16),
    ("title", "用例标题", 46),
    ("design_method", "设计方法", 12),
    ("case_type", "用例类型", 10),
    ("priority", "优先级", 8),
    ("requirement_ids", "关联需求", 14),
    ("preconditions", "前置条件", 26),
    ("steps", "测试步骤", 52),
    ("expected_result", "预期结果", 40),
    ("test_data", "测试数据", 24),
    ("tags", "标签", 18),
    ("remarks", "备注", 26),
    ("source", "来源", 10),
    ("covered_methods", "覆盖方法", 22),
)

HEADER_FILL = PatternFill("solid", fgColor="305496")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
TITLE_FONT = Font(bold=True, size=12)
THIN_BORDER = Border(
    left=Side(style="thin", color="BFBFBF"),
    right=Side(style="thin", color="BFBFBF"),
    top=Side(style="thin", color="BFBFBF"),
    bottom=Side(style="thin", color="BFBFBF"),
)
TOP_WRAP = Alignment(vertical="top", wrap_text=True)

PRIORITY_FILLS = {
    "P0": PatternFill("solid", fgColor="FFC7CE"),
    "P1": PatternFill("solid", fgColor="FFEB9C"),
    "P2": PatternFill("solid", fgColor="E2EFDA"),
    "P3": PatternFill("solid", fgColor="F2F2F2"),
}
TYPE_FILLS = {
    "异常": PatternFill("solid", fgColor="FCE4D6"),
    "边界": PatternFill("solid", fgColor="DDEBF7"),
    "场景": PatternFill("solid", fgColor="E4DFEC"),
}


def _stage_label(llm_used: bool, provider: str) -> str:
    """把「是否使用 LLM + Provider」渲染为一致的展示文案，避免出现
    「Provider=deepseek 但生成方式=规则引擎」这类自相矛盾的展示。"""
    if not llm_used:
        return "规则引擎"
    return f"LLM（{provider or 'llm'}）"


def _provider_label(provider: str, used: bool) -> str:
    """未启用的 Provider 不显示名称，避免被误读为"本次用了 deepseek"。"""
    return (provider or "rule") if used else "未启用（本次仅使用规则引擎）"


class ExcelExporter(Exporter):
    name = "excel"
    label = "Excel"
    extension = "xlsx"
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def export(self, suite: TestCaseSuite, *, options: dict | None = None) -> ExportResult:
        options = options or {}
        include_stats = bool(options.get("include_stats", True))
        try:
            workbook = Workbook()
            self._write_cases(workbook.active, suite)
            if include_stats:
                self._write_stats(workbook.create_sheet("用例统计"), suite)
                self._write_traceability(workbook.create_sheet("需求追溯"), suite)
                self._write_meta(workbook.create_sheet("生成信息"), suite)

            buffer = io.BytesIO()
            workbook.save(buffer)
            content = buffer.getvalue()
        except PermissionError as exc:
            raise ExportError(
                "Excel 文件写入被拒绝，请关闭已打开的同名文件后重试。", detail={"error": str(exc)}
            ) from exc
        except Exception as exc:  # noqa: BLE001 - openpyxl 异常类型较多，统一兜底
            raise ExportError(f"Excel 导出失败：{exc}", detail={"error": str(exc)}) from exc

        return ExportResult(content=content, filename=self.build_filename(suite), media_type=self.media_type)

    # ------------------------------------------------------------------ #
    def _write_cases(self, sheet: Worksheet, suite: TestCaseSuite) -> None:
        sheet.title = "测试用例"
        for column, (_, header, width) in enumerate(CASE_HEADERS, start=1):
            cell = sheet.cell(row=1, column=column, value=header)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(vertical="center", horizontal="center")
            cell.border = THIN_BORDER
            sheet.column_dimensions[get_column_letter(column)].width = width
        sheet.row_dimensions[1].height = 22
        sheet.freeze_panes = "C2"

        if not suite.cases:
            sheet.cell(row=2, column=1, value="（本次未生成任何用例，请检查需求解析结果或所选设计方法）")

        for index, case in enumerate(suite.cases, start=2):
            for column, (key, _, _) in enumerate(CASE_HEADERS, start=1):
                cell = sheet.cell(row=index, column=column, value=self._cell_value(key, case))
                cell.alignment = TOP_WRAP
                cell.border = THIN_BORDER
            priority_cell = sheet.cell(row=index, column=6)
            if case.priority.value in PRIORITY_FILLS:
                priority_cell.fill = PRIORITY_FILLS[case.priority.value]
            type_cell = sheet.cell(row=index, column=5)
            if case.case_type.value in TYPE_FILLS:
                type_cell.fill = TYPE_FILLS[case.case_type.value]

        if suite.cases:
            sheet.auto_filter.ref = f"A1:{get_column_letter(len(CASE_HEADERS))}{len(suite.cases) + 1}"

    @staticmethod
    def _cell_value(key: str, case: TestCase) -> str:
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
            return {"rule": "规则引擎", "llm": "LLM", "hybrid": "混合"}.get(case.source.value, case.source.value)
        if key == "covered_methods":
            methods = case.covered_methods or [case.design_method]
            return "、".join(method.label for method in methods)
        return str(getattr(case, key, "") or "")

    def _write_stats(self, sheet: Worksheet, suite: TestCaseSuite) -> None:
        rows: list[tuple[str, str | int]] = [
            ("用例总数", suite.stats.total),
            ("去重剔除数", suite.stats.duplicate_removed),
            ("覆盖需求条目数", len(suite.stats.requirement_coverage)),
            ("需求解析方式", _stage_label(suite.parse_meta.llm_used, suite.parse_meta.provider)),
            ("用例生成方式", "LLM 增强" if suite.generation_meta.llm_used else "规则引擎"),
        ]
        self._write_kv_table(sheet, "总体统计", rows, start_row=1)

        row = len(rows) + 4
        row = self._write_mapping(sheet, "按设计方法（主）", suite.stats.by_method, row)
        if suite.stats.by_covered_method:
            row = self._write_mapping(
                sheet, "按设计方法（含合并覆盖）", suite.stats.by_covered_method, row + 1
            )
        row = self._write_mapping(sheet, "按用例类型", suite.stats.by_type, row + 1)
        self._write_mapping(sheet, "按优先级", suite.stats.by_priority, row + 1)

    def _write_traceability(self, sheet: Worksheet, suite: TestCaseSuite) -> None:
        sheet.append(["需求条目", "用例数"])
        for cell in sheet[1]:
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
        sheet.column_dimensions["A"].width = 24
        sheet.column_dimensions["B"].width = 12
        if not suite.stats.requirement_coverage:
            sheet.append(["（无）", 0])
            return
        for req_id, count in suite.stats.requirement_coverage.items():
            sheet.append([req_id, count])
        sheet.freeze_panes = "A2"

    def _write_meta(self, sheet: Worksheet, suite: TestCaseSuite) -> None:
        meta = suite.generation_meta
        rows: list[tuple[str, str | int]] = [
            ("用例集 ID", suite.suite_id),
            ("需求文档 ID", suite.doc_id),
            ("需求文档标题", suite.doc_title),
            ("生成时间", suite.created_at),
            ("设计方法", "、".join(method.label for method in suite.methods)),
            ("需求解析 Provider", _provider_label(suite.parse_meta.provider, suite.parse_meta.llm_used)),
            ("需求解析是否使用 LLM", "是" if suite.parse_meta.llm_used else "否"),
            ("用例生成 Provider", _provider_label(meta.llm_provider, meta.llm_used)),
            ("用例生成是否使用 LLM", "是" if meta.llm_used else "否"),
            ("LLM 模型", meta.llm_model or "-"),
            ("是否降级", "是" if meta.fallback_used else "否"),
            ("生成耗时(ms)", meta.elapsed_ms),
            ("告警数量", len(meta.warnings)),
        ]
        self._write_kv_table(sheet, "生成信息", rows, start_row=1)
        if meta.warnings:
            row = len(rows) + 4
            sheet.cell(row=row, column=1, value=f"告警明细（{len(meta.warnings)} 条）").font = TITLE_FONT
            for index, warning in enumerate(meta.warnings, start=row + 1):
                sheet.cell(row=index, column=1, value=truncate(warning, 200))

    @staticmethod
    def _write_kv_table(
        sheet: Worksheet, title: str, rows: list[tuple[str, str | int]], *, start_row: int
    ) -> None:
        sheet.cell(row=start_row, column=1, value=title).font = TITLE_FONT
        sheet.column_dimensions["A"].width = 22
        sheet.column_dimensions["B"].width = 60
        for offset, (key, value) in enumerate(rows, start=start_row + 1):
            key_cell = sheet.cell(row=offset, column=1, value=key)
            key_cell.font = Font(bold=True)
            key_cell.border = THIN_BORDER
            value_cell = sheet.cell(row=offset, column=2, value=value)
            value_cell.alignment = TOP_WRAP
            value_cell.border = THIN_BORDER

    @staticmethod
    def _write_mapping(sheet: Worksheet, title: str, mapping: dict[str, int], row: int) -> int:
        sheet.cell(row=row, column=1, value=title).font = TITLE_FONT
        if not mapping:
            sheet.cell(row=row + 1, column=1, value="（无）")
            return row + 1
        for offset, (key, value) in enumerate(mapping.items(), start=row + 1):
            sheet.cell(row=offset, column=1, value=key).border = THIN_BORDER
            sheet.cell(row=offset, column=2, value=value).border = THIN_BORDER
        return row + len(mapping)


__all__ = ["ExcelExporter"]
