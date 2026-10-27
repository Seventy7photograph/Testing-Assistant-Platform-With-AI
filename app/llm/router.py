"""按任务、成本与质量选择模型。

路由只决定模型名，不改变 Prompt、证据闸门或 Provider 的鉴权边界。
每次决策都返回可解释理由，并随 LLMResponse 写入生成元数据。
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings

_HEAVY_TASKS = {
    "requirement_extraction",
    "generation_review",
    "api_case_review",
    "report_summarization",
    "automation_operation_gap",
    "automation_failure_assertion",
    "automation_script_review",
    "knowledge_answer",
}

_TASK_ALIASES = {
    "requirement.extract": "requirement_extraction",
    "design.generation_review": "generation_review",
    "report.summarize": "report_summarization",
    "api.case_review": "api_case_review",
}


@dataclass(frozen=True, slots=True)
class ModelRouteDecision:
    provider: str
    model: str
    task: str
    strategy: str
    quality_tier: str
    cost_tier: str
    rationale: str

    def as_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model,
            "task": self.task,
            "strategy": self.strategy,
            "quality_tier": self.quality_tier,
            "cost_tier": self.cost_tier,
            "rationale": self.rationale,
        }


def normalize_strategy(raw: str) -> str:
    value = (raw or "balanced").strip().lower()
    return value if value in {"quality", "balanced", "cost"} else "balanced"


def route_model(
    settings: Settings,
    task: str,
    *,
    strategy: str | None = None,
) -> ModelRouteDecision:
    normalized_task = _TASK_ALIASES.get(task, task or "general")
    selected_strategy = normalize_strategy(strategy or settings.llm_routing_strategy)
    provider = (settings.llm_provider or "none").strip().lower()
    configured = (settings.llm_model or "").strip()

    if provider != "deepseek":
        model = configured or ("fake-model" if provider == "fake" else "")
        return ModelRouteDecision(
            provider=provider,
            model=model,
            task=normalized_task,
            strategy=selected_strategy,
            quality_tier="configured",
            cost_tier="configured",
            rationale="非 DeepSeek 端点使用配置模型，避免向未知厂商发送不存在的模型名。",
        )

    heavy = normalized_task in _HEAVY_TASKS
    use_pro = selected_strategy == "quality" or (selected_strategy == "balanced" and heavy)
    if use_pro:
        model = "deepseek-v4-pro"
        quality_tier = "high"
        cost_tier = "high"
        rationale = (
            "质量优先：复杂任务使用深度推理模型。"
            if selected_strategy == "quality"
            else "均衡策略：复杂任务使用深度推理模型，其余任务使用 Flash。"
        )
    else:
        model = "deepseek-flash"
        quality_tier = "standard"
        cost_tier = "low"
        rationale = (
            "成本优先：使用低单价 Flash 模型。"
            if selected_strategy == "cost"
            else "均衡策略：常规任务使用低单价 Flash 模型。"
        )
    return ModelRouteDecision(
        provider=provider,
        model=model,
        task=normalized_task,
        strategy=selected_strategy,
        quality_tier=quality_tier,
        cost_tier=cost_tier,
        rationale=rationale,
    )


def routing_preview(settings: Settings, strategy: str | None = None) -> list[ModelRouteDecision]:
    tasks = [
        "requirement_extraction",
        "scenario_enrichment",
        "generation_review",
        "report_summarization",
        "api_case_review",
        "automation_fixture_recipe",
        "knowledge_answer",
        "general",
    ]
    return [route_model(settings, task, strategy=strategy) for task in tasks]


__all__ = [
    "ModelRouteDecision",
    "normalize_strategy",
    "route_model",
    "routing_preview",
]
