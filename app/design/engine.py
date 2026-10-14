"""设计引擎：把「结构化需求」按所选设计方法批量转换为「测试用例集」。

职责边界：
  - 只负责调度策略、隔离单个策略/单条需求的异常；
  - 不关心 LLM 细节（由 DesignContext 注入的 Provider 承担）；
  - 不关心导出格式（由 exporter 层承担）。
"""
from __future__ import annotations

import collections
import asyncio

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError, FeatureNotAvailableError, NotFoundError
from app.core.logging import get_logger
from app.core.utils import Timer, new_id
from app.design.base import (
    DEFAULT_LLM_DESIGN_MODE,
    LLM_DESIGN_MODES,
    DesignContext,
    DesignStrategy,
    TruncationRecord,
)
from app.design.enrichment import review_item
from app.design.optimizer import optimize
from app.design.registry import STRATEGY_REGISTRY, available_methods, build_strategies
from app.llm.base import LLMProvider
from app.schemas.common import DEFAULT_METHODS, CaseSource, DesignMethod
from app.schemas.requirement import RequirementDoc, RequirementItem
from app.schemas.testcase import GenerationMeta, TestCase, TestCaseSuite

#: 复核请求的并发度：多模态/对话端点普遍有并发限制，放开只会换来 429。
LLM_REVIEW_CONCURRENCY = 3

logger = get_logger(__name__)

# 某个设计方法「一条都没产出」时，告诉用户为什么，而不是只给一个 0。
_EMPTY_METHOD_HINTS: dict[str, str] = {
    DesignMethod.EQUIVALENCE.value: (
        "等价类划分需要需求条目给出字段约束（类型 / 枚举 / 取值区间 / 长度）或业务规则；"
        "纯描述性的条目划不出等价类。"
    ),
    DesignMethod.BOUNDARY.value: (
        "边界值分析需要数值区间或长度上下限（min / max / 长度限制）；没有边界就取不到点。"
    ),
    DesignMethod.SCENARIO.value: (
        "场景法需要主流程 / 备选流 / 异常流或业务规则；只有字段清单的条目串不成场景。"
    ),
    DesignMethod.DECISION_TABLE.value: (
        "判定表需要至少 2 个带约束的字段（枚举 / 数值区间 / 长度区间 / 必填 / 格式）"
        "才能构成条件桩与动作桩；只有一个条件时没有组合可判定。"
    ),
    DesignMethod.CAUSE_EFFECT.value: (
        "因果图需要业务规则里出现「若…则…」这类因果表述，或至少 2 个带约束的字段"
        "用于补齐「因」；没有任何规则与约束时无因果可画。"
    ),
    DesignMethod.ORTHOGONAL.value: (
        "正交实验需要至少 2 个具备 2 个以上水平的因子（枚举取值 / 数值区间 / 长度区间）；"
        "无区间也无枚举的字段没有水平，构不成因子。"
    ),
}


def _is_implemented(method: DesignMethod) -> bool:
    """该方法是否已注册且已实现（用于能力清单与 501 提示）。"""
    strategy_cls = STRATEGY_REGISTRY.try_get(method.value)
    return bool(strategy_cls and strategy_cls.implemented)


def normalize_llm_design_mode(raw: str | None) -> str:
    """把请求里的模式收敛到受支持的值，未知值回落默认（不抛错）。"""
    value = str(raw or "").strip().lower()
    return value if value in LLM_DESIGN_MODES else DEFAULT_LLM_DESIGN_MODE


def fair_share_trim(
    cases: list[TestCase], limit: int
) -> tuple[list[TestCase], dict[str, int], dict[str, int]]:
    """超过单条需求上限时，**在方法之间轮转保留**，而不是"先到先得"。

    为什么必须这样：用例是按设计方法的顺序依次产出的，简单地取前 N 条，等于让排在前面的
    方法（等价类、边界值）把额度吃光，排在后面的方法一条都进不来。实测同一份需求：
    顺序截断到 60 条时正交实验只剩 13 条，而它的自然产出是 47 条 —— 这不是"少了些用例"，
    而是新加的方法被系统性地饿死，使用者在结果里根本看不出它跑过。

    轮转保留保证每种被选中的方法都有代表进入结果；方法内部仍保持原有顺序。

    :return: (保留的用例, 各方法总数, 各方法保留数)
    """
    buckets: dict[str, list[TestCase]] = {}
    order: list[str] = []
    for case in cases:
        key = case.design_method.value
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(case)

    totals = {key: len(buckets[key]) for key in order}
    kept_counts = {key: 0 for key in order}
    keep: set[int] = set()
    cursor = 0
    while len(keep) < limit:
        progressed = False
        for key in order:
            bucket = buckets[key]
            if cursor >= len(bucket):
                continue
            keep.add(id(bucket[cursor]))
            kept_counts[key] += 1
            progressed = True
            if len(keep) >= limit:
                break
        if not progressed:
            break
        cursor += 1
    # 按原始顺序输出，保证结果确定（排序与编号在 optimize 里统一做）。
    kept = [case for case in cases if id(case) in keep]
    return kept, totals, kept_counts


