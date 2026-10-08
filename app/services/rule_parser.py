"""规则化的需求文档解析器（无 LLM 也能工作的确定性兜底链路）。

能力：
  1. 章节切分：Markdown 标题 / 数字编号标题 / 加粗标题 / 空行分段；
  2. 字段表格解析：把需求文档里的「字段说明表」转成 FieldConstraint
     （识别 字段名 / 类型 / 必填 / 取值范围 / 默认值 / 说明 等列）；
  3. 行内约束抽取：11 位、6-20 位、1~100、不超过 500、待支付/已支付 等；
  4. 流程与规则分类：主流程 / 备选流程 / 异常场景 / 业务规则 / 前置条件 / 验收标准。

明确假设：结构化程度越低，规则解析准确率越低；此时建议启用 LLM 解析
（LLM_PROVIDER=deepseek 且配置 LLM_API_KEY），或在 Prompt 层面把文档
整理成 Markdown 标题 + 表格的形式。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from collections.abc import Callable

from app.core.utils import normalize_whitespace, truncate
from app.schemas.common import DataType, Priority, RequirementType, ValueCharset
from app.schemas.requirement import FieldConstraint, RequirementItem

# --------------------------------------------------------------------------- #
# 正则
# --------------------------------------------------------------------------- #
HASH_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s*(?P<title>.+?)\s*$")
NUMBERED_HEADING_RE = re.compile(r"^(?P<num>\d+(?:\.\d+)*)\s*[、.．)）]\s*(?P<title>\S.*)$")
BOLD_HEADING_RE = re.compile(r"^\*\*(?P<title>[^*]{2,40})\*\*\s*[:：]?\s*$")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*•]|\(?\d+[)）.、]|[（(]\d+[）)]|[一二三四五六七八九十]+[、.])\s*(?P<text>.+?)\s*$")
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
TAB_SEP_RE = re.compile(r"\t+")

RANGE_RE = re.compile(r"(?P<min>\d+(?:\.\d+)?)\s*(?:~|～|-|—|–|到|至)\s*(?P<max>\d+(?:\.\d+)?)")
LEN_RANGE_RE = re.compile(r"(?P<min>\d+)\s*(?:~|～|-|—|–|到|至)\s*(?P<max>\d+)\s*(?:位|个字符|字符|个)")
# 「长度 2~20」「字符数 2-20」这类范围没有"位/字符"后缀，需单独识别，
# 否则会被 RANGE_RE 先命中，误判成"可比较大小"的数值区间（如把昵称长度当成 2~20 的数值）。
LEN_PREFIX_RANGE_RE = re.compile(
    r"(?:长度|字符数|字数|位数)\s*(?:为|是|:|：)?\s*(?P<min>\d+)\s*(?:~|～|-|—|–|到|至)\s*(?P<max>\d+)"
)
MAX_LEN_RE = re.compile(r"(?:不超过|最多|最大长度|长度不超过|上限为?|≤|<=|小于等于)\s*(?P<value>\d+)")
MIN_LEN_RE = re.compile(r"(?:不少于|至少|最少|最小长度|长度不少于|下限为?|≥|>=|大于等于)\s*(?P<value>\d+)")
EXACT_LEN_RE = re.compile(r"(?P<value>\d+)\s*(?:位|个字符|字符)")
PATTERN_HINTS: tuple[tuple[str, str], ...] = (
    ("邮箱", r"^[\w.+-]+@[\w-]+\.[\w.]+$"),
    ("手机", r"^1[3-9]\d{9}$"),
    ("身份证", r"^\d{17}[\dXx]$"),
    ("邮编", r"^\d{6}$"),
    ("网址", r"^https?://.+$"),
    ("金额", r"^\d+(\.\d{1,2})?$"),
)

SECTION_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("main_flow", ("主流程", "正常流程", "基本流程", "基本流", "操作步骤", "业务流程")),
    ("alternative_flows", ("备选流程", "备选流", "分支流程", "分支流", "替代流程", "其他流程", "可替代流程")),
    ("exceptions", ("异常场景", "异常流程", "异常情况", "失败场景", "错误处理")),
    ("preconditions", ("前置条件", "前提条件", "前置要求", "准备条件")),
    ("acceptance_criteria", ("验收标准", "验收条件", "预期结果", "期望结果", "测试要点")),
    ("business_rules", ("业务规则", "校验规则", "规则说明", "约束条件", "限制条件")),
)
RULE_INLINE_RE = re.compile(r"(?:^|[，,。；;\s])(?:若|如果|当|如遇).{0,40}?(?:则|就|应|需)")
PROHIBITION_RE = re.compile(r"(?:禁止|不允许|不得|不能|不可|必须|应当|需要)")

TABLE_NAME_KEYS = ("字段名", "字段名称", "字段", "参数名", "参数", "名称", "属性", "项目")
TABLE_TYPE_KEYS = ("类型", "数据类型", "格式", "字段类型")
TABLE_REQUIRED_KEYS = ("必填", "是否必填", "必输", "是否必输", "是否必选", "是否必填项")
TABLE_RANGE_KEYS = ("取值范围", "范围", "长度", "约束", "限制", "取值", "允许值", "校验规则")
TABLE_DEFAULT_KEYS = ("默认值", "缺省值", "默认")
TABLE_DESC_KEYS = ("说明", "描述", "备注", "含义", "备注说明")
# 任意一列命中即认为该行是表头（用于识别 Tab 分隔表格）
TABLE_HEADER_KEYS = (
    *TABLE_NAME_KEYS,
    *TABLE_TYPE_KEYS,
    *TABLE_REQUIRED_KEYS,
    *TABLE_RANGE_KEYS,
    *TABLE_DEFAULT_KEYS,
    *TABLE_DESC_KEYS,
)

TRUE_WORDS = {"是", "y", "yes", "true", "1", "必填", "必输", "必选", "需要", "支持"}
NUMBER_HINTS = ("数字", "数值", "整数", "整型", "数量", "次数", "个数", "年龄", "金额", "价格", "比例")
# 命中这些词说明字段是「数字串」（长度约束优先），数据构造必须用数字填充。
DIGIT_CHARSET_HINTS = ("数字", "阿拉伯数字", "纯数字", "号码")
# 这些内置正则本身只接受数字，等价于数字串语义。
DIGIT_ONLY_PATTERNS = (r"^1[3-9]\d{9}$", r"^\d{17}[\dXx]$", r"^\d{6}$")
INTEGER_HINTS = ("整数", "整型", "次数", "个数", "数量", "人数", "台数")
FLOAT_HINTS = ("小数", "金额", "价格", "比例", "费率", "税率", "重量")
BOOLEAN_HINTS = ("是否", "布尔", "开关", "标志", "true", "false")
DATE_HINTS = ("日期", "时间", "date", "time")
ENUM_SEPARATOR_RE = re.compile(r"[、,，/／|]")
# 出现这些词的片段属于「约束描述」而非「枚举取值」，如「11位数字，必填」
ENUM_STOPWORDS: tuple[str, ...] = (
    "必填", "必输", "必选", "选填", "可选", "非必填", "不能为空", "不可为空",
    "数字", "字符", "字节", "长度", "范围", "默认", "位", "≤", "≥", "<", ">", "=",
)
ENUM_STOPWORDS_HIT = re.compile("|".join(re.escape(word) for word in ENUM_STOPWORDS))
PRIORITY_HINTS: tuple[tuple[Priority, tuple[str, ...]], ...] = (
    (Priority.P0, ("p0", "致命", "最高", "核心", "紧急")),
    (Priority.P1, ("p1", "高", "重要")),
    (Priority.P3, ("p3", "低", "次要")),
)


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class Section:
    """一个章节（标题 + 正文行）。"""

    title: str
    level: int
    lines: list[str] = field(default_factory=list)
    module: str = "默认模块"


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #
def parse_requirements(
    text: str,
    *,
    doc_title: str = "",
    max_items: int = 20,
) -> tuple[str, str, list[RequirementItem], list[str]]:
    """把需求文本解析为条目列表。

    :return: (文档标题, 概述, 需求条目列表, 告警列表)
    """
    warnings: list[str] = []
    normalized = normalize_whitespace(text)
    if not normalized:
        return doc_title or "空文档", "", [], ["文档内容为空，未能解析出任何需求。"]

    sections = split_sections(normalized)
    sections = drop_container_sections(sections)
    _reassign_doc_title_modules(sections)
    items: list[RequirementItem] = []
    for section in sections[:max_items]:
        item = build_item(section, sequence=len(items) + 1)
        if item:
            items.append(item)

    if len(sections) > max_items:
        warnings.append(f"文档解析出 {len(sections)} 个章节，已按上限保留前 {max_items} 个。")

    if not items:
        fallback = fallback_item(normalized, doc_title)
        items = [fallback]
        warnings.append("未识别出明确的章节结构，已把整篇文档作为单条需求处理，建议人工拆分或改用 LLM 解析。")

    if not any(item.fields for item in items) and any(
        looks_like_tab_header(line) for line in normalized.split("\n")
    ):
        warnings.append(
            "检测到疑似 Tab 分隔的表格（常见于从 Word/网页直接复制粘贴），但未解析出任何字段约束；"
            "建议改用 .docx 文件上传，或把表格整理成 Markdown 表格（| 列名 | 列名 |）。"
        )

    summary = build_summary(doc_title, items, normalized)
    return (doc_title or infer_doc_title(sections, normalized), summary, items, warnings)


def split_sections(text: str) -> list[Section]:
    """按标题层级切分章节。

    关键设计：先判定文档使用的主标题风格（# 标题 / 加粗标题 / 点分编号 / 纯编号），
    全程只采用该风格切分，避免把正文里的编号步骤（如「1. 输入手机号」）误判成章节。
    文档完全没有标题时，退化为「按空行分段 + 短首行作标题」。
    """
    lines = text.split("\n")
    style = detect_heading_style(lines)
    if style == "none":
        return paragraph_sections(text)

    sections: list[Section] = []
    current: Section | None = None
    current_module = "默认模块"
    pending: list[str] = []
    heading_count = 0

    for raw_line in lines:
        heading = match_heading(raw_line.rstrip(), style)
        if heading:
            heading_count += 1
            title, level = heading
            if current is not None:
                current.lines = pending
                pending = []
            if level <= 1:
                current_module = title
            module = current_module if level > 1 else title
            if module == "默认模块":
                # 没有任何一级标题时（如整篇都用 ## 或加粗标题），子章节自己就是
                # 模块归属；否则所有用例的「所属模块」都会退化成「默认模块」。
                module = title
            current = Section(title=title, level=level, module=module)
            sections.append(current)
            continue
        pending.append(raw_line.rstrip())

    if current is not None:
        current.lines = pending

    sections = [section for section in sections if any(line.strip() for line in section.lines)]
    if heading_count == 0 or not sections:
        return paragraph_sections(text)
    return sections


def detect_heading_style(lines: list[str]) -> str:
    """判定文档的主标题风格，保证同一种编号不会既当标题又当步骤。"""
    stripped = [line.strip() for line in lines]
    if any(HASH_HEADING_RE.match(line) for line in stripped):
        return "marked"
    if any(BOLD_HEADING_RE.match(line) for line in stripped):
        return "marked"

    has_dotted = False
    has_plain = False
    for line in stripped:
        match = NUMBERED_HEADING_RE.match(line)
        if not match:
            continue
        if "." in match.group("num"):
            has_dotted = True
        else:
            has_plain = True
    if has_dotted:
        return "dotted"
    if has_plain:
        return "numbered"
    return "none"


def drop_container_sections(sections: list[Section]) -> list[Section]:
    """剔除「仅作模块容器」的一级标题。

    例如「# 电商订单系统需求说明书」下面全是「## xxx」子章节时，
    一级标题只是文档/模块名，不应被当成一条需求（否则会产出无字段的噪声用例）。
    若文档只有这一级标题、没有子章节，则保留为需求条目。
    """
    result: list[Section] = []
    for index, section in enumerate(sections):
        has_child = index + 1 < len(sections) and sections[index + 1].level > section.level
        if section.level <= 1 and has_child:
            continue
        result.append(section)
    return result or sections


def _reassign_doc_title_modules(sections: list[Section]) -> None:
    """把「容器型一级标题」遗留的模块名改写为各自章节标题。

    典型场景：``# 某某系统需求说明书`` 下面全是 ``## 用户注册`` 子章节。
    容器标题通常没有正文，会在 :func:`split_sections` 阶段被丢弃，
    但仍以 ``module`` 的形式留在了子章节上，导致所有用例的「所属模块」
    退化成同一个文档名。
    判定条件：全部章节共享同一个模块名，且该名字不是任何一个章节的标题
    —— 这只可能来自被丢弃的容器标题。若存在多个一级标题（如 ``# 用户模块`` /
    ``# 订单模块``），它们本身就是模块名、彼此不同，不会被改写。
    """
    modules = {section.module for section in sections}
    if len(modules) != 1:
        return
    shared = next(iter(modules))
    if shared == "默认模块" or any(section.title == shared for section in sections):
        return
    for section in sections:
        section.module = section.title


def paragraph_sections(text: str) -> list[Section]:
    """无标题时的兜底：按空行分段，并尝试用短首行作为标题。"""
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    sections: list[Section] = []
    for index, block in enumerate(blocks, start=1):
        lines = [line for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        first = lines[0].strip()
        if len(first) <= 30 and not first.endswith(("。", ".", "；", ";")) and len(lines) > 1:
            sections.append(Section(title=clean_title(first), level=2, lines=lines[1:]))
        else:
            sections.append(Section(title=f"需求片段 {index}", level=2, lines=lines))
    return sections


def match_heading(line: str, style: str = "marked") -> tuple[str, int] | None:
    """按已判定的标题风格识别标题行，返回 (标题, 层级)。"""
    text = line.strip()
    if not text:
        return None
    hashed = HASH_HEADING_RE.match(text)
    if hashed:
        return clean_title(hashed.group("title")), len(hashed.group("hashes"))
    if style == "marked":
        bold = BOLD_HEADING_RE.match(text)
        if bold:
            return clean_title(bold.group("title")), 2
        return None

    numbered = NUMBERED_HEADING_RE.match(text)
    if not numbered:
        return None
    num = numbered.group("num")
    if style == "dotted" and "." in num:
        return clean_title(numbered.group("title")), 2 + num.count(".")
    if style == "numbered" and len(text) <= 25 and not text.endswith(("。", ".", "；", ";")):
        return clean_title(numbered.group("title")), 2
    return None


def clean_title(title: str) -> str:
    cleaned = re.sub(r"^[#*\s]+|[*\s]+$", "", title or "")
    cleaned = re.sub(r"^\d+(?:\.\d+)*\s*[、.．)）]?\s*", "", cleaned)
    return cleaned.strip() or "未命名章节"


# --------------------------------------------------------------------------- #
# 单章节 -> 需求条目
# --------------------------------------------------------------------------- #
def build_item(section: Section, *, sequence: int) -> RequirementItem | None:
    body_lines = [line for line in section.lines if line.strip()]
    table_fields, remaining = extract_tables(body_lines, section.title)

    buckets: dict[str, list[str]] = {
        "main_flow": [],
        "alternative_flows": [],
        "exceptions": [],
        "preconditions": [],
        "acceptance_criteria": [],
        "business_rules": [],
    }
    description_lines: list[str] = []
    target: str | None = None

    for line in remaining:
        stripped = line.strip()
        if not stripped:
            continue
        section_key = match_section_keyword(stripped)
        if section_key:
            target = section_key
            inline = strip_section_keyword(stripped)
            if inline:
                buckets[section_key].append(inline)
            continue
        item_text = strip_list_marker(stripped)
        if target and item_text:
            buckets[target].append(item_text)
            continue
        if RULE_INLINE_RE.search(stripped) or PROHIBITION_RE.search(stripped):
            buckets["business_rules"].append(item_text)
            continue
        description_lines.append(item_text)

    inline_fields = extract_inline_fields(remaining, section.title)
    fields = merge_fields(table_fields, inline_fields)

    description = "\n".join(line for line in description_lines if line).strip()
    if not description and not fields and not any(buckets.values()):
        return None

    priority = infer_priority(f"{section.title}\n{description}")
    if priority is Priority.P2 and (buckets["exceptions"] or buckets["business_rules"]):
        # 没有显式优先级提示，但包含异常场景/业务规则时，默认提升为 P1，
        # 避免规则解析产出的用例几乎全部堆在 P2。
        priority = Priority.P1

    return RequirementItem(
        id=f"REQ-{sequence:03d}",
        title=section.title,
        module=section.module or "默认模块",
        description=truncate(description, 600),
        priority=priority,
        requirement_type=infer_requirement_type(section.title, fields, buckets),
        fields=fields,
        business_rules=dedupe_text(buckets["business_rules"]),
        preconditions=dedupe_text(buckets["preconditions"]),
        main_flow=dedupe_text(buckets["main_flow"]),
        alternative_flows=dedupe_text(buckets["alternative_flows"]),
        exceptions=dedupe_text(buckets["exceptions"]),
        acceptance_criteria=dedupe_text(buckets["acceptance_criteria"]),
        source_ref=section.title,
        raw_text=truncate("\n".join(body_lines), 1200),
    )


def fallback_item(text: str, doc_title: str) -> RequirementItem:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    title = doc_title or (clean_title(lines[0]) if lines else "整篇需求")
    table_fields, _ = extract_tables(lines, title)
    inline_fields = extract_inline_fields(lines, title)
    return RequirementItem(
        id="REQ-001",
        title=title,
        module="默认模块",
        description=truncate("\n".join(lines[:20]), 800),
        priority=infer_priority(text),
        requirement_type=RequirementType.FUNCTION,
        fields=merge_fields(table_fields, inline_fields),
        business_rules=dedupe_text([line for line in lines if RULE_INLINE_RE.search(line)][:10]),
        main_flow=[],
        source_ref="整篇文档",
        raw_text=truncate(text, 2000),
    )


def build_summary(doc_title: str, items: list[RequirementItem], text: str) -> str:
    field_count = sum(len(item.fields) for item in items)
    return (
        f"共解析出 {len(items)} 条需求、{field_count} 个可测字段，覆盖模块："
        + "、".join(dict.fromkeys(item.module for item in items))
    )


def infer_doc_title(sections: list[Section], text: str) -> str:
    if sections:
        return sections[0].title
    first_line = next((line.strip() for line in text.split("\n") if line.strip()), "")
    return truncate(clean_title(first_line), 40) or "未命名需求文档"


# --------------------------------------------------------------------------- #
# 表格 -> 字段
# --------------------------------------------------------------------------- #
def extract_tables(lines: list[str], section_title: str) -> tuple[list[FieldConstraint], list[str]]:
    fields: list[FieldConstraint] = []
    remaining: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if TABLE_ROW_RE.match(line):
            block: list[str] = []
            while index < len(lines) and TABLE_ROW_RE.match(lines[index]):
                block.append(lines[index])
                index += 1
            fields.extend(parse_table_block(block))
            continue
        if is_tab_table_row(line):
            tab_block: list[str] = []
            while index < len(lines) and is_tab_table_row(lines[index]):
                tab_block.append(lines[index])
                index += 1
            if looks_like_tab_table(tab_block):
                fields.extend(parse_table_block(tab_block, splitter=split_tab_row))
            else:
                remaining.extend(tab_block)
            continue
        remaining.append(line)
        index += 1
    return fields, remaining


def is_tab_table_row(line: str) -> bool:
    """判断一行是否「可能」属于 Tab 分隔表格（宽松初筛）。

    要求至少 2 列且至少 2 个非空单元格；是否真的是表格由 looks_like_tab_table 判定。
    """
    if "\t" not in line:
        return False
    cells = split_tab_row(line)
    return len(cells) >= 2 and sum(1 for cell in cells if cell) >= 2


def looks_like_tab_header(line: str) -> bool:
    """该行是否是 Tab 表格的表头（含「字段/类型/必填/约束」等列名）。"""
    if not is_tab_table_row(line):
        return False
    return any(
        key in cell
        for cell in split_tab_row(line)
        for key in TABLE_HEADER_KEYS
    )


def looks_like_tab_table(block: list[str]) -> bool:
    """判定一段 Tab 分隔的行是否构成表格。

    为避免把正文中偶然出现的制表符当成表格，要求：
      1. 至少 2 行；
      2. 每行至少 2 列，且所有行列数一致；
      3. 首行是含列名关键词的表头。
    不满足时按普通文本处理，宁可少解析也不构造出凭空捏造的字段。
    """
    if len(block) < 2:
        return False
    rows = [split_tab_row(row) for row in block]
    if len({len(row) for row in rows}) != 1 or len(rows[0]) < 2:
        return False
    return looks_like_tab_header(block[0])


def parse_table_block(
    block: list[str], *, splitter: Callable[[str], list[str]] | None = None
) -> list[FieldConstraint]:
    split = splitter or split_table_row
    rows = [split(row) for row in block]
    rows = [row for row in rows if row and not all(TABLE_SEP_RE.match(cell or "") for cell in row)]
    if len(rows) < 2:
        return []

    header = [normalize_whitespace(cell) for cell in rows[0]]
    has_header = any(any(key in cell for key in TABLE_NAME_KEYS) for cell in header)
    body_rows = rows[1:] if has_header else rows

    fields: list[FieldConstraint] = []
    for row in body_rows:
        if has_header:
            record = {header[i]: (row[i] if i < len(row) else "") for i in range(len(header))}
            field_model = field_from_record(record)
        else:
            field_model = field_from_cells(row)
        if field_model:
            fields.append(field_model)
    return fields


def split_table_row(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]


def split_tab_row(line: str) -> list[str]:
    """按 Tab 切分一行（Word / 网页表格复制粘贴后的常见形态）。"""
    return [cell.strip() for cell in TAB_SEP_RE.split(line.strip())]


def _pick(record: dict[str, str], keys: tuple[str, ...]) -> str:
    for key, value in record.items():
        for candidate in keys:
            if candidate and candidate in (key or ""):
                return (value or "").strip()
    return ""


def field_from_record(record: dict[str, str]) -> FieldConstraint | None:
    name = _pick(record, TABLE_NAME_KEYS)
    if not name or len(name) > 30:
        return None
    type_text = _pick(record, TABLE_TYPE_KEYS)
    required_text = _pick(record, TABLE_REQUIRED_KEYS)
    range_text = _pick(record, TABLE_RANGE_KEYS)
    default_text = _pick(record, TABLE_DEFAULT_KEYS)
    description = _pick(record, TABLE_DESC_KEYS)

    required = required_text.strip().lower() in TRUE_WORDS if required_text else False
    return build_field_constraint(
        name=name,
        type_text=type_text,
        required=required,
        constraint_text=range_text,
        default=default_text or None,
        description=description,
    )


def field_from_cells(cells: list[str]) -> FieldConstraint | None:
    if not cells:
        return None
    first = cells[0].strip()
    if ":" in first or "：" in first:
        return None
    if not first or len(first) > 30:
        return None
    joined = " ".join(cell for cell in cells[1:] if cell)
    return build_field_constraint(
        name=first,
        type_text=joined,
        required=False,
        constraint_text=joined,
        default=None,
        description=joined,
    )


def build_field_constraint(
    *,
    name: str,
    type_text: str,
    required: bool,
    constraint_text: str,
    default: str | None,
    description: str,
) -> FieldConstraint:
    combined = " ".join(dict.fromkeys(part.strip() for part in (type_text, constraint_text, description) if part and part.strip()))
    data_type = infer_data_type(name, combined)
    kwargs: dict[str, object] = {
        "name": name,
        "label": name,
        "data_type": data_type,
        "required": required,
        "nullable": not required,
        "default": default,
        "description": truncate(description or combined, 200),
    }

    enum_values = infer_enum_values(combined, data_type)
    if enum_values:
        kwargs["enum_values"] = enum_values
        kwargs["data_type"] = DataType.ENUM

    length_range = LEN_RANGE_RE.search(combined) or LEN_PREFIX_RANGE_RE.search(combined)
    exact_length = EXACT_LEN_RE.search(combined)
    numeric_range = RANGE_RE.search(combined)
    max_length = MAX_LEN_RE.search(combined)
    min_length = MIN_LEN_RE.search(combined)

    length_applied = False
    if length_range:
        kwargs["min_length"] = int(length_range.group("min"))
        kwargs["max_length"] = int(length_range.group("max"))
        length_applied = True
    elif exact_length:
        value = int(exact_length.group("value"))
        kwargs["min_length"] = value
        kwargs["max_length"] = value
        length_applied = True
    elif numeric_range:
        kwargs["min_value"] = float(numeric_range.group("min"))
        kwargs["max_value"] = float(numeric_range.group("max"))
    else:
        if max_length:
            kwargs["max_length"] = int(max_length.group("value"))
        if min_length:
            kwargs["min_length"] = int(min_length.group("value"))
        length_applied = bool(max_length or min_length)

    for hint, pattern in PATTERN_HINTS:
        if hint in name or hint in combined:
            kwargs["pattern"] = pattern
            break

    # 「6位数字」「11位」这类约束本质是长度约束，字段应按字符串处理，
    # 否则边界值/等价类会错把手机号、验证码当成可比较大小的整数；
    # 但必须同时保留「数字串」语义，否则数据构造会把手机号填成 AAAAAAAAAAA。
    if length_applied and kwargs.get("min_value") is None and kwargs.get("max_value") is None:
        if kwargs.get("data_type") is not DataType.ENUM:
            kwargs["data_type"] = DataType.STRING
            if is_digit_charset(name, combined, kwargs.get("pattern")):
                kwargs["value_charset"] = ValueCharset.DIGITS

    return FieldConstraint(**kwargs)



def infer_data_type(name: str, text: str) -> DataType:
    haystack = f"{name} {text}".lower()
    if any(hint in haystack for hint in BOOLEAN_HINTS):
        return DataType.BOOLEAN
    if any(hint in haystack for hint in INTEGER_HINTS):
        return DataType.INTEGER
    if any(hint in haystack for hint in FLOAT_HINTS):
        return DataType.FLOAT
    if any(hint in haystack for hint in NUMBER_HINTS):
        return DataType.INTEGER
    if any(hint in haystack for hint in ("日期", "date")):
        return DataType.DATE
    if "时间" in haystack or "datetime" in haystack:
        return DataType.DATETIME
    return DataType.STRING


def is_digit_charset(name: str, text: str, pattern: object = None) -> bool:
    """判断长度类字段是否应按「数字串」构造测试数据。"""
    haystack = f"{name} {text}"
    if any(hint in haystack for hint in DIGIT_CHARSET_HINTS):
        return True
    return isinstance(pattern, str) and pattern in DIGIT_ONLY_PATTERNS


def infer_enum_values(text: str, data_type: DataType) -> list[str]:
    if data_type is DataType.BOOLEAN:
        return []
    cleaned = re.sub(r"^(?:取值|可选值|枚举|枚举值|选项|包括|允许值)\s*[:：]?\s*", "", text.strip())
    for fragment in re.split(r"[；;。\n]", cleaned):
        fragment = fragment.strip()
        if not fragment or len(fragment) > 60:
            continue
        if not ENUM_SEPARATOR_RE.search(fragment):
            continue
        parts = [part.strip() for part in ENUM_SEPARATOR_RE.split(fragment) if part.strip()]
        if not (2 <= len(parts) <= 8):
            continue
        if any(len(part) > 12 for part in parts):
            continue
        if any(ENUM_STOPWORDS_HIT.search(part) for part in parts):
            continue
        if all(re.fullmatch(r"[\u4e00-\u9fa5A-Za-z0-9_\-]+", part) for part in parts):
            return list(dict.fromkeys(parts))
    return []


# --------------------------------------------------------------------------- #
# 行内字段（"手机号：11位数字，必填"）
# --------------------------------------------------------------------------- #
INLINE_FIELD_RE = re.compile(
    r"^(?P<name>[\u4e00-\u9fa5A-Za-z_][\u4e00-\u9fa5A-Za-z0-9_\-]{0,19})\s*[:：]\s*(?P<desc>.{2,200})$"
)


def extract_inline_fields(lines: list[str], section_title: str) -> list[FieldConstraint]:
    fields: list[FieldConstraint] = []
    for line in lines:
        match = INLINE_FIELD_RE.match(line.strip().lstrip("-*• ").strip())
        if not match:
            continue
        name = match.group("name").strip()
        desc = match.group("desc").strip()
        if name in ("说明", "备注", "描述", "注意", "规则", "结论") or section_title.startswith(name):
            continue
        required = any(word in desc for word in ("必填", "不能为空", "不可为空", "必输"))
        field_model = build_field_constraint(
            name=name,
            type_text=desc,
            required=required,
            constraint_text=desc,
            default=None,
            description=desc,
        )
        if field_model.enum_values and field_model.name.endswith("取值"):
            # 「注册状态取值：待激活/已激活/已冻结」这类写法：去掉尾部"取值"，
            # 让字段名更贴近可测字段本身（注册状态），导出与展示更清晰。
            clean_name = field_model.name[: -len("取值")]
            if clean_name:
                field_model = field_model.model_copy(update={"name": clean_name, "label": clean_name})
        fields.append(field_model)
    return fields


def merge_fields(
    primary: list[FieldConstraint], secondary: list[FieldConstraint]
) -> list[FieldConstraint]:
    merged: dict[str, FieldConstraint] = {}
    for field_model in [*primary, *secondary]:
        key = field_model.name.strip().lower()
        if key in merged:
            existing = merged[key]
            if not existing.description and field_model.description:
                merged[key] = field_model
            continue
        merged[key] = field_model
    return list(merged.values())


# --------------------------------------------------------------------------- #
# 分类辅助
# --------------------------------------------------------------------------- #
def _match_section_keyword(line: str) -> tuple[str, str] | None:
    """匹配章节关键词，返回 (section_key, 命中的关键词)。

    必须取「最长匹配」：否则「备选流程：」会被较短的「备选流」命中，
    剥离后残留「程：」污染用例数据。
    """
    text = line.strip().lstrip("#*-• ").strip()
    if not text or len(text) > 30:
        return None
    best: tuple[str, str] | None = None
    for key, keywords in SECTION_KEYWORDS:
        for keyword in keywords:
            if text.startswith(keyword) and (best is None or len(keyword) > len(best[1])):
                best = (key, keyword)
    return best


def match_section_keyword(line: str) -> str | None:
    matched = _match_section_keyword(line)
    return matched[0] if matched else None


def strip_section_keyword(line: str) -> str:
    matched = _match_section_keyword(line)
    if not matched:
        return ""
    text = line.strip().lstrip("#*-• ").strip()
    return text[len(matched[1]) :].lstrip("：: ").strip()


def strip_list_marker(line: str) -> str:
    match = LIST_ITEM_RE.match(line)
    return match.group("text").strip() if match else line.strip()


def dedupe_text(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = (item or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def infer_priority(text: str) -> Priority:
    lowered = text.lower()
    for priority, hints in PRIORITY_HINTS:
        if any(hint in lowered for hint in hints):
            return priority
    return Priority.P2


def infer_requirement_type(
    title: str, fields: list[FieldConstraint], buckets: dict[str, list[str]]
) -> RequirementType:
    if buckets.get("business_rules") and not fields:
        return RequirementType.BUSINESS_RULE
    if fields and any(hint in title for hint in ("接口", "API", "报文")):
        return RequirementType.INTERFACE
    if fields:
        return RequirementType.FUNCTION
    if buckets.get("main_flow"):
        return RequirementType.FUNCTION
    return RequirementType.CONSTRAINT
