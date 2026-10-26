"""安全解析 pytest JUnit XML。"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from app.core.exceptions import DocumentParseError
from app.core.utils import truncate
from app.schemas.execution import CaseResult

CASE_ID_RE = re.compile(r"(?:\[|\()((?:API|CASE|TC)[A-Za-z0-9._-]{3,})(?:\]|\))")


class JUnitParseError(DocumentParseError):
    code = "JUNIT_PARSE_FAILED"
    default_message = "JUnit XML 解析失败"


def _duration_ms(raw: str | None) -> int:
    try:
        return max(0, round(float(raw or 0) * 1000))
    except (TypeError, ValueError):
        return 0


def _case_id(node: ET.Element) -> str | None:
    explicit = node.attrib.get("case_id")
    if explicit:
        return explicit
    for prop in node.findall("./properties/property"):
        if (prop.attrib.get("name") or "").lower() == "case_id":
            value = prop.attrib.get("value") or (prop.text or "")
            if value.strip():
                return value.strip()
    for text in (node.attrib.get("name", ""), node.attrib.get("classname", "")):
        match = CASE_ID_RE.search(text)
        if match:
            return match.group(1)
    return None


def _node_text(node: ET.Element | None, limit: int = 4000) -> str:
    if node is None:
        return ""
    content = node.text or ""
    return truncate(content.strip(), limit)


def parse_junit_xml(data: bytes, *, source_file: str = "") -> tuple[list[CaseResult], int, list[str]]:
    """返回 case 结果、总耗时与解析告警。"""
    if not data.strip():
        raise JUnitParseError("JUnit XML 内容为空。", detail={"source_file": source_file})
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise JUnitParseError(
            "JUnit XML 格式不合法，请确认文件来自 pytest 的 --junitxml 输出。",
            detail={"source_file": source_file, "error": str(exc)},
        ) from exc
    if root.tag not in {"testsuite", "testsuites"}:
        raise JUnitParseError(
            "根节点必须是 testsuite 或 testsuites。",
            detail={"source_file": source_file, "root": root.tag},
        )

    results: list[CaseResult] = []
    warnings: list[str] = []
    for node in root.iter("testcase"):
        failure = node.find("failure")
        error = node.find("error")
        skipped = node.find("skipped")
        if error is not None:
            status = "error"
            detail = error
        elif failure is not None:
            status = "failed"
            detail = failure
        elif skipped is not None:
            status = "skipped"
            detail = skipped
        else:
            status = "passed"
            detail = None
        message = ""
        if detail is not None:
            message = detail.attrib.get("message") or _node_text(detail, 1000)
        case_id = _case_id(node)
        if not case_id:
            warnings.append(f"测试 {node.attrib.get('name', 'unknown')} 缺少 case_id，按未匹配处理。")
        results.append(
            CaseResult(
                case_id=case_id,
                name=truncate(node.attrib.get("name", ""), 500),
                classname=truncate(node.attrib.get("classname", ""), 500),
                status=status,
                duration_ms=_duration_ms(node.attrib.get("time")),
                message=truncate(message, 2000),
                stdout=_node_text(node.find("system-out")),
                stderr=_node_text(node.find("system-err")),
            )
        )

    if not results:
        warnings.append("JUnit XML 中没有 testcase 节点。")
    total_duration = 0
    suite_nodes = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suite_nodes:
        suite_nodes = list(root.iter("testsuite"))
    total_duration = sum(_duration_ms(node.attrib.get("time")) for node in suite_nodes)
    if not total_duration:
        total_duration = sum(item.duration_ms for item in results)
    return results, total_duration, warnings


__all__ = ["JUnitParseError", "parse_junit_xml"]
