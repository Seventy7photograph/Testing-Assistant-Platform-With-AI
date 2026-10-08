"""规则解析器单测：章节切分、表格字段、约束抽取、流程分类。"""
from __future__ import annotations

from app.schemas.common import DataType, Priority, ValueCharset
from app.services.rule_parser import parse_requirements


def _doc(text: str, title: str = "测试需求") -> tuple[str, str, list, list]:
    return parse_requirements(text, doc_title=title, max_items=10)


def test_markdown_doc_splits_into_sections(sample_text: str) -> None:
    doc_title, summary, items, warnings = _doc(sample_text)
    assert doc_title == "测试需求"
    assert len(items) == 1
    assert items[0].title == "用户注册"
    assert "1 条需求" in summary
    assert not warnings


def test_numbered_steps_are_not_treated_as_sections(sample_text: str) -> None:
    _, _, items, _ = _doc(sample_text)
    assert items[0].main_flow == ["进入注册页", "填写手机号与昵称", "提交注册"]


def test_flows_rules_and_acceptance_classified(sample_text: str) -> None:
    _, _, items, _ = _doc(sample_text)
    item = items[0]
    assert item.alternative_flows == ["手机号已注册时提示直接登录"]
    assert item.exceptions == ["短信通道异常"]
    assert item.business_rules == ["不允许昵称包含敏感词"]
    assert item.acceptance_criteria == ["注册成功后自动跳转首页"]


def test_inline_field_constraints(sample_text: str) -> None:
    _, _, items, _ = _doc(sample_text)
    fields = {field.name: field for field in items[0].fields}
    assert fields["手机号"].min_length == 11
    assert fields["手机号"].max_length == 11
    assert fields["手机号"].required is True
    assert fields["手机号"].data_type is DataType.STRING
    assert fields["手机号"].pattern == r"^1[3-9]\d{9}$"
    assert fields["年龄"].min_value == 18
    assert fields["年龄"].max_value == 120
    assert fields["状态"].enum_values == ["待激活", "已激活", "已冻结"]


def test_table_field_constraints(sample_text: str) -> None:
    _, _, items, _ = _doc(sample_text)
    fields = {field.name: field for field in items[0].fields}
    assert fields["昵称"].min_length == 2
    assert fields["昵称"].max_length == 20
    assert fields["昵称"].required is True
    assert fields["余额"].min_value == 0
    assert fields["余额"].max_value == 99999.99


def test_numeric_field_is_not_converted_to_string() -> None:
    _, _, items, _ = _doc("## 下单\n- 数量：1~999\n")
    field = items[0].fields[0]
    assert field.data_type is DataType.INTEGER
    assert (field.min_value, field.max_value) == (1, 999)
    assert field.min_length is None


def test_document_without_headings_falls_back_to_paragraphs() -> None:
    text = "用户注册\n手机号必须 11 位且必填。\n\n订单查询\n支持按下单时间查询订单。\n"
    _, _, items, _ = _doc(text)
    assert len(items) == 2
    assert {item.title for item in items} == {"用户注册", "订单查询"}


def test_priority_and_type_inference() -> None:
    _, _, items, _ = _doc("## 核心支付功能\n必须支持重复支付拦截，P0。\n")
    assert items[0].priority is Priority.P0
    assert items[0].business_rules


def test_empty_text_returns_no_items() -> None:
    _, _, items, warnings = _doc("")
    assert items == []
    assert warnings


def test_container_heading_is_not_a_requirement() -> None:
    text = "# 需求说明书\n\n## 用户注册\n手机号：11位数字\n\n## 订单创建\n数量：1~99\n"
    _, _, items, _ = _doc(text)
    assert [item.title for item in items] == ["用户注册", "订单创建"]
    # 只有一个容器型一级标题时，它只是文档名；模块应取子章节标题，
    # 否则所有用例的「所属模块」都会退化成同一个文档名。
    assert {item.module for item in items} == {"用户注册", "订单创建"}


def test_single_heading_with_body_is_kept() -> None:
    _, _, items, _ = _doc("# 用户注册\n手机号：11位数字，必填\n")
    assert len(items) == 1
    assert items[0].title == "用户注册"


def test_max_items_limit_applied() -> None:
    text = "\n\n".join(f"## 需求{i}\n内容{i}说明。" for i in range(1, 8))
    _, _, items, warnings = _doc(text)
    assert len(items) == 7
    assert items[0].title == "需求1"
    _, _, limited, limited_warnings = parse_requirements(text, max_items=3)
    assert len(limited) == 3
    assert limited_warnings


