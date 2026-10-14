"""Prompt 模板集中管理。

设计要点（对应「需求解析 / 用例生成拆成两次调用」的工程建议）：
  - 每次 LLM 调用只做一件事，Prompt 结构稳定，便于回归；
  - Prompt 中带机器可读的 [TASK:xxx] 标记，FakeProvider 与日志据此路由；
  - 明确要求「不编造原文没有的信息」，降低幻觉污染。
"""
from __future__ import annotations

from typing import Any

from app.core.utils import dump_json, truncate
from app.llm.base import LLMMessage, system, user

TASK_REQUIREMENT_EXTRACTION = "[TASK:REQUIREMENT_EXTRACTION]"
TASK_SCENARIO_ENRICHMENT = "[TASK:SCENARIO_ENRICHMENT]"
TASK_GENERATION_REVIEW = "[TASK:GENERATION_REVIEW]"

REQUIREMENT_SYSTEM_PROMPT = f"""你是资深测试架构师，擅长把非结构化需求文档拆解为结构化需求模型，供后续自动化生成测试用例。

{TASK_REQUIREMENT_EXTRACTION}

输出要求：
- 只输出一个 JSON 对象，不要 Markdown 代码块，不要任何解释性文字。
- JSON 顶层结构必须为：
{{
  "title": "文档标题",
  "summary": "一句话概述该文档测试重点",
  "items": [
    {{
      "id": "REQ-001",
      "title": "需求条目名称",
      "module": "所属模块",
      "description": "需求描述",
      "priority": "P0/P1/P2/P3 之一",
      "requirement_type": "functional|business_rule|interface|constraint|non_functional 之一",
      "fields": [
        {{
          "name": "字段名",
          "label": "字段中文名",
          "data_type": "string|integer|float|boolean|enum|date|datetime|other 之一",
          "required": true,
          "nullable": false,
          "min_value": null,
          "max_value": null,
          "min_length": null,
          "max_length": null,
          "enum_values": [],
          "pattern": null,
          "default": null,
          "unit": null,
          "description": "字段说明与约束"
        }}
      ],
      "business_rules": ["业务规则"],
      "preconditions": ["前置条件"],
      "main_flow": ["主流程步骤"],
      "alternative_flows": ["备选/分支流程"],
      "exceptions": ["异常场景"],
      "acceptance_criteria": ["验收标准"],
      "source_ref": "原文中的章节或位置"
    }}
  ]
}}

拆解规则：
1. 最多输出 {{max_items}} 条 items，按业务重要性排序，一条需求对应一个可独立测试的功能点或业务规则。
2. 数值范围（如 1~100、不超过 500）必须落到 min_value/max_value；
   长度限制（如 6-20 位、「11位数字」）落到 min_length/max_length；
   枚举取值（如 状态：待支付/已支付/已取消）落到 enum_values。
3. pattern 只允许填写真正的正则表达式（如 ^\\d{{11}}$、^1[3-9]\\d{{9}}$）；禁止把
   「11位数字」「8位」这类自然语言描述写进 pattern，无法确定正则时填 null。
4. 只有原文出现的信息才可写入，缺失信息用 null 或空数组，禁止编造。
5. main_flow 与 alternative_flows 尽量拆成单步动词短语，便于生成场景用例。
"""

SCENARIO_SYSTEM_PROMPT = f"""你是资深测试架构师，请针对给定需求条目补充「场景法」测试用例，重点覆盖易漏的异常、分支与组合场景。

{TASK_SCENARIO_ENRICHMENT}

输出要求：
- 只输出一个 JSON 对象（不要 Markdown 代码块），结构为：
{{
  "cases": [
    {{
      "title": "用例标题",
      "case_type": "功能|边界|异常|场景 之一",
      "priority": "P0|P1|P2|P3 之一",
      "preconditions": ["前置条件"],
      "steps": [{{"action": "操作步骤", "expected": "该步预期"}}],
      "expected_result": "整体预期结果",
      "test_data": {{"字段名": "测试数据"}}
    }}
  ]
}}
- 最多 {{max_cases}} 条；不要与「已有用例」重复；不要输出与需求无关的场景。
"""


def build_requirement_messages(text: str, *, title: str, max_items: int = 8) -> list[LLMMessage]:
    """构造「需求解析」调用消息。"""
    body = truncate(text, 12000)
    return [
        system(REQUIREMENT_SYSTEM_PROMPT.replace("{max_items}", str(max_items))),
        user(f"文档标题：{title}\n\n需求原文如下（可能包含表格与列表）：\n\n{body}\n\n请输出结构化 JSON。"),
    ]


def build_scenario_messages(
    item_payload: dict[str, Any],
    *,
    existing_titles: list[str] | None = None,
    max_cases: int = 6,
) -> list[LLMMessage]:
    """构造「场景用例补充」调用消息。"""
    existing = existing_titles or []
    existing_text = "\n".join(f"- {title}" for title in existing[:30]) or "（无）"
    return [
        system(SCENARIO_SYSTEM_PROMPT.replace("{max_cases}", str(max_cases))),
        user(
            "需求条目（JSON）：\n"
            + dump_json(item_payload, indent=None)
            + "\n\n已有用例标题：\n"
            + existing_text
            + "\n\n请输出补充的场景用例 JSON。"
        ),
    ]


