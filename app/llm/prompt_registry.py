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

PROMPT_AUTOMATION_OPERATION_GAP = PromptSpec(
    prompt_id="automation.operation_gap",
    version="2.3.1",
    task="automation_operation_gap",
    input_boundary="未覆盖 operation 的结构摘要与允许引用的 source_ref；不含密钥、完整请求体或执行数据",
    temperature=0.1,
    change_log=(
        "2.3.1 自动化资产受控增强：只建议人工补充的接口测试场景，不生成或改写脚本",
    ),
)

PROMPT_AUTOMATION_FAILURE_ASSERTION = PromptSpec(
    prompt_id="automation.failure_assertion",
    version="2.3.1",
    task="automation_failure_assertion",
    input_boundary="失败执行摘要、已有接口用例断言与允许引用的 source_ref；不含凭据和完整响应体",
    temperature=0.1,
    change_log=(
        "2.3.1 自动化失败归纳：只生成待人工确认的断言提案",
    ),
)

PROMPT_AUTOMATION_FIXTURE_RECIPE = PromptSpec(
    prompt_id="automation.fixture_recipe",
    version="2.3.1",
    task="automation_fixture_recipe",
    input_boundary="接口用例请求结构、环境变量占位符与脱敏后的数据摘要；不得包含真实密钥",
    temperature=0.2,
    change_log=(
        "2.3.1 测试数据配方：输出环境变量、fixture 与测试数据建议，不输出可执行 Python",
    ),
)

PROMPT_AUTOMATION_SCRIPT_REVIEW = PromptSpec(
    prompt_id="automation.script_review",
    version="2.3.1",
    task="automation_script_review",
    input_boundary="受控生成项目的 Python 文件与文件清单；只读审查，不回写资产",
    temperature=0.1,
    change_log=(
        "2.3.1 自动化脚本只读审查：检查可维护性、断言完整性、数据与环境变量风险",
    ),
)

ALL_PROMPTS: tuple[PromptSpec, ...] = (
    PROMPT_REQUIREMENT_EXTRACTION,
    PROMPT_SCENARIO_ENRICHMENT,
    PROMPT_GENERATION_REVIEW,
    PROMPT_REPORT_SUMMARY,
    PROMPT_API_CASE_REVIEW,
    PROMPT_AUTOMATION_OPERATION_GAP,
    PROMPT_AUTOMATION_FAILURE_ASSERTION,
    PROMPT_AUTOMATION_FIXTURE_RECIPE,
    PROMPT_AUTOMATION_SCRIPT_REVIEW,
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