# --------------------------------------------------------------------------- #
# 缺陷回归：长度区间误判 / 数字串字符集 / Tab 表格
# --------------------------------------------------------------------------- #
def test_length_range_without_unit_is_length_not_value() -> None:
    """「长度2~20」不应被当成可比较大小的数值区间。"""
    _, _, items, _ = _doc("## 注册\n- 昵称：长度2~20位，必填\n- 签名：长度 5~100\n")
    fields = {field.name: field for field in items[0].fields}
    assert (fields["昵称"].min_length, fields["昵称"].max_length) == (2, 20)
    assert fields["昵称"].has_numeric_range is False
    assert (fields["签名"].min_length, fields["签名"].max_length) == (5, 100)
    assert fields["签名"].has_numeric_range is False


def test_digit_length_field_keeps_digit_charset() -> None:
    """「11位数字」是长度约束，但必须保留数字串语义，供数据构造使用数字填充。"""
    _, _, items, _ = _doc("## 注册\n手机号：11位数字，必填\n昵称：2-20位\n")
    fields = {field.name: field for field in items[0].fields}
    assert fields["手机号"].data_type is DataType.STRING
    assert fields["手机号"].value_charset is ValueCharset.DIGITS
    assert fields["昵称"].value_charset is ValueCharset.TEXT


def test_digit_only_pattern_implies_digit_charset() -> None:
    """手机号/身份证/邮编等内置正则本身只接受数字，应自动按数字串处理。"""
    _, _, items, _ = _doc("## 注册\n- 身份证号：18位\n- 邮编：6位\n")
    for field in items[0].fields:
        assert field.value_charset is ValueCharset.DIGITS


def test_tab_separated_table_is_parsed() -> None:
    """从 Word/网页复制粘贴产生的 Tab 分隔表格也应被识别。"""
    text = "## 注册\n字段\t是否必填\t约束\n手机号\t是\t11位数字\n昵称\t是\t长度2~20\n"
    _, _, items, warnings = _doc(text)
    fields = {field.name: field for field in items[0].fields}
    assert set(fields) == {"手机号", "昵称"}
    assert fields["手机号"].min_length == 11
    assert warnings == []


def test_unparsed_tab_table_emits_warning() -> None:
    """疑似表格却一个字段都没解析出来时，必须给出可操作的兜底提示。"""
    text = "## 注册\n说明\t备注\n这是一段普通描述\n"
    _, _, items, warnings = _doc(text)
    assert not any(item.fields for item in items)
    assert any("Tab 分隔" in warning for warning in warnings)


def test_plain_text_with_stray_tab_is_not_a_table() -> None:
    """正文里偶然出现的制表符不应被误判成表格，也不应触发表格告警。"""
    text = "## 注册\n用户点击\t提交按钮后完成注册。\n请联系管理员\t获取帮助。\n"
    _, _, items, warnings = _doc(text)
    assert not any(item.fields for item in items)
    assert warnings == []


# --------------------------------------------------------------------------- #
# 缺陷回归：模块归属 / 枚举字段命名 / 默认优先级
# --------------------------------------------------------------------------- #
def test_multiple_level1_headings_keep_module_semantics() -> None:
    """多个一级标题本身就是模块名时，模块归属不能被改写。"""
    text = "# 用户模块\n## 注册\n手机号：11位数字\n\n# 订单模块\n## 下单\n数量：1~99\n"
    _, _, items, _ = _doc(text)
    assert {item.module for item in items} == {"用户模块", "订单模块"}


def test_heading_only_doc_uses_section_title_as_module() -> None:
    """整篇没有一级标题时，二级章节本身就是模块归属，不能退化成「默认模块」。"""
    text = "## 用户注册\n手机号：11位数字\n\n## 订单创建\n数量：1~99\n"
    _, _, items, _ = _doc(text)
    assert {item.module for item in items} == {"用户注册", "订单创建"}


def test_enum_field_name_strips_quzhi_suffix() -> None:
    """「注册状态取值：待激活/已激活」应解析为字段「注册状态」而不是带"取值"的名字。"""
    _, _, items, _ = _doc("## 注册\n注册状态取值：待激活/已激活/已冻结\n")
    fields = {field.name: field for field in items[0].fields}
    assert "注册状态" in fields
    assert fields["注册状态"].enum_values == ["待激活", "已激活", "已冻结"]


def test_exception_or_business_rule_bumps_default_priority() -> None:
    """未显式标注优先级、但含异常场景/业务规则时，默认提升为 P1 而非全部 P2。"""
    _, _, items, _ = _doc("## 普通功能\n异常场景：\n- 网络中断\n")
    assert items[0].priority is Priority.P1
