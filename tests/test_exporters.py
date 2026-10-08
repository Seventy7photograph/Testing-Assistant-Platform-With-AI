"""导出器单测：Excel 结构、JSON 往返、异常兜底与注册表。"""
from __future__ import annotations

import io
import json

import pytest
from openpyxl import load_workbook

from app.core.exceptions import ExportError, NotFoundError
from app.exporters.excel_exporter import ExcelExporter
from app.exporters.json_exporter import JsonExporter
from app.exporters.registry import available_formats, get_exporter
from app.schemas.common import CaseSource, CaseType, DesignMethod, Priority
from app.schemas.testcase import GenerationMeta, TestCase, TestCaseSuite, TestStep


@pytest.fixture
def suite() -> TestCaseSuite:
    cases = [
        TestCase(
            case_id="TC-EQ-001",
            title="[等价类] 用户注册｜手机号 有效等价类",
            module="用户中心",
            requirement_ids=["REQ-001"],
            design_method=DesignMethod.EQUIVALENCE,
            case_type=CaseType.FUNCTIONAL,
            priority=Priority.P0,
            preconditions=["系统正常运行"],
            steps=[TestStep(no=1, action="输入手机号", expected="校验通过")],
            expected_result="注册成功",
            test_data={"手机号": "13800000000"},
            tags=["等价类划分", "有效等价类"],
            source=CaseSource.RULE,
        ),
        TestCase(
            case_id="TC-BV-001",
            title="[边界值] 用户注册｜年龄 最小值-1",
            module="用户中心",
            requirement_ids=["REQ-001", "REQ-002"],
            design_method=DesignMethod.BOUNDARY,
            case_type=CaseType.EXCEPTION,
            priority=Priority.P1,
            steps=[TestStep(no=1, action="输入 17", expected="拒绝")],
            expected_result="系统拦截",
            test_data={"年龄": "17"},
        ),
    ]
    suite = TestCaseSuite(
        suite_id="SUITE-test",
        doc_id="DOC-test",
        doc_title="订单系统需求说明",
        methods=[DesignMethod.EQUIVALENCE, DesignMethod.BOUNDARY],
        cases=cases,
        generation_meta=GenerationMeta(
            methods=["equivalence", "boundary"], llm_provider="rule", warnings=["示例告警"]
        ),
    )
    suite.stats.duplicate_removed = 3
    suite.recount()
    return suite


class TestExcelExporter:
    def test_produces_valid_workbook(self, suite: TestCaseSuite) -> None:
        result = ExcelExporter().export(suite)
        assert result.content[:2] == b"PK"
        assert result.filename.endswith(".xlsx")
        assert "订单系统需求说明" in result.filename

        workbook = load_workbook(io.BytesIO(result.content))
        assert workbook.sheetnames == ["测试用例", "用例统计", "需求追溯", "生成信息"]

        sheet = workbook["测试用例"]
        assert sheet.cell(row=1, column=1).value == "用例编号"
        assert sheet.cell(row=2, column=1).value == "TC-EQ-001"
        assert sheet.cell(row=2, column=4).value == "等价类划分"
        assert sheet.cell(row=3, column=7).value == "REQ-001、REQ-002"
        assert sheet.freeze_panes == "C2"
        assert sheet.max_row == 3

    def test_stats_and_meta_sheets(self, suite: TestCaseSuite) -> None:
        workbook = load_workbook(io.BytesIO(ExcelExporter().export(suite).content))
        stats_values = [cell.value for row in workbook["用例统计"].iter_rows() for cell in row]
        assert "用例总数" in stats_values
        assert 2 in stats_values

        trace_values = [cell.value for row in workbook["需求追溯"].iter_rows() for cell in row]
        assert "REQ-001" in trace_values

        meta_values = [cell.value for row in workbook["生成信息"].iter_rows() for cell in row]
        assert "SUITE-test" in meta_values
        assert "示例告警" in " ".join(str(value) for value in meta_values)

    def test_stats_separates_parse_and_generation_stage(self, suite: TestCaseSuite) -> None:
        """导出必须区分「需求解析」与「用例生成」两阶段口径，不能只写一个模糊的生成方式。"""
        workbook = load_workbook(io.BytesIO(ExcelExporter().export(suite).content))
        stats_values = [cell.value for row in workbook["用例统计"].iter_rows() for cell in row]
        assert "需求解析方式" in stats_values
        assert "用例生成方式" in stats_values

        meta_values = [cell.value for row in workbook["生成信息"].iter_rows() for cell in row]
        assert "需求解析是否使用 LLM" in meta_values
        assert "用例生成是否使用 LLM" in meta_values
        assert "是否使用 LLM" not in meta_values

    def test_empty_suite_is_exportable(self) -> None:
        suite = TestCaseSuite(suite_id="SUITE-empty", doc_id="DOC-1", doc_title="空用例集")
        result = ExcelExporter().export(suite)
        workbook = load_workbook(io.BytesIO(result.content))
        assert "未生成任何用例" in str(workbook["测试用例"].cell(row=2, column=1).value)

    def test_exporter_wraps_unexpected_error(self, suite: TestCaseSuite, monkeypatch) -> None:
        from app.exporters import excel_exporter

        def boom(self, stream):  # noqa: ANN001
            raise RuntimeError("磁盘写入异常")

        monkeypatch.setattr(excel_exporter.Workbook, "save", boom)
        with pytest.raises(ExportError) as excinfo:
            ExcelExporter().export(suite)
        assert excinfo.value.code == "EXPORT_FAILED"


class TestJsonExporter:
    def test_roundtrip(self, suite: TestCaseSuite) -> None:
        result = JsonExporter().export(suite)
        assert result.media_type.startswith("application/json")
        payload = json.loads(result.content.decode("utf-8"))
        assert payload["suite_id"] == "SUITE-test"
        assert payload["cases"][0]["case_id"] == "TC-EQ-001"
        assert payload["stats"]["total"] == 2


class TestExporterRegistry:
    def test_v1_formats_registered(self) -> None:
        names = {item["name"] for item in available_formats()}
        assert {"excel", "json"} <= names

    def test_unknown_format_raises(self) -> None:
        with pytest.raises(NotFoundError):
            get_exporter("xmind")

    def test_media_type_for_excel(self) -> None:
        assert get_exporter("excel").extension == "xlsx"