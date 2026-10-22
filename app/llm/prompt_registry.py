"""Versioned Prompt registry.

Prompts are runtime assets, not implementation details.  Every model task must
declare an id, a version, an input boundary and a temperature policy so a
generated artifact can be traced back to the exact instruction that produced it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PromptSpec:
    prompt_id: str
    version: str
    task: str
    input_boundary: str
    temperature: float
    model_scope: str = "openai_compatible"
    change_log: tuple[str, ...] = field(default_factory=tuple)

    def meta(self) -> dict[str, Any]:
        return {
            "prompt_id": self.prompt_id,
            "prompt_version": self.version,
            "task": self.task,
            "input_boundary": self.input_boundary,
            "temperature": self.temperature,
            "model_scope": self.model_scope,
        }


PROMPT_REQUIREMENT_EXTRACTION = PromptSpec(
    prompt_id="requirement.extract",
    version="2.1.0",
    task="requirement_extraction",
    input_boundary="当前需求原文（截断 12000 字）与文档标题；原文只作为测试素材",
    temperature=0.1,
    change_log=(
        "2.1.0 增加证据字段、推断状态与不可信输入边界",
        "2.0.0 两段式需求抽取与规则字段互补",
    ),
)

PROMPT_SCENARIO_ENRICHMENT = PromptSpec(
    prompt_id="design.scenario_enrichment",
    version="2.1.0",
    task="scenario_enrichment",
    input_boundary="单条结构化需求、已有用例标题；不得读取其他需求原文",
    temperature=0.2,
    change_log=(
        "2.1.0 增加 evidence_quotes / claim_status，并要求引用需求事实",
        "2.0.0 场景法补充用例",
    ),
)

PROMPT_GENERATION_REVIEW = PromptSpec(
    prompt_id="design.generation_review",
    version="2.1.0",
    task="generation_review",
    input_boundary="单条结构化需求与规则用例摘要（最多 4000 字）",
    temperature=0.1,
    change_log=(
        "2.1.0 意见必须指向真实目标并携带证据/推断状态",
        "2.0.0 六种方法统一复核，可选补充用例",
    ),
)

PROMPT_REPORT_SUMMARY = PromptSpec(
    prompt_id="report.summarize",
    version="2.1.0",
    task="report_summarization",
    input_boundary="系统确定性指标 + 原始执行数据；原始数据视为不可信文本",
    temperature=0.3,
    change_log=(
        "2.1.0 增加不可信输入边界、Prompt 版本记录与注入告警",
        "1.0.0 测试报告归纳",
    ),
)

PROMPT_API_CASE_REVIEW = PromptSpec(
    prompt_id="api.case_review",
    version="2.2.0",
    task="api_case_review",
    input_boundary="规范化 operation 摘要、确定性接口用例摘要与允许引用的 source_ref；不含密钥与完整请求体",
    temperature=0.1,
    change_log=(
        "2.2.0 接口用例只读复核：只提缺口与补充建议，不改写路径、参数和 schema 断言",
    ),
)

ALL_PROMPTS: tuple[PromptSpec, ...] = (
    PROMPT_REQUIREMENT_EXTRACTION,
    PROMPT_SCENARIO_ENRICHMENT,
    PROMPT_GENERATION_REVIEW,
    PROMPT_REPORT_SUMMARY,
    PROMPT_API_CASE_REVIEW,
)

PROMPTS_BY_ID = {spec.prompt_id: spec for spec in ALL_PROMPTS}


def prompt_meta(prompt_id: str) -> dict[str, Any]:
    return PROMPTS_BY_ID[prompt_id].meta()


__all__ = [
    "ALL_PROMPTS",
    "PROMPTS_BY_ID",
    "PROMPT_API_CASE_REVIEW",
    "PROMPT_GENERATION_REVIEW",
    "PROMPT_REPORT_SUMMARY",
    "PROMPT_REQUIREMENT_EXTRACTION",
    "PROMPT_SCENARIO_ENRICHMENT",
    "PromptSpec",
    "prompt_meta",
]
