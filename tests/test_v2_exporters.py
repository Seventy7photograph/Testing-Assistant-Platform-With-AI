"""S3 回归：CSV / XMind / TestLink XML 三种新导出格式。"""
from __future__ import annotations

import csv
import io
import json
import zipfile

import pytest

from app.exporters.csv_exporter import CSV_HEADERS, CsvExporter, sanitize_cell
from app.exporters.registry import get_exporter
from app.exporters.testlink_exporter import TestLinkXmlExporter, parse_export
from app.exporters.xmind_exporter import XMindExporter
from app.schemas.common import CaseSource, CaseType, DesignMethod, Priority
from app.schemas.testcase import GenerationMeta, TestCase, TestCaseSuite, TestStep


def make_suite() -> TestCaseSuite:
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
            remarks="有效等价类",
            source=CaseSource.RULE,
        ),
        TestCase(
            case_id="TC-BV-001",
            title="[边界值] 用户注册｜年龄 最小值-1",
            module="用户中心",
            requirement_ids=["REQ-001"],
            design_method=DesignMethod.BOUNDARY,
            case_type=CaseType.EXCEPTION,
            priority=Priority.P1,
            steps=[TestStep(no=1, action="输入 17", expected="拒绝")],
            expected_result="系统拦截",
            test_data={"年龄": "17"},
        ),
        TestCase(
            case_id="TC-SC-001",
            title="[场景] 退款｜主流程",
            module="订单中心",
            requirement_ids=["REQ-002"],
            design_method=DesignMethod.SCENARIO,
            case_type=CaseType.SCENARIO,
            priority=Priority.P2,
            expected_result="退款成功",
        ),
    ]
    suite = TestCaseSuite(
        suite_id="SUITE-1",
        doc_id="DOC-1",
        doc_title="订单系统需求说明",
        methods=[DesignMethod.EQUIVALENCE, DesignMethod.BOUNDARY, DesignMethod.SCENARIO],
        cases=cases,
        generation_meta=GenerationMeta(methods=["equivalence", "boundary", "scenario"]),
    )
    suite.recount()
    return suite


class TestCsvExporter:
    def test_headers_and_rows(self) -> None:
        result = CsvExporter().export(make_suite())
        # 带 BOM：不然中文 Windows 的 Excel 打开就是乱码。
        assert result.content[:3] == b"\xef\xbb\xbf"
        text = result.content.decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        assert rows[0] == [header for _, header in CSV_HEADERS]
        assert len(rows) == 4
        assert rows[1][0] == "TC-EQ-001"
        assert rows[1][3] == "等价类划分"
        assert "1. 输入手机号 -> 预期：校验通过" in rows[1][8]

    def test_extension_and_media_type(self) -> None:
        exporter = get_exporter("csv")
        assert exporter.extension == "csv"
        assert exporter.media_type.startswith("text/csv")

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("=SUM(A1:A2)", "'=SUM(A1:A2)"),
            ("+1+1", "'+1+1"),
            ("@import", "'@import"),
            ("-1", "-1"),
            ("-17", "-17"),
            ("-abc", "'-abc"),
            ("正常文本", "正常文本"),
            ("", ""),
        ],
    )
    def test_formula_injection_is_neutralized(self, value: str, expected: str) -> None:
        assert sanitize_cell(value) == expected

    def test_formula_payload_in_case_title(self) -> None:
        suite = make_suite()
        suite.cases[0].title = "=cmd|' /C calc'!A0"
        text = CsvExporter().export(suite).content.decode("utf-8-sig")
        assert "'=cmd" in text


class TestXMindExporter:
    def test_is_valid_xmind_package(self) -> None:
        result = XMindExporter().export(make_suite())
        assert result.filename.endswith(".xmind")
        with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
            assert {"content.json", "metadata.json", "manifest.json"} <= set(archive.namelist())
            content = json.loads(archive.read("content.json").decode("utf-8"))
            metadata = json.loads(archive.read("metadata.json").decode("utf-8"))
        assert metadata["creator"]["name"]
        sheet = content[0]
        assert sheet["class"] == "sheet"
        root = sheet["rootTopic"]
        assert root["title"] == "订单系统需求说明"
        titles = [topic["title"] for topic in root["children"]["attached"]]
        assert any(title.startswith("统计：") for title in titles)
        assert any("用户中心" in title for title in titles)
        assert any("订单中心" in title for title in titles)

    def test_case_topic_carries_steps_and_expectation(self) -> None:
        result = XMindExporter().export(make_suite())
        with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
            content = json.loads(archive.read("content.json").decode("utf-8"))
        modules = content[0]["rootTopic"]["children"]["attached"]
        user_center = next(item for item in modules if "用户中心" in item["title"])
        case_topic = user_center["children"]["attached"][0]
        assert case_topic["title"].startswith("[P0] TC-EQ-001")
        details = " ".join(child["title"] for child in case_topic["children"]["attached"])
        assert "设计方法：等价类划分" in details
        assert "预期结果：注册成功" in details
        assert "测试数据：手机号=13800000000" in details

    def test_topic_ids_are_stable(self) -> None:
        first = XMindExporter().export(make_suite()).content
        second = XMindExporter().export(make_suite()).content
        with zipfile.ZipFile(io.BytesIO(first)) as left, zipfile.ZipFile(io.BytesIO(second)) as right:
            assert left.read("content.json") == right.read("content.json")

    def test_empty_suite_is_exportable(self) -> None:
        suite = TestCaseSuite(suite_id="SUITE-empty", doc_id="DOC-1", doc_title="空用例集")
        with zipfile.ZipFile(io.BytesIO(XMindExporter().export(suite).content)) as archive:
            content = json.loads(archive.read("content.json").decode("utf-8"))
        titles = [topic["title"] for topic in content[0]["rootTopic"]["children"]["attached"]]
        assert any("未生成任何用例" in title for title in titles)


class TestTestLinkExporter:
    def test_structure_and_importance(self) -> None:
        result = TestLinkXmlExporter().export(make_suite())
        assert result.media_type.startswith("application/xml")
        payload = parse_export(result.content)
        assert payload["name"] == "订单系统需求说明"
        assert [case["name"] for case in payload["cases"]] == [
            "TC-EQ-001 [等价类] 用户注册｜手机号 有效等价类",
            "TC-BV-001 [边界值] 用户注册｜年龄 最小值-1",
            "TC-SC-001 [场景] 退款｜主流程",
        ]
        # TestLink 的 importance 只有 1~3；P0 -> 3，P1/P2 -> 2。
        assert [case["importance"] for case in payload["cases"]] == ["3", "2", "2"]

    def test_case_without_steps_still_importable(self) -> None:
        payload = parse_export(TestLinkXmlExporter().export(make_suite()).content)
        assert all(case["steps"] >= 1 for case in payload["cases"])

    def test_special_characters_are_escaped(self) -> None:
        suite = make_suite()
        suite.cases[0].title = "年龄 < 18 & 手机号 > 11 位"
        suite.cases[0].expected_result = "拒绝 <script>"
        content = TestLinkXmlExporter().export(suite).content
        assert b"<script>" not in content
        # 转义后仍能被 XML 解析器读回原值。
        payload = parse_export(content)
        assert payload["cases"][0]["name"].endswith("年龄 < 18 & 手机号 > 11 位")

    def test_summary_carries_method_and_requirements(self) -> None:
        content = TestLinkXmlExporter().export(make_suite()).content
        text = content.decode("utf-8")
        assert "设计方法：等价类划分" in text
        assert "REQ-001" in text