class DesignEngine:
    """测试用例设计引擎。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------ #
    def available_methods(self) -> list[dict]:
        return available_methods()

    def resolve_methods(self, methods: list[str | DesignMethod] | None) -> list[DesignMethod]:
        """把用户输入的方法名解析为枚举，并校验是否已实现。"""
        requested = list(methods) if methods else list(DEFAULT_METHODS)
        resolved: list[DesignMethod] = []
        for raw in requested:
            try:
                method = raw if isinstance(raw, DesignMethod) else DesignMethod(str(raw).strip().lower())
            except ValueError as exc:
                raise NotFoundError(
                    f"未知的设计方法：{raw}，可选值：{', '.join(STRATEGY_REGISTRY.names())}",
                    detail={"available": STRATEGY_REGISTRY.names()},
                ) from exc
            if method not in resolved:
                resolved.append(method)

        unimplemented = [m.label for m in resolved if not STRATEGY_REGISTRY.get(m.value).implemented]
        if unimplemented:
            raise FeatureNotAvailableError(
                "以下设计方法已在架构中预留但尚未实现：" + "、".join(unimplemented),
                detail={
                    "unimplemented": unimplemented,
                    "implemented": [
                        method.label for method in DesignMethod if _is_implemented(method)
                    ],
                },
            )
        if not resolved:
            raise NotFoundError("至少需要选择一种设计方法。")
        return resolved

    # ------------------------------------------------------------------ #
    async def generate(
        self,
        doc: RequirementDoc,
        methods: list[str | DesignMethod] | None = None,
        *,
        llm: LLMProvider,
        use_llm: bool = False,
        max_cases_per_item: int | None = None,
        llm_design_mode: str | None = None,
    ) -> TestCaseSuite:
        """对整份需求文档生成用例集。"""
        resolved = self.resolve_methods(methods)
        # 上限可由调用方按请求覆盖（界面上的「单条需求用例上限」），否则用服务端默认值。
        limit = self.settings.max_cases_per_requirement if max_cases_per_item is None else max_cases_per_item
        mode = normalize_llm_design_mode(llm_design_mode)
        context = DesignContext(
            settings=self.settings,
            llm=llm,
            use_llm=use_llm,
            max_cases_per_item=limit,
            llm_review_mode=mode,
            max_llm_calls=int(self.settings.llm_max_calls_per_generation or 20),
        )
        strategies = build_strategies(context)
        selected: list[DesignStrategy] = [strategies[method.value] for method in resolved]

        if use_llm and not llm.available:
            context.warn(f"未启用大模型（{llm.degraded_reason or '未配置'}），本次仅使用规则引擎生成用例。")

        per_item: list[tuple[RequirementItem, list[TestCase]]] = []
        with Timer() as timer:
            for item in doc.items:
                per_item.append((item, await self._generate_for_item(item, selected, context)))
            if context.llm_review_enabled:
                await self._review_items(per_item, resolved, context)

        cases: list[TestCase] = [case for _, item_cases in per_item for case in item_cases]

        unique_cases, duplicates = optimize(cases)

        # 截断告警必须等到去重之后才生成：只有这时才知道「截断前 N 条」最终留下多少条。
        # 之前在校验前就报警，界面会出现「已截断到 60」却只显示 48 条的自相矛盾。
        final_counts = collections.Counter()
        for case in unique_cases:
            for requirement_id in case.requirement_ids:
                final_counts[requirement_id] += 1
        for record in context.truncations:
            final = final_counts.get(record.requirement_id, 0)
            context.warn(
                f"需求「{record.requirement_title}」生成 {record.raw_count} 条，超过单条需求上限 "
                f"{context.max_cases_per_item}，已按方法轮转保留 {record.kept_count} 条"
                f"（去重合并后本需求 {final} 条），请人工复核遗漏场景。"
            )

        # 如实解释「为什么是 0」：按方法统计产出，空手而归的方法必须给出可执行的下一步。
        produced: dict[str, int] = {}
        for case in unique_cases:
            produced[case.design_method.value] = produced.get(case.design_method.value, 0) + 1
        for method in resolved:
            if produced.get(method.value):
                continue
            hint = _EMPTY_METHOD_HINTS.get(
                method.value, "当前需求条目没有匹配到该方法的适用条件。"
            )
            context.warn(f"「{method.label}」本次未产出用例：{hint}")

        # 只有真正产出（且未被去重剔除）LLM 用例时才认为"生成阶段用了 LLM"；
        # 若模型调用失败并降级为规则用例，元数据必须如实显示为规则引擎。
        llm_case_count = sum(
            1 for case in unique_cases if case.source in (CaseSource.LLM, CaseSource.HYBRID)
        )
        # 复核模式可能只产出意见、不产出用例，但模型确实被调用了 ——
        # 口径上要如实反映，否则「本次用了模型」这件事在元数据里会消失。
        llm_calls = context.llm_call_count
        llm_used = llm_case_count > 0 or llm_calls > 0

        suite = TestCaseSuite(
            suite_id=new_id("SUITE-"),
            doc_id=doc.doc_id,
            doc_title=doc.title,
            methods=resolved,
            cases=unique_cases,
            generation_meta=GenerationMeta(
                methods=[method.value for method in resolved],
                llm_used=llm_used,
                llm_provider=llm.name,
                llm_model=llm.model,
                llm_calls=llm_calls,
                fallback_used=not llm.available,
                warnings=context.warnings,
                review_findings=context.findings,
                elapsed_ms=timer.elapsed_ms,
            ),
        )
        suite.stats.duplicate_removed = duplicates
        suite.recount()
        logger.info(
            "用例生成完成：doc=%s 方法=%s 用例数=%d（去重 %d）耗时=%dms",
            doc.doc_id,
            [m.value for m in resolved],
            suite.stats.total,
            duplicates,
            timer.elapsed_ms,
        )
        return suite

    # ------------------------------------------------------------------ #
    async def _review_items(
        self,
        per_item: list[tuple[RequirementItem, list[TestCase]]],
        methods: list[DesignMethod],
        context: DesignContext,
    ) -> None:
        """让大模型复核「规则引擎的产出」，并按模式决定是否补充用例。

        按需求条目调用（一条需求一次），而不是每个方法调一次：六个方法各调一次意味着
        一份 5 条需求的文档要发 30 次请求，成本与耗时都不成立。
        """
        budget = max(int(context.max_llm_calls or 0), 0)
        targets = per_item[:budget]
        if len(per_item) > len(targets):
            context.warn(
                f"大模型复核按调用上限（{budget} 次）只覆盖了前 {len(targets)} 条需求，"
                f"其余 {len(per_item) - len(targets)} 条沿用规则结果。"
            )
        if not targets:
            context.warn("本次未执行大模型复核：生成阶段的大模型调用预算为 0。")
            return

        allow_cases = context.llm_extra_cases_enabled
        semaphore = asyncio.Semaphore(LLM_REVIEW_CONCURRENCY)

        async def run(item: RequirementItem, cases: list[TestCase]):
            async with semaphore:
                return await review_item(
                    item,
                    cases,
                    context=context,
                    methods=methods,
                    allow_cases=allow_cases,
                    max_cases=context.max_llm_cases_per_item,
                )

        results = await asyncio.gather(*(run(item, cases) for item, cases in targets))
        extra_total = 0
        for (_, item_cases), (extra, findings) in zip(targets, results):
            item_cases.extend(extra)
            extra_total += len(extra)
            context.findings.extend(findings)
        if context.findings:
            context.warn(
                f"大模型复核共给出 {len(context.findings)} 条意见"
                + (f"，并补充 {extra_total} 条用例（均需人工复核）。" if extra_total else "（未补充用例）。")
            )

    # ------------------------------------------------------------------ #
    async def _generate_for_item(
        self,
        item: RequirementItem,
        strategies: list[DesignStrategy],
        context: DesignContext,
    ) -> list[TestCase]:
        cases: list[TestCase] = []
        for strategy in strategies:
            try:
                if not strategy.is_applicable(item):
                    continue
                produced = await strategy.generate(item)
            except AppError as exc:
                # 单条需求/单个方法的失败不应中断整体生成（关键异常路径兜底）
                context.warn(
                    f"需求「{item.title}」使用「{strategy.method.label}」生成失败（{exc.code}）：{exc.message}"
                )
                logger.warning("策略 %s 处理需求 %s 失败：%s", strategy.name, item.id, exc)
                continue
            except Exception as exc:  # noqa: BLE001 - 兜底：防止第三方异常导致整批失败
                context.warn(f"需求「{item.title}」使用「{strategy.method.label}」出现未知异常：{exc}")
                logger.exception("策略 %s 处理需求 %s 出现未知异常", strategy.name, item.id)
                continue
            cases.extend(produced)
        # 设计上下文里的上限语义是「单条需求最多生成的用例数」（跨全部设计方法），
        # 策略内部只做了单方法截断，这里补一层条目级兜底，避免多方法叠加后超限。
        limit = context.max_cases_per_item
        if limit and len(cases) > limit:
            kept, totals, kept_counts = fair_share_trim(cases, limit)
            context.note_truncation(
                TruncationRecord(
                    requirement_id=item.id,
                    requirement_title=item.title,
                    raw_count=len(cases),
                    kept_count=len(kept),
                    per_method_total=totals,
                    per_method_kept=kept_counts,
                )
            )
            cases = kept
        return cases
