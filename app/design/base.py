"""设计策略抽象与共享工具。

所有设计方法都实现同一个接口，主干（DesignEngine）不感知具体方法，
这是"插件化设计引擎"的核心。
"""
from __future__ import annotations

import abc
import re
from dataclasses import dataclass, field

from app.core.config import Settings
from app.core.exceptions import FeatureNotAvailableError
from app.llm.base import LLMProvider
from app.schemas.common import CaseSource, CaseType, DesignMethod, Priority, ValueCharset
from app.schemas.requirement import FieldConstraint, RequirementItem
from app.schemas.testcase import ReviewFinding, TestCase, TestStep

#: 生成阶段大模型的参与方式。
#:   scenario —— 只让场景法补充用例（V1.0 起的默认行为）
#:   review   —— 六种方法都覆盖：模型复核规则产出并给出意见（不改写用例）
#:   enhance  —— review + 允许补充用例（带来源标记与上限）
LLM_DESIGN_MODES: tuple[str, ...] = ("scenario", "review", "enhance")
DEFAULT_LLM_DESIGN_MODE = "scenario"


@dataclass
class DesignContext:
    """一次生成任务的共享上下文（依赖注入容器）。"""

    settings: Settings
    llm: LLMProvider
    use_llm: bool = False
    max_cases_per_item: int = 60
    warnings: list[str] = field(default_factory=list)
    llm_call_count: int = 0
    #: 被「单条需求上限」裁剪过的需求。这里只记录事实，告警文案由引擎在
    #: **去重之后**统一生成 —— 只有那时才知道这条需求最终留下多少条用例。
    truncations: list["TruncationRecord"] = field(default_factory=list)
    #: 生成阶段大模型的参与方式（scenario / review / enhance）。
    llm_review_mode: str = DEFAULT_LLM_DESIGN_MODE
    #: 大模型复核产出的意见（只呈现，不自动改写用例）。
    findings: list[ReviewFinding] = field(default_factory=list)
    #: 每条需求允许补充的用例数上限。
    max_llm_cases_per_item: int = 5
    #: 单次生成允许调用大模型的总次数上限（成本护栏）。
    max_llm_calls: int = 20
    #: Prompt / 校验追溯信息，进入 GenerationMeta。
    prompt_runs: list[dict] = field(default_factory=list)
    validation_failures: list[str] = field(default_factory=list)
    unreviewed_requirements: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def note_truncation(self, record: "TruncationRecord") -> None:
        self.truncations.append(record)

    @property
    def llm_ready(self) -> bool:
        return self.use_llm and self.llm.available

    # ------------------------------------------------------------------ #
    @property
    def scenario_llm_enabled(self) -> bool:
        """场景法的 LLM 增强（历史行为，只在 scenario 模式下启用）。"""
        return self.llm_ready and self.llm_review_mode == "scenario"

    @property
    def llm_review_enabled(self) -> bool:
        """统一复核：一次调用覆盖六种方法的产出。"""
        return self.llm_ready and self.llm_review_mode in ("review", "enhance")

    @property
    def llm_extra_cases_enabled(self) -> bool:
        """是否允许模型在复核之外补充用例。"""
        return self.llm_ready and self.llm_review_mode == "enhance"


@dataclass(slots=True)
class TruncationRecord:
    """某条需求超过单条上限、被裁剪时的原始记录（用于生成口径准确的告警）。"""

    requirement_id: str
    requirement_title: str
    raw_count: int
    kept_count: int
    per_method_total: dict[str, int] = field(default_factory=dict)
    per_method_kept: dict[str, int] = field(default_factory=dict)


def bump_priority(priority: Priority, minimum: Priority = Priority.P1) -> Priority:
    """把优先级提升到不低于 minimum（如必填项缺失的异常用例）。"""
    return priority if priority.rank <= minimum.rank else minimum


class DesignStrategy(abc.ABC):
    """测试设计策略基类。"""

    method: DesignMethod
    description: str = ""
    implemented: bool = True

    def __init__(self, context: DesignContext) -> None:
        self.context = context

    # ------------------------------------------------------------------ #
    @property
    def name(self) -> str:
        return self.method.value

    @abc.abstractmethod
    def is_applicable(self, item: RequirementItem) -> bool:
        """该需求条目是否适合本方法（返回 False 时会被引擎跳过）。"""

    @abc.abstractmethod
    async def generate(self, item: RequirementItem) -> list[TestCase]:
        """生成用例；实现方需保证不抛异常（异常会被引擎统一兜底）。"""

    # ------------------------------------------------------------------ #
    # 共享构建工具
    # ------------------------------------------------------------------ #
    def build_case(
        self,
        item: RequirementItem,
        *,
        title: str,
        case_type: CaseType,
        steps: list[TestStep] | None = None,
        expected_result: str,
        test_data: dict[str, str] | None = None,
        priority: Priority | None = None,
        preconditions: list[str] | None = None,
        remarks: str = "",
        tags: list[str] | None = None,
        source: CaseSource = CaseSource.RULE,
    ) -> TestCase:
        return TestCase(
            title=title,
            module=item.module,
            requirement_ids=[item.id],
            design_method=self.method,
            case_type=case_type,
            priority=priority or item.priority,
            preconditions=list(preconditions if preconditions is not None else item.preconditions),
            steps=steps or [],
            expected_result=expected_result,
            test_data=test_data or {},
            tags=[self.method.label, *(tags or [])],
            remarks=remarks,
            source=source,
        )

    def too_many(self, cases: list[TestCase]) -> list[TestCase]:
        """按 max_cases_per_item 截断，并记录告警（防止边界值组合爆炸）。"""
        limit = self.context.max_cases_per_item
        if len(cases) <= limit:
            return cases
        self.context.warn(
            f"「{self.method.label}」单方法产出 {len(cases)} 条，超过单方法上限 {limit}，已截断保留 {limit} 条；"
            "跨方法合计后还会再去重合并，最终条数以结果为准，请人工复核遗漏场景。"
        )
        return cases[:limit]


