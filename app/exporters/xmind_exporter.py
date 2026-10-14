"""XMind 导出器。

输出 XMind Zen / 2020+ 的 ``.xmind`` 包（本质是 zip）：

    content.json   思维导图本体（一个 sheet + rootTopic 树）
    metadata.json  创建者信息（XMind 打开时会校验，缺了会提示文件异常）
    manifest.json  包内清单

树形结构：用例集 -> 模块 -> 用例 -> 明细（设计方法/优先级/前置/步骤/预期/数据）。

为什么是 JSON 而不是老的 content.xml：XMind 8 之后的桌面版与移动端都读 JSON 格式，
老格式在新版里会被提示升级；JSON 结构也更适合用代码生成与断言。
"""
from __future__ import annotations

import io
import json
import zipfile
from typing import Any

from app.core.exceptions import ExportError
from app.core.utils import short_hash
from app.exporters.base import Exporter, ExportResult
from app.schemas.testcase import TestCase, TestCaseSuite

CREATOR_NAME = "测试工程师助手平台"
CREATOR_VERSION = "2.0.0"

#: 树形结构用「逻辑图」布局，用例分支多时比思维导图更易读。
STRUCTURE_CLASS = "org.xmind.ui.logic.right"


class XMindExporter(Exporter):
    name = "xmind"
    label = "XMind"
    extension = "xmind"
    media_type = "application/vnd.xmind.workbook"

    def export(self, suite: TestCaseSuite, *, options: dict | None = None) -> ExportResult:
        try:
            sheet = {
                "id": topic_id("sheet", suite.suite_id),
                "class": "sheet",
                "title": suite.doc_title or "测试用例",
                "rootTopic": self._root_topic(suite),
            }
            content = json.dumps([sheet], ensure_ascii=False).encode("utf-8")
            metadata = json.dumps(
                {"creator": {"name": CREATOR_NAME, "version": CREATOR_VERSION}},
                ensure_ascii=False,
            ).encode("utf-8")
            manifest = json.dumps(
                {"file-entries": {"content.json": {}, "metadata.json": {}}},
                ensure_ascii=False,
            ).encode("utf-8")

            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("content.json", content)
                archive.writestr("metadata.json", metadata)
                archive.writestr("manifest.json", manifest)
            payload = buffer.getvalue()
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            raise ExportError(f"XMind 导出失败：{exc}", detail={"error": str(exc)}) from exc

        return ExportResult(content=payload, filename=self.build_filename(suite), media_type=self.media_type)

    # ------------------------------------------------------------------ #
    def _root_topic(self, suite: TestCaseSuite) -> dict[str, Any]:
        root = self._topic(suite.doc_title or "测试用例", path="root")
        if not suite.cases:
            root["children"] = {"attached": [self._topic("（本次未生成任何用例）", path="empty")]}
            return root

        grouped: dict[str, list[TestCase]] = {}
        for case in suite.cases:
            grouped.setdefault(case.module or "默认模块", []).append(case)

        modules: list[dict[str, Any]] = []
        for module, cases in grouped.items():
            module_topic = self._topic(f"{module}（{len(cases)}）", path=f"module:{module}")
            module_topic["children"] = {
                "attached": [
                    self._case_topic(case, path=f"case:{case.case_id or index}") 
                    for index, case in enumerate(cases, start=1)
                ]
            }
            modules.append(module_topic)

        summary = self._topic(
            f"统计：{suite.stats.total} 条用例 / {len(grouped)} 个模块",
            path="summary",
        )
        summary["children"] = {
            "attached": [
                # stats.by_method 的键是设计方法的中文名（与 Excel/界面口径一致）。
                self._topic(f"{label}：{count} 条", path=f"stat:{label}")
                for label, count in sorted(
                    suite.stats.by_method.items(), key=lambda item: item[0]
                )
            ]
        }
        root["children"] = {"attached": [summary, *modules]}
        return root

    def _case_topic(self, case: TestCase, *, path: str) -> dict[str, Any]:
        title = f"{case.case_id or ''} {case.title}".strip()
        topic = self._topic(f"[{case.priority.value}] {title}", path=path)
        details: list[dict[str, Any]] = [
            self._leaf(f"设计方法：{case.design_method.label}", path=f"{path}|method"),
            self._leaf(f"用例类型：{case.case_type.value}", path=f"{path}|type"),
            self._leaf(f"关联需求：{'、'.join(case.requirement_ids) or '（未标注）'}", path=f"{path}|req"),
        ]
        if case.preconditions:
            details.append(
                self._leaf("前置条件：" + "；".join(case.preconditions), path=f"{path}|pre")
            )
        if case.steps:
            details.append(self._leaf("测试步骤", path=f"{path}|steps"))
            details[-1]["children"] = {
                "attached": [
                    self._leaf(
                        f"{step.no}. {step.action}" + (f" -> 预期：{step.expected}" if step.expected else ""),
                        path=f"{path}|step{step.no}",
                    )
                    for step in case.steps
                ]
            }
        details.append(self._leaf(f"预期结果：{case.expected_result or '（未填写）'}", path=f"{path}|expect"))
        if case.test_data:
            details.append(
                self._leaf("测试数据：" + "；".join(f"{k}={v}" for k, v in case.test_data.items()), path=f"{path}|data")
            )
        if case.remarks:
            details.append(self._leaf(f"备注：{case.remarks}", path=f"{path}|remark"))
        topic["children"] = {"attached": details}
        return topic

    @staticmethod
    def _topic(title: str, *, path: str) -> dict[str, Any]:
        return {
            "id": topic_id("topic", path),
            "class": "topic",
            "title": title,
            "structureClass": STRUCTURE_CLASS,
        }

    @staticmethod
    def _leaf(title: str, *, path: str) -> dict[str, Any]:
        return {"id": topic_id("topic", path), "class": "topic", "title": title}


def topic_id(kind: str, path: str) -> str:
    """稳定的主题 ID：同样的用例集导两次得到同样的 ID，便于版本比对。"""
    return short_hash(kind, path, length=24)


__all__ = ["CREATOR_NAME", "XMindExporter", "topic_id"]
