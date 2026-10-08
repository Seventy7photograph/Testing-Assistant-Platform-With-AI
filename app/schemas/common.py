"""领域枚举与共享小模型。"""
from __future__ import annotations

from enum import Enum


class DesignMethod(str, Enum):
    """测试设计方法。V1.0 实现前三项，其余为 架构预留。"""

    EQUIVALENCE = "equivalence"
    BOUNDARY = "boundary"
    SCENARIO = "scenario"
    # ---- 预留（未实现） ----
    DECISION_TABLE = "decision_table"
    CAUSE_EFFECT = "cause_effect"
    ORTHOGONAL = "orthogonal"

    @property
    def label(self) -> str:
        return _METHOD_LABELS.get(self.value, self.value)


_METHOD_LABELS: dict[str, str] = {
    "equivalence": "等价类划分",
    "boundary": "边界值分析",
    "scenario": "场景法",
    "decision_table": "判定表",
    "cause_effect": "因果图",
    "orthogonal": "正交实验",
}

V1_METHODS: tuple[DesignMethod, ...] = (
    DesignMethod.EQUIVALENCE,
    DesignMethod.BOUNDARY,
    DesignMethod.SCENARIO,
)


class Priority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"

    @property
    def rank(self) -> int:
        return {"P0": 0, "P1": 1, "P2": 2, "P3": 3}[self.value]


class CaseType(str, Enum):
    """用例类型，决定执行优先级与统计口径。"""

    FUNCTIONAL = "功能"
    BOUNDARY = "边界"
    EXCEPTION = "异常"
    SCENARIO = "场景"
    SECURITY = "安全"
    PERFORMANCE = "性能"
    COMPATIBILITY = "兼容性"


class RequirementType(str, Enum):
    FUNCTION = "functional"
    BUSINESS_RULE = "business_rule"
    INTERFACE = "interface"
    CONSTRAINT = "constraint"
    NON_FUNCTIONAL = "non_functional"


class DataType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    ENUM = "enum"
    DATE = "date"
    DATETIME = "datetime"
    OTHER = "other"


class ValueCharset(str, Enum):
    """长度类字段测试数据的字符集语义。

    「11位数字」「6位验证码」这类约束本质是长度约束，字段类型会被归一为
    字符串；若不同时保留字符集语义，数据构造会退化成字母填充，从而产出
    违反字段约束的测试数据（例如把手机号填成 AAAAAAAAAAA）。
    """

    TEXT = "text"
    DIGITS = "digits"


class CaseSource(str, Enum):
    RULE = "rule"
    LLM = "llm"
    HYBRID = "hybrid"