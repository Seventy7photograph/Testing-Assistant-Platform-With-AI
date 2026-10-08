"""设计策略注册表：插件式设计引擎的装配点。"""
from __future__ import annotations

from app.core.registry import Registry
from app.design.base import DesignContext, DesignStrategy
from app.design.boundary import BoundaryStrategy
from app.design.equivalence import EquivalenceStrategy
from app.design.scenario import ScenarioStrategy
from app.design.planned_strategies import (
    CauseEffectStrategy,
    DecisionTableStrategy,
    OrthogonalStrategy,
)

STRATEGY_REGISTRY: Registry[type[DesignStrategy]] = Registry("设计策略")


def register_strategy(strategy_cls: type[DesignStrategy], *, override: bool = False) -> type[DesignStrategy]:
    return STRATEGY_REGISTRY.register(
        strategy_cls.method.value,
        strategy_cls,
        meta={"label": strategy_cls.method.label, "implemented": strategy_cls.implemented},
        override=override,
    )


for _cls in (
    EquivalenceStrategy,
    BoundaryStrategy,
    ScenarioStrategy,
    DecisionTableStrategy,
    CauseEffectStrategy,
    OrthogonalStrategy,
):
    register_strategy(_cls)


def available_methods() -> list[dict]:
    """能力清单（供 /methods 与健康检查使用）。"""
    return [
        {
            "name": name,
            "label": strategy_cls.method.label,
            "implemented": strategy_cls.implemented,
            "description": strategy_cls.description,
        }
        for name, strategy_cls in STRATEGY_REGISTRY.items()
    ]


def build_strategies(context: DesignContext) -> dict[str, DesignStrategy]:
    """按上下文实例化全部策略（依赖注入）。"""
    return {name: strategy_cls(context) for name, strategy_cls in STRATEGY_REGISTRY.items()}
