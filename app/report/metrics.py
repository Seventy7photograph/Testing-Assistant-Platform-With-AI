"""确定性指标计算。

设计原则：**能算的都算出来，不交给模型。**
模型只负责解释与建议，因此报告里的每个数字都能追溯到输入。
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

from .config import VerdictThresholds
from .schemas import CountItem, Defect, Metrics, MetricsResult

# --------------------------------------------------------------- 字段别名

_TOTAL_KEYS = ("total_cases", "total", "cases", "case_total", "total_count", "用例总数", "总数", "用例数")
_PASSED_KEYS = ("passed", "pass", "passes", "pass_count", "success", "succeeded", "通过", "通过数", "成功数")
_FAILED_KEYS = ("failed", "fail", "fails", "failure", "failures", "fail_count", "失败", "失败数")
_BLOCKED_KEYS = ("blocked", "block", "blocked_count", "阻塞", "阻塞数")
_SKIPPED_KEYS = ("skipped", "skip", "ignored", "pending", "not_run", "untested", "跳过", "未执行", "未运行")

_VERSION_KEYS = ("version", "build", "release", "app_version", "版本", "版本号", "构建号")

_DEFECT_ID_KEYS = ("id", "bug_id", "key", "no", "编号", "缺陷编号")
_DEFECT_TITLE_KEYS = ("title", "name", "summary", "description", "desc", "标题", "描述", "摘要")
_DEFECT_PRIORITY_KEYS = ("priority", "severity", "level", "severity_level", "优先级", "严重程度", "等级")
_DEFECT_MODULE_KEYS = ("module", "component", "area", "feature", "模块", "子系统", "功能")
_DEFECT_STATUS_KEYS = ("status", "state", "状态")

_PRIORITY_ORDER = ["P0", "P1", "P2", "P3"]
_PRIORITY_LABELS = {"P0": "P0 阻断", "P1": "P1 严重", "P2": "P2 一般", "P3": "P3 轻微"}
_STATUS_LABELS = {"open": "未关闭", "resolved": "已修复", "rejected": "已驳回"}
_STATUS_LABELS["unknown"] = "状态未标注"

_OPEN_MARKERS = (
    "待修复", "未修复", "未关闭", "重新打开", "新建", "处理中", "进行中", "遗留", "待处理",
    "open", "new", "reopen", "in progress", "in_progress", "active", "todo", "assigned", "blocked",
    # 这些状态以前既不是 open 也不是 resolved，会被当成"读不出来"而放行。
    "in review", "reviewing", "待复核", "待验证", "验证中", "待回归", "fixing",
    "pending verification", "awaiting",
)
_RESOLVED_MARKERS = (
    "已修复", "已验证", "已关闭", "关闭", "完成", "已解决", "已验收",
    "resolved", "fixed", "closed", "done", "verified", "complete",
    "回归通过", "验证通过", "已回归", "修复完成", "已确认修复",
)
_REJECTED_MARKERS = ("驳回", "不接受", "非缺陷", "rejected", "wontfix", "won't fix", "invalid", "duplicate")

# 否定式必须排在肯定式前面：unresolved 里含 resolved、not fixed 里含 fixed、
# 未完成里含完成。顺序反了就会把「未关闭」读成「已修复」，
# 于是 open_p0 归零，发版闸门被直接放行。
_NEGATED_OPEN_MARKERS = (
    "unresolved", "not resolved", "not fixed", "unfixed", "not closed", "not done",
    "incomplete", "未解决", "未修复", "未关闭", "未完成", "没修复", "尚未修复",
)

_EXCERPT_LIMIT = 160


# --------------------------------------------------------------- 小工具

def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        match = re.search(r"-?\d+", value.replace(",", ""))
        if match:
            return int(match.group(0))
    return None


def _as_text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def _lookup(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    lowered = {str(k).lower(): v for k, v in mapping.items()}
    for key in keys:
        if key.lower() in lowered:
            return lowered[key.lower()]
    return None


def _lookup_int(mapping: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    return _as_int(_lookup(mapping, keys))


def normalize_priority(value: Any) -> str | None:
    text = _as_text(value)
    if not text:
        return None
    upper = text.upper()
    match = re.search(r"P\s*([0-4])", upper)
    if match:
        return f"P{match.group(1)}"
    for keyword, level in (
        ("致命", "P0"), ("阻断", "P0"), ("严重", "P1"), ("主要", "P1"),
        ("一般", "P2"), ("中等", "P2"), ("轻微", "P3"), ("次要", "P3"),
    ):
        if keyword in text:
            return level
    word_map = {
        "BLOCKER": "P0", "CRITICAL": "P0", "FATAL": "P0",
        "MAJOR": "P1", "HIGH": "P1",
        "NORMAL": "P2", "MEDIUM": "P2", "MODERATE": "P2",
        "MINOR": "P3", "LOW": "P3", "TRIVIAL": "P3",
    }
    return word_map.get(upper, text)


def normalize_status(value: Any) -> str | None:
    text = _as_text(value)
    if not text:
        return None
    lower = text.lower()
    if any(marker in lower for marker in _NEGATED_OPEN_MARKERS):
        return "open"
    if any(marker in lower for marker in _REJECTED_MARKERS):
        return "rejected"
    if any(marker in lower for marker in _OPEN_MARKERS):
        return "open"
    if any(marker in lower for marker in _RESOLVED_MARKERS):
        return "resolved"
    # 认不出来的状态归入 unknown，而不是原样返回：原样返回会让它既不算
    # open 也不算 resolved，从而被闸门当成"已关闭"放行。
    return "unknown"


def status_label(key: str) -> str:
    """状态键对应的中文标签（提示词与界面共用）。"""

    return _STATUS_LABELS.get(key, key)


def _priority_label(key: str) -> str:
    return _PRIORITY_LABELS.get(key, key)


def _status_label(key: str) -> str:
    return status_label(key)


# --------------------------------------------------------------- 解析

def parse_payload(raw: str) -> tuple[Any | None, list[str]]:
    """尽力把输入解析成 JSON；失败时返回原因，而不是静默放弃。"""

    text = (raw or "").strip()
    if not text:
        return None, ["输入为空，无法计算指标。"]

    try:
        return json.loads(text), []
    except json.JSONDecodeError:
        pass

    # 真实数据常常是"日志 + JSON"粘贴在一起的，退一步找最外层的 JSON 对象。
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start : end + 1]), [
                "输入不是纯 JSON，已截取其中的 JSON 片段计算指标。"
            ]
        except json.JSONDecodeError:
            pass

    return None, ["输入不是可解析的 JSON，无法计算指标；报告仍会基于原文生成。"]


def _walk(obj: Any, depth: int = 0, key: str | None = None) -> Iterator[tuple[str | None, Any]]:
    """遍历嵌套结构，并带上每一层的键名。

    键名是最强的语义信号：cases / 用例 下面的列表是用例，
    defects / 缺陷 下面的才是缺陷。只看元素长什么样，这两者分不开。
    """

    yield key, obj
    if depth >= 3:
        return
    if isinstance(obj, dict):
        for name, value in obj.items():
            if isinstance(value, (dict, list)):
                yield from _walk(value, depth + 1, str(name))
    elif isinstance(obj, list):
        for value in obj[:5]:
            if isinstance(value, (dict, list)):
                yield from _walk(value, depth + 1, key)


_COUNT_GROUPS = (_TOTAL_KEYS, _PASSED_KEYS, _FAILED_KEYS, _BLOCKED_KEYS, _SKIPPED_KEYS)


def _count_score(candidate: dict[str, Any]) -> int:
    lowered = {str(k).lower() for k in candidate}
    return sum(1 for group in _COUNT_GROUPS if lowered & {k.lower() for k in group})


def find_count_container(parsed: Any) -> dict[str, Any] | None:
    """在嵌套结构里找最像"用例统计"的那一层。"""

    best: dict[str, Any] | None = None
    best_score = 0
    for _key, node in _walk(parsed):
        if not isinstance(node, dict):
            continue
        score = _count_score(node)
        if score > best_score:
            best, best_score = node, score
    return best if best_score >= 2 else None


_DEFECT_CONTAINER_KEYS = (
    "defect", "defects", "bug", "bugs", "issue", "issues", "缺陷", "问题", "bug_list", "defect_list",
)
_CASE_CONTAINER_KEYS = (
    "case", "cases", "testcase", "testcases", "test_case", "test_cases", "tests", "用例", "测试用例",
)
_TESTCASE_ITEM_KEYS = (
    "steps", "step", "expected", "actual", "precondition", "case_id", "testcase", "test_case",
    "用例", "步骤", "预期", "实际", "前置条件",
)
_CASE_ID_RE = re.compile(r"^\s*(tc|case|t)[-_ ]?\d", re.IGNORECASE)


def _matches_vocabulary(key: str | None, vocabulary: tuple[str, ...]) -> bool:
    if not key:
        return False
    lowered = key.lower()
    return any(word in lowered for word in vocabulary)


def _defect_score(items: list[dict[str, Any]]) -> int:
    """给一份列表打分，判断它像不像缺陷清单。

    只看元素字段是不够的 —— 用例清单同样有 id / title / status。
    所以优先级/严重程度权重最高，用例特征字段直接判负。
    """

    keys = {str(k).lower() for k in items[0]}
    if keys & {k.lower() for k in _TESTCASE_ITEM_KEYS}:
        return 0

    score = 0
    if keys & {k.lower() for k in _DEFECT_PRIORITY_KEYS}:
        score += 3
    if keys & {k.lower() for k in _DEFECT_STATUS_KEYS}:
        score += 1
    if keys & {k.lower() for k in _DEFECT_ID_KEYS}:
        score += 1
    if keys & {k.lower() for k in _DEFECT_TITLE_KEYS}:
        score += 1

    first_id = _as_text(_lookup(items[0], _DEFECT_ID_KEYS)) or ""
    if _CASE_ID_RE.match(first_id):
        score -= 2
    return score


def find_defects(parsed: Any) -> list[dict[str, Any]]:
    """找到缺陷清单：一份由字典组成、且字段像缺陷的列表。"""

    best: list[dict[str, Any]] = []
    best_score = 0
    for key, node in _walk(parsed):
        if not isinstance(node, list):
            continue
        items = [item for item in node if isinstance(item, dict)]
        if not items:
            continue

        score = _defect_score(items)
        if _matches_vocabulary(key, _DEFECT_CONTAINER_KEYS):
            score += 2
        elif _matches_vocabulary(key, _CASE_CONTAINER_KEYS):
            score = 0

        if score >= 3 and (score > best_score or (score == best_score and len(items) > len(best))):
            best, best_score = items, score
    return best


def _to_defect(raw: dict[str, Any]) -> Defect:
    raw_status = _as_text(_lookup(raw, _DEFECT_STATUS_KEYS))
    return Defect(
        id=_as_text(_lookup(raw, _DEFECT_ID_KEYS)),
        title=_as_text(_lookup(raw, _DEFECT_TITLE_KEYS)),
        priority=normalize_priority(_lookup(raw, _DEFECT_PRIORITY_KEYS)),
        module=_as_text(_lookup(raw, _DEFECT_MODULE_KEYS)),
        status=normalize_status(raw_status),
        # 归一化会丢信息（待复核 → unknown），原文留着给界面显示。
        status_raw=raw_status,
    )


# --------------------------------------------------------------- 判定

def _decide_verdict(
    total: int,
    pass_rate: float,
    fail_rate: float,
    blocked: int,
    skipped: int,
    execution_rate: float,
    defects_open: int,
    open_p0: int,
    open_p1: int,
    defects_known: bool,
    thresholds: VerdictThresholds,
) -> tuple[str, str, list[str]]:
    """规则判定。每一条依据都写出来，并且带上本次使用的阈值，可被复核。"""

    reasons: list[str] = []

    if total <= 0:
        return "unknown", "无法判定", ["输入中没有用例统计，缺少判定依据。"]

    if open_p0 > 0:
        reasons.append(f"存在 {open_p0} 条未关闭的 P0 缺陷")
        if fail_rate > 0:
            reasons.append(f"用例失败率 {fail_rate * 100:.1f}%")
        return "reject", "不建议发版", reasons

    if open_p1 > 0:
        reasons.append(f"存在 {open_p1} 条未关闭的 P1 缺陷")
    if fail_rate > thresholds.fail_rate:
        reasons.append(
            f"失败率 {fail_rate * 100:.1f}% 高于 {thresholds.fail_rate * 100:.1f}% 阈值"
        )
    if blocked:
        blocked_rate = blocked / total
        if blocked_rate > thresholds.blocked_rate:
            reasons.append(
                f"阻塞率 {blocked_rate * 100:.1f}% 高于 {thresholds.blocked_rate * 100:.1f}% 阈值"
            )
    # 结论只覆盖执行到的范围。执行率不达标时不能给"建议发版"。
    if execution_rate < thresholds.execution_floor:
        reasons.append(
            f"执行率 {execution_rate * 100:.1f}% 低于 {thresholds.execution_floor * 100:.1f}% 下限，"
            "结论未覆盖未执行部分"
        )
    if reasons:
        return "conditional", "有条件通过", reasons

    reasons.append(
        f"通过率 {pass_rate * 100:.1f}%（失败率 {fail_rate * 100:.1f}%，"
        f"均未超过 {thresholds.fail_rate * 100:.1f}% 阈值）"
    )
    if defects_known and defects_open == 0:
        reasons.append("无未关闭缺陷")
    elif defects_open:
        reasons.append(f"仍有 {defects_open} 条未关闭缺陷，但均低于 P1")
    if skipped or blocked:
        reasons.append(f"另有 {skipped} 条未执行、{blocked} 条阻塞，执行率 {execution_rate * 100:.1f}%")
    return "pass", "建议发版", reasons


# --------------------------------------------------------------- 主入口

def compute_metrics(raw: str, thresholds: VerdictThresholds | None = None) -> MetricsResult:
    """把原始输入变成一组可核对的指标。算不出来就诚实地说算不出来。"""

    thresholds = thresholds or VerdictThresholds()
    parsed, warnings = parse_payload(raw)
    if parsed is None:
        return MetricsResult(metrics=None, source_format="text", warnings=warnings)

    result = MetricsResult(source_format="json", warnings=warnings)

    if isinstance(parsed, dict):
        version = _as_text(_lookup(parsed, _VERSION_KEYS))
        if version:
            result.version = version

    container = find_count_container(parsed)
    raw_defects = find_defects(parsed)
    defects = [_to_defect(item) for item in raw_defects]
    deduped: list[Defect] = []
    seen_ids: set[str] = set()
    for defect in defects:
        # 编号 + 模块才算同一条：不同模块复用「1」「2」这类编号是常见做法，
        # 只看编号会把它们误判成重复而丢掉。
        marker = "|".join(
            part for part in ((defect.id or "").strip().lower(), (defect.module or "").strip().lower())
            if part
        )
        if marker:
            if marker in seen_ids:
                continue
            seen_ids.add(marker)
        deduped.append(defect)
    if len(deduped) != len(defects):
        result.warnings.append(
            f"缺陷清单里有 {len(defects) - len(deduped)} 条重复编号，已去重后统计。"
        )
    defects = deduped
    result.defects = defects

    if container is None:
        result.warnings.append("没有找到用例统计字段（如 total_cases / passed / failed），无法计算指标。")
        return result

    total = _lookup_int(container, _TOTAL_KEYS)
    passed = _lookup_int(container, _PASSED_KEYS)
    failed = _lookup_int(container, _FAILED_KEYS)
    blocked = _lookup_int(container, _BLOCKED_KEYS) or 0
    skipped = _lookup_int(container, _SKIPPED_KEYS) or 0

    negative = [
        name
        for name, value in (
            ("总数", total), ("通过", passed), ("失败", failed), ("阻塞", blocked), ("未执行", skipped),
        )
        if value is not None and value < 0
    ]
    if negative:
        result.warnings.append(f"用例计数里出现负数（{'、'.join(negative)}），已按 0 处理。")
        total = None if total is None else max(total, 0)
        passed = None if passed is None else max(passed, 0)
        failed = None if failed is None else max(failed, 0)
        blocked = max(blocked, 0)
        skipped = max(skipped, 0)

    known = [v for v in (passed, failed) if v is not None]
    if total is None:
        if known:
            total = sum(known) + blocked + skipped
            result.warnings.append("输入未给出用例总数，已按各项之和推算。")
        else:
            result.warnings.append("缺少用例总数与通过/失败数，无法计算通过率。")
            return result

    if passed is None:
        passed = max(total - (failed or 0) - blocked - skipped, 0)
        result.warnings.append("输入未给出通过数，已按总数减去其余项推算。")
    if failed is None:
        failed = max(total - passed - blocked - skipped, 0)
        result.warnings.append("输入未给出失败数，已按总数减去其余项推算。")

    declared_total = total
    total = max(total, passed + failed + blocked + skipped)
    if total != declared_total:
        result.warnings.append(
            f"输入中的用例总数（{declared_total}）小于各项之和（{total}），已按各项之和计算。"
        )

    pass_rate = passed / total if total else 0.0
    fail_rate = failed / total if total else 0.0
    executed = max(total - blocked - skipped, 0)
    execution_rate = executed / total if total else 0.0
    # 通过率的分母口径有两种读法，两个都算出来，别让读者自己猜。
    effective_pass_rate = (passed / executed) if executed else 0.0

    by_priority: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_module: dict[str, int] = {}
    open_p0 = open_p1 = 0
    defects_open = 0

    unlabeled_status = 0
    for defect in defects:
        priority = defect.priority or "未标注"
        status = defect.status or "unknown"
        by_priority[priority] = by_priority.get(priority, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
        if defect.module:
            by_module[defect.module] = by_module.get(defect.module, 0) + 1
        # 只有明确标成"已修复/已驳回"的才算关闭；其余（含读不出来的）
        # 一律计入未关闭。闸门宁可拦错，也不能把没读到的缺陷放行。
        if status not in ("resolved", "rejected"):
            defects_open += 1
            if status == "unknown":
                unlabeled_status += 1
            if priority == "P0":
                open_p0 += 1
            elif priority == "P1":
                open_p1 += 1

    if unlabeled_status:
        result.warnings.append(
            f"{unlabeled_status} 条缺陷没有可识别的状态，已按未关闭计入判定。"
        )

    def _ordered(counts: dict[str, int], order: list[str] | None, labeler) -> list[CountItem]:
        keys = list(counts)
        if order:
            keys.sort(key=lambda k: (order.index(k) if k in order else len(order), k))
        else:
            keys.sort(key=lambda k: (-counts[k], k))
        return [CountItem(key=k, label=labeler(k), count=counts[k]) for k in keys]

    verdict, verdict_label, verdict_reasons = _decide_verdict(
        total=total,
        pass_rate=pass_rate,
        fail_rate=fail_rate,
        blocked=blocked,
        skipped=skipped,
        execution_rate=execution_rate,
        defects_open=defects_open,
        open_p0=open_p0,
        open_p1=open_p1,
        defects_known=bool(defects),
        thresholds=thresholds,
    )

    result.metrics = Metrics(
        total=total,
        passed=passed,
        failed=failed,
        blocked=blocked,
        skipped=skipped,
        executed=executed,
        pass_rate=pass_rate,
        fail_rate=fail_rate,
        execution_rate=execution_rate,
        effective_pass_rate=effective_pass_rate,
        defects_total=len(defects),
        defects_open=defects_open,
        open_p0=open_p0,
        open_p1=open_p1,
        by_priority=_ordered(by_priority, _PRIORITY_ORDER, _priority_label),
        by_status=_ordered(by_status, ["open", "unknown", "resolved", "rejected"], _status_label),
        by_module=_ordered(by_module, None, lambda k: k)[:6],
        verdict=verdict,  # type: ignore[arg-type]
        verdict_label=verdict_label,
        verdict_reasons=verdict_reasons,
    )
    return result


def excerpt(text: str, limit: int = _EXCERPT_LIMIT) -> str:
    """列表用的正文摘要：去掉 Markdown 记号，截断到一行。"""

    if not text:
        return ""
    plain = re.sub(r"[#*>`_\[\]()|~-]+", " ", text)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain[:limit] + ("…" if len(plain) > limit else "")
