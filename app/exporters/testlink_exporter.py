"""TestLink XML 导出器。

输出 TestLink「导入测试用例」所用的 XML（``<testsuite>/<testcase>`` + ``<steps>``），
可直接通过 TestLink 的 *Test Case Import* 上传。

映射口径：
  - 用例标题 -> ``name``（TestLink 内同套件下唯一，编号前缀保留以便检索）
  - 备注/设计方法/类型 -> ``summary``
  - 前置条件 -> ``preconditions``
  - 步骤 -> ``<steps><step>``（无显式预期时回落到用例级预期结果，
    避免导入后 TestLink 里出现空步骤）
  - 优先级 -> ``importance``：P0=3 / P1=2 / P2=2 / P3=1（TestLink 只支持 1~3）

为什么用 ElementTree 而不是拼字符串：用例标题与步骤里几乎必然出现 ``<``、``&``
这类字符（如「年龄 < 18」），手拼字符串必须自己转义，漏一处就是导入失败。
"""
from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

from app.core.exceptions import ExportError
from app.exporters.base import Exporter, ExportResult
from app.schemas.testcase import TestCase, TestCaseSuite

#: TestLink 的 importance 只有 1(低) / 2(中) / 3(高) 三档。
IMPORTANCE_MAP = {"P0": "3", "P1": "2", "P2": "2", "P3": "1"}


class TestLinkXmlExporter(Exporter):
    name = "testlink"
    label = "TestLink XML"
    extension = "xml"
    media_type = "application/xml; charset=utf-8"

    def export(self, suite: TestCaseSuite, *, options: dict | None = None) -> ExportResult:
        try:
            suite_name = suite.doc_title or "测试用例"
            root = ET.Element("testsuite", {"name": suite_name})
            description = ET.SubElement(root, "details")
            description.text = self._suite_details(suite)
            for case in suite.cases:
                root.append(self._case_element(case))

            ET.indent(root, space="  ")
            body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        except (ValueError, TypeError) as exc:
            raise ExportError(f"TestLink XML 导出失败：{exc}", detail={"error": str(exc)}) from exc
        return ExportResult(content=body, filename=self.build_filename(suite), media_type=self.media_type)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _suite_details(suite: TestCaseSuite) -> str:
        methods = "、".join(method.label for method in suite.methods) or "（未标注）"
        return (
            f"用例集：{suite.suite_id}\n"
            f"需求文档：{suite.doc_title}（{suite.doc_id}）\n"
            f"设计方法：{methods}\n"
            f"用例总数：{suite.stats.total}\n"
            f"生成时间：{suite.created_at}\n"
            f"生成引擎：{'LLM（' + suite.generation_meta.llm_provider + '）' if suite.generation_meta.llm_used else '规则引擎'}"
        )

    def _case_element(self, case: TestCase) -> ET.Element:
        element = ET.Element("testcase", {"name": self._case_name(case)})
        ET.SubElement(element, "summary").text = self._summary(case)
        if case.preconditions:
            ET.SubElement(element, "preconditions").text = "\n".join(case.preconditions)
        ET.SubElement(element, "importance").text = IMPORTANCE_MAP.get(case.priority.value, "2")
        self._append_steps(element, case)
        self._append_keywords(element, case)
        return element

    @staticmethod
    def _case_name(case: TestCase) -> str:
        prefix = f"{case.case_id} " if case.case_id else ""
        return f"{prefix}{case.title}"

    @staticmethod
    def _summary(case: TestCase) -> str:
        lines = [
            f"所属模块：{case.module}",
            f"设计方法：{case.design_method.label}（用例类型：{case.case_type.value}，优先级：{case.priority.value}）",
            f"关联需求：{'、'.join(case.requirement_ids) or '（未标注）'}",
        ]
        if case.covered_methods:
            lines.append("覆盖方法：" + "、".join(method.label for method in case.covered_methods))
        if case.remarks:
            lines.append(case.remarks)
        return "\n".join(lines)

    @staticmethod
    def _append_steps(element: ET.Element, case: TestCase) -> None:
        steps = ET.SubElement(element, "steps")
        if not case.steps:
            step = ET.SubElement(steps, "step")
            ET.SubElement(step, "step_number").text = "1"
            ET.SubElement(step, "actions").text = f"执行用例「{case.title}」"
            ET.SubElement(step, "expectedresults").text = case.expected_result or ""
            ET.SubElement(step, "execution_type").text = "2"
            return
        for step in case.steps:
            node = ET.SubElement(steps, "step")
            ET.SubElement(node, "step_number").text = str(step.no)
            ET.SubElement(node, "actions").text = step.action
            # 步骤级预期为空时回落到用例级预期：TestLink 里空预期步骤不可执行。
            ET.SubElement(node, "expectedresults").text = step.expected or case.expected_result or ""
            # execution_type: 1=手工 2=自动。
            ET.SubElement(node, "execution_type").text = "1"

    @staticmethod
    def _append_keywords(element: ET.Element, case: TestCase) -> None:
        keywords = [*case.tags]
        if case.test_data:
            keywords.append("测试数据：" + "；".join(f"{k}={v}" for k, v in case.test_data.items()))
        if not keywords:
            return
        container = ET.SubElement(element, "keywords")
        for keyword in keywords:
            word = ET.SubElement(container, "keyword")
            ET.SubElement(word, "name").text = keyword


def parse_export(content: bytes) -> dict[str, Any]:
    """测试与调试用：把导出结果解析回结构化数据。"""
    root = ET.fromstring(content)
    return {
        "name": root.attrib.get("name", ""),
        "cases": [
            {
                "name": case.attrib.get("name", ""),
                "importance": (case.findtext("importance") or "").strip(),
                "steps": len(case.findall("./steps/step")),
            }
            for case in root.findall("testcase")
        ],
    }


__all__ = ["IMPORTANCE_MAP", "TestLinkXmlExporter", "parse_export"]
