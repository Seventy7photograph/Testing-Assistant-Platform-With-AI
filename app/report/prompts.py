"""提示词。"""

from __future__ import annotations

from .metrics import status_label
from .schemas import Metrics, MetricsResult

_DEFECT_LIST_LIMIT = 40

SYSTEM_PROMPT = """你是一名企业级软件测试分析助手。
你的任务是分析测试执行数据，输出结构化、可执行的测试报告。

必须遵守：
1. 区分事实与推断。凡是输入中直接给出的数据都是事实；你的判断必须标注为推断。
2. 优先关注 P0/P1 缺陷、高风险模块、阻塞项。
3. 指标（通过率、失败率、执行率、缺陷分布）已由系统精确计算并给出，直接引用，不要自己重算，也不要改动数值。
4. 绝不虚构输入中不存在的缺陷、模块、业务事实或数字。
5. 如果输入数据不足以支撑某个结论，直接说明"数据不足"，不要猜测。

输出结构（使用简洁的中文 Markdown）：
## 测试概况
## 关键指标解读
## 主要缺陷与风险
## 风险判断依据
## 建议与下一步"""


def _format_metrics(result: MetricsResult) -> str:
    metrics: Metrics | None = result.metrics
    if metrics is None:
        return "（本次输入无法解析出可计算指标，请仅基于原文分析，并说明数据不足。）"

    lines = [
        f"- 用例总数：{metrics.total}",
        f"- 通过：{metrics.passed}（{(metrics.pass_rate):.1%}）",
        f"- 失败：{metrics.failed}（{(metrics.fail_rate):.1%}）",
        f"- 阻塞：{metrics.blocked}",
        f"- 未执行：{metrics.skipped}",
        f"- 执行率：{(metrics.execution_rate):.1%}",
        f"- 系统判定：{metrics.verdict_label}",
    ]
    if metrics.verdict_reasons:
        lines.append("- 判定依据：" + "；".join(metrics.verdict_reasons))
    if metrics.defects_total:
        lines.append(
            f"- 缺陷：共 {metrics.defects_total} 条，其中未关闭 {metrics.defects_open} 条"
            f"（P0 未关闭 {metrics.open_p0}，P1 未关闭 {metrics.open_p1}）"
        )
    if metrics.by_priority:
        lines.append(
            "- 按优先级：" + "、".join(f"{item.label} {item.count}" for item in metrics.by_priority)
        )
    if metrics.by_module:
        lines.append(
            "- 按模块：" + "、".join(f"{item.label} {item.count}" for item in metrics.by_module)
        )
    if result.defects:
        # 明细也放进"权威口径"：否则模型回答"哪个模块缺陷最密"时
        # 只能自己数原始数据，容易和上面的统计对不上。
        lines.append("- 缺陷明细（编号 | 优先级 | 模块 | 状态）：")
        for defect in result.defects[:_DEFECT_LIST_LIMIT]:
            status = defect.status or "unknown"
            label = status_label(status)
            if status == "unknown":
                label = f"{label}（按未关闭计）"
            lines.append(
                f"  - {defect.id or '未编号'} | {defect.priority or '未标注'} | "
                f"{defect.module or '未标注模块'} | {label}"
            )
        if len(result.defects) > _DEFECT_LIST_LIMIT:
            lines.append(f"  - …另有 {len(result.defects) - _DEFECT_LIST_LIMIT} 条未列出，见原始数据。")
    return "\n".join(lines)


def build_user_prompt(
    result: MetricsResult, normalized_data: str, instruction: str
) -> str:
    sections = [
        "请分析以下软件测试数据。",
        "",
        "【系统计算结果（权威，请直接引用）】",
        _format_metrics(result),
        "",
        "【原始测试数据】",
        normalized_data,
        "",
        "【额外要求】",
        instruction,
        "",
        "再次强调：不要编造数据，不要重算上方已给出的指标。",
    ]
    return "\n".join(sections)