class NotImplementedStrategy(DesignStrategy):
    """尚未实现的设计方法的统一占位实现。

    显式注册占位类而不是"什么都不写"，好处是：
      - /methods 接口能列出能力清单与实现状态（implemented=False）；
      - 调用时返回 501 + 清晰提示，而不是 404 让人误以为参数写错。
    """

    description = "该设计方法尚未实现，当前版本不提供。"
    implemented = False

    def is_applicable(self, item: RequirementItem) -> bool:  # pragma: no cover - 占位
        return False

    async def generate(self, item: RequirementItem) -> list[TestCase]:  # pragma: no cover - 占位
        raise FeatureNotAvailableError(
            f"「{self.method.label}」当前版本尚未实现；可选的方法为 等价类划分 / 边界值分析 / 场景法。",
            detail={"method": self.method.value, "implemented": self.implemented},
        )


# --------------------------------------------------------------------------- #
# 通用小工具
# --------------------------------------------------------------------------- #

def field_constraint_text(field: FieldConstraint) -> str:
    text = field.describe_constraint()
    return text or "无显式约束"


def make_single_step(action: str, expected: str = "") -> list[TestStep]:
    return [TestStep(no=1, action=action, expected=expected)]


def format_number(value: float) -> str:
    """数值格式化：整数不带小数点（1.0 -> "1"），便于拼装测试数据。"""
    return str(int(value)) if float(value).is_integer() else str(value)


ALPHA_FILLER = "A"
DIGIT_FILLER = "1"

# 内置正则 -> 符合该格式的样例值，避免「有效等价类」数据本身违反格式约束。
PATTERN_SAMPLES: dict[str, str] = {
    r"^[\w.+-]+@[\w-]+\.[\w.]+$": "tester@example.com",
    r"^1[3-9]\d{9}$": "13800138000",
    r"^\d{17}[\dXx]$": "11010119900307123X",
    r"^\d{6}$": "100000",
    r"^\d{11}$": "13800138000",
    r"^\d{12}$": "202601011200",
    r"^\d{4}$": "1000",
    r"^https?://.+$": "https://example.com",
    r"^\d+(\.\d{1,2})?$": "100.00",
}

# 匹配「只接受数字」的正则（如 ^\d{11}$、^\d{6}$）：去掉 \d、量词与锚点/分组符号后，
# 若不再残留任何字面字符，则说明该正则只接受数字。用于在没有内置样例时仍按数字填充。
_DIGIT_ONLY_QUANTIFIER_RE = re.compile(r"\{\d+(?:,\d*)?\}")
_DIGIT_ONLY_SYMBOL_RE = re.compile(r"[\^$()\[\]\+\-\*\?\\|:{}]")


def pattern_is_digit_only(pattern: str | None) -> bool:
    """判断正则是否「只接受数字」；供数据构造选择数字字符集。"""
    if not pattern:
        return False
    stripped = pattern.replace(r"\d", "")
    stripped = _DIGIT_ONLY_QUANTIFIER_RE.sub("", stripped)
    stripped = _DIGIT_ONLY_SYMBOL_RE.sub("", stripped)
    return stripped == ""


def fill_value(length: int, charset: ValueCharset | str = ValueCharset.TEXT) -> str:
    """构造指定长度的字符串测试数据。

    :param charset: digits -> 用数字填充（「11位数字」「6位验证码」等数字串字段）；
                    其余按字母填充（普通文本字段）。

    数字串字段若用字母填充，会产生"测试数据本身违反字段约束"的假缺陷，
    因此字符集由调用方按字段语义显式传入（负数/0 长度由调用方处理）。
    """
    is_digits = charset == ValueCharset.DIGITS or charset == ValueCharset.DIGITS.value
    filler = DIGIT_FILLER if is_digits else ALPHA_FILLER
    return filler * max(int(length), 0)


def pattern_sample(pattern: str | None) -> str | None:
    """返回与内置正则匹配的样例值；无内置样例时返回 None。"""
    if not pattern:
        return None
    return PATTERN_SAMPLES.get(pattern)


def length_sample(field: FieldConstraint, length: int) -> str:
    """构造长度恰好为 ``length`` 的代表值：等长且符合格式时用内置样例，否则按字符集填充。

    必须要求样例长度与目标长度严格相等：边界值需要「长度10 / 11 / 12」三种不同取值，
    否则 11 位的固定样例会让所有长度点塌缩成同一个值，边界用例退化为一条。
    没有内置样例但正则只接受数字时（如 LLM 抽取出的 ``^\\d{11}$``），
    按数字填充，避免把手机号这类字段填成字母而产出"有效却非法"的数据。
    """
    sample = pattern_sample(field.pattern)
    if sample and len(sample) == length and _fits_length(field, length):
        return sample
    charset = ValueCharset.DIGITS if pattern_is_digit_only(field.pattern) else field.data_charset
    return fill_value(length, charset)


def _fits_length(field: FieldConstraint, size: int) -> bool:
    if field.min_length is not None and size < field.min_length:
        return False
    if field.max_length is not None and size > field.max_length:
        return False
    return True
