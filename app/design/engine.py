"""设计引擎：把「结构化需求」按所选设计方法批量转换为「测试用例集」。

职责边界：
  - 只负责调度策略、隔离单个策略/单条需求的异常；
  - 不关心 LLM 细节（由 DesignContext 注入的 Provider 承担）；
  - 不关心导出格式（由 exporter 层承担）。
"""
from __future__ import annotations

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError, FeatureNotAvailableError, NotFoundError
from app.core.logging import get_logger
from app.core.utils import Timer, new_id
from app.design.base import DesignContext, DesignStrategy
from app.design.optimizer import optimize
from app.design.registry import STRATEGY_REGISTRY, available_methods, build_strategies
from app.llm.base import LLMProvider
from app.schemas.common import CaseSource, DesignMethod
from app.schemas.requirement import RequirementDoc, RequirementItem
from app.schemas.testcase import GenerationMeta, TestCase, TestCaseSuite

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
}


class DesignEngine:
    """测试用例设计引擎。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------ #
    def available_methods(self) -> list[dict]:
        return available_methods()

    def resolve_methods(self, methods: list[str | DesignMethod] | None) -> list[DesignMethod]:
        """把用户输入的方法名解析为枚举，并校验是否已实现。"""
        requested = methods or [DesignMethod.EQUIVALENCE, DesignMethod.BOUNDARY, DesignMethod.SCENARIO]
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
                    "implemented": [m.label for m in DesignMethod if STRATEGY_REGISTRY.try_get(m.value) and STRATEGY_REGISTRY.get(m.value).implemented],
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
    ) -> TestCaseSuite:
        """对整份需求文档生成用例集。"""
        resolved = self.resolve_methods(methods)
        context = DesignContext(
            settings=self.settings,
            llm=llm,
            use_llm=use_llm,
            max_cases_per_item=self.settings.max_cases_per_requirement,
        )
        strategies = build_strategies(context)
        selected: list[DesignStrategy] = [strategies[method.value] for method in resolved]

        if use_llm and not llm.available:
            context.warn(f"未启用大模型（{llm.degraded_reason or '未配置'}），本次仅使用规则引擎生成用例。")

        cases: list[TestCase] = []
        with Timer() as timer:
            for item in doc.items:
                cases.extend(await self._generate_for_item(item, selected, context))

        unique_cases, duplicates = optimize(cases)

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

        suite = TestCaseSuite(
            suite_id=new_id("SUITE-"),
            doc_id=doc.doc_id,
            doc_title=doc.title,
            methods=resolved,
            cases=unique_cases,
            generation_meta=GenerationMeta(
                methods=[method.value for method in resolved],
                llm_used=llm_case_count > 0,
                llm_provider=llm.name,
                llm_model=llm.model,
                fallback_used=not llm.available,
                warnings=context.warnings,
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
            context.warn(
                f"需求「{item.title}」的用例数 {len(cases)} 超过单条需求上限 {limit}，已截断，请人工复核遗漏场景。"
            )
            cases = cases[:limit]
        return cases