# --------------------------------------------------------------------------- #
# 生成阶段复核：让模型检查「规则引擎产出的用例」，并指出遗漏
# --------------------------------------------------------------------------- #
# 为什么不让模型直接生成用例：规则引擎的产出是确定、可复现、可离线核对的，
# 这是本项目的立身之本。模型的价值在**规则天生做不好的地方** ——
# 判断"这套字段约束背后真实的业务语义有没有漏"、"数据与约束是否自相矛盾"、
# "预期结果和业务规则是否打架"。因此这里产出的是**意见 + 可选补充**，
# 而不是重写规则结果。
# 注意：这里刻意用普通字符串拼接而不是 f-string —— 模板里既有 JSON 的花括号、
# 又有运行时才填的占位符，f-string 会把两边都当成表达式，既需要转义又容易写错。
GENERATION_REVIEW_SYSTEM_PROMPT = (
    "你是资深测试架构师，负责复核「规则引擎按测试设计方法产出的用例」，并指出遗漏。\n\n"
    + TASK_GENERATION_REVIEW
    + "\n\n你收到的输入：一条需求条目（含字段约束、业务规则、流程、验收标准）"
    "+ 规则引擎基于已选设计方法产出的用例清单。\n\n"
    "请做三件事：\n"
    "1. **复核已有用例**：数据与字段约束是否矛盾、预期结果与业务规则是否冲突、"
    "同一需求内部是否自相矛盾、是否存在明显重复；\n"
    "2. **指出遗漏**：规则方法覆盖不到、但真实业务里一定会发生的测试点"
    "（并发、权限、幂等、状态时序、脏数据、历史数据等）；\n"
    "3. **补充用例**：{case_instruction}\n\n"
    "输出要求（只输出一个 JSON 对象，不要 Markdown 代码块、不要解释文字）：\n"
    "{\n"
    '  "findings": [\n'
    '    {"severity": "info 或 warning", "target": "用例标题 / 字段名 / 需求条目",'
    ' "issue": "问题是什么", "suggestion": "建议怎么改"}\n'
    "  ],\n"
    '  "cases": [\n'
    "    {\n"
    '      "title": "用例标题",\n'
    '      "method": "{method_hint}",\n'
    '      "case_type": "功能|边界|异常|场景 之一",\n'
    '      "priority": "P0|P1|P2|P3 之一",\n'
    '      "preconditions": ["前置条件"],\n'
    '      "steps": [{"action": "操作步骤", "expected": "该步预期"}],\n'
    '      "expected_result": "整体预期结果",\n'
    '      "test_data": {"字段名": "测试数据"},\n'
    '      "reason": "为什么需要这条（指向具体的业务规则或流程）"\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "严格约束：\n"
    "- `test_data` 的键**只能**使用需求条目里出现过的字段名；没有对应字段就不要给 test_data；\n"
    "- 不要与「已有用例」重复：判断依据是测试点（目标条件 + 数据），标题不同但测试点相同仍算重复；\n"
    "- 每条补充用例都必须在 `reason` 里说明它覆盖了哪条业务规则或流程，"
    "**不要编造需求里没有的信息**；\n"
    "- findings 最多 6 条，只写真正值得改的；没有问题就返回空数组，不要为了凑数而提意见。\n"
)


def build_review_messages(
    item_payload: dict[str, Any],
    *,
    case_titles: list[str],
    case_digest: str,
    methods: list[str],
    allow_cases: bool,
    max_cases: int = 5,
) -> list[LLMMessage]:
    """构造「生成阶段复核」调用消息。

    ``allow_cases=False``（review 模式）时明确要求只给意见、不给用例，
    既省输出 token，也避免使用者误以为补充用例已经在用。
    """
    method_hint = "|".join(methods) or "scenario"
    case_instruction = (
        f"在意见之外，另外给出最多 {max_cases} 条补充用例（不要与已有用例重复）"
        if allow_cases
        else "**本次不需要补充用例，cases 请返回空数组**"
    )
    prompt = (
        GENERATION_REVIEW_SYSTEM_PROMPT.replace("{case_instruction}", case_instruction).replace(
            "{method_hint}", method_hint
        )
    )
    existing = "\n".join(f"- {title}" for title in case_titles[:60]) or "（规则引擎本次没有产出用例）"
    return [
        system(prompt),
        user(
            "需求条目（JSON）：\n"
            + dump_json(item_payload, indent=None)
            + "\n\n规则引擎产出的用例（标题 / 数据 / 预期 / 方法）：\n"
            + (case_digest or "（无）")
            + "\n\n已有用例标题：\n"
            + existing
            + "\n\n请输出复核 JSON。"
        ),
    ]
