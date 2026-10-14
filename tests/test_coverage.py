"""S4 回归：字段 / 边界 / 规则三维覆盖率与缺口清单。"""
from __future__ import annotations

from app.design.coverage import analyze_coverage, case_covers_field, case_mentions_rule, iter_rules
from app.schemas.common import CaseType, DesignMethod, Priority
from app.schemas.requirement import FieldConstraint, RequirementDoc, RequirementItem
from app.schemas.testcase import TestCase, TestCaseSuite, TestStep


def make_case(title: str, **kwargs) -> TestCase:
    defaults = dict(
        title=title,
        module="用户中心",
        requirement_ids=["REQ-001"],
        design_method=DesignMethod.EQUIVALENCE,
        case_type=CaseType.FUNCTIONAL,
        priority=Priority.P2,
    )
    defaults.update(kwargs)
    return TestCase(**defaults)


def make_doc() -> RequirementDoc:
    return RequirementDoc(
        doc_id="DOC-1",
        title="注册需求",
        items=[
            RequirementItem(
                id="REQ-001",
                title="用户注册",
                module="用户中心",
                fields=[
                    FieldConstraint(name="age", label="年龄", min_value=18, max_value=120),
                    FieldConstraint(name="phone", label="手机号", required=True, min_length=11, max_length=11),
                ],
                business_rules=["同一手机号不可重复注册"],
                main_flow=["进入注册页", "填写手机号", "提交注册"],
            ),
            RequirementItem(id="REQ-002", title="找回密码", description="支持短信找回。"),
        ],
    )


def make_suite(cases: list[TestCase]) -> TestCaseSuite:
    suite = TestCaseSuite(suite_id="SUITE-1", doc_id="DOC-1", doc_title="注册需求", cases=cases)
    suite.recount()
    return suite


class TestFieldDimension:
    def test_uncovered_field_is_reported_with_locating_info(self) -> None:
        doc = make_doc()
        suite = make_suite([make_case("年龄校验", test_data={"age": "18"})])
        report = analyze_coverage(doc, suite)
        field = report.dimension("field")
        assert field is not None
        assert field.total == 2 and field.covered == 1
        gap = field.gaps[0]
        assert gap.target == "手机号"
        assert gap.requirement_id == "REQ-001"

    def test_field_covered_via_tags_or_title(self) -> None:
        field = FieldConstraint(name="phone", label="手机号")
        assert case_covers_field(make_case("手机号校验"), field) is True
        assert case_covers_field(make_case("校验", tags=["phone"]), field) is True
        assert case_covers_field(make_case("其它", test_data={"phone": "1"}), field) is True
        assert case_covers_field(make_case("其它"), field) is False

    def test_note_when_no_fields(self) -> None:
        doc = RequirementDoc(doc_id="DOC-9", title="无字段", items=[RequirementItem(id="REQ-1", title="描述")])
        report = analyze_coverage(doc, make_suite([]))
        field = report.dimension("field")
        assert field is not None
        assert field.total == 0
        assert "未解析出任何可测字段" in field.note


class TestBoundaryDimension:
    def test_partial_boundary_coverage_lists_missing_points(self) -> None:
        doc = make_doc()
        # 只覆盖「最小值」这一个边界点。
        suite = make_suite([make_case("年龄最小值", test_data={"age": "18"})])
        boundary = analyze_coverage(doc, suite).dimension("boundary")
        assert boundary is not None
        assert 0 < boundary.covered < boundary.total
        labels = " ".join(gap.target for gap in boundary.gaps)
        assert "最小值-1" in labels

    def test_full_boundary_coverage(self) -> None:
        from app.design.boundary import boundary_points

        field = FieldConstraint(name="age", label="年龄", min_value=18, max_value=120)
        points, _ = boundary_points(field)
        cases = [make_case(f"点{index}", test_data={"age": point.value}) for index, point in enumerate(points)]
        doc = RequirementDoc(
            doc_id="DOC-1", title="t", items=[RequirementItem(id="REQ-001", title="注册", fields=[field])]
        )
        boundary = analyze_coverage(doc, make_suite(cases)).dimension("boundary")
        assert boundary is not None
        assert boundary.ratio == 1.0
        assert boundary.gaps == []

    def test_note_when_no_boundary_points(self) -> None:
        doc = RequirementDoc(
            doc_id="DOC-1",
            title="t",
            items=[RequirementItem(id="REQ-001", title="描述", description="无约束")],
        )
        boundary = analyze_coverage(doc, make_suite([])).dimension("boundary")
        assert boundary is not None
        assert boundary.total == 0 and boundary.note


class TestRuleDimension:
    def test_iter_rules_collects_all_sections(self) -> None:
        rules = iter_rules(make_doc().items[0])
        labels = {label for label, _ in rules}
        assert labels == {"业务规则", "主流程"}
        assert len(rules) == 4

    def test_rule_mentioned_in_case_is_covered(self) -> None:
        assert case_mentions_rule(make_case("同一手机号不可重复注册校验"), "同一手机号不可重复注册")
        assert case_mentions_rule(
            make_case("注册流程", steps=[TestStep(no=1, action="填写手机号")]), "填写手机号"
        )
        assert not case_mentions_rule(make_case("无关用例"), "同一手机号不可重复注册")

    def test_short_rules_are_not_falsely_matched(self) -> None:
        # 过短的规则串容易在任意文本里误命中，因此不参与匹配。
        assert case_mentions_rule(make_case("提交"), "提交") is False

    def test_uncovered_rules_are_listed(self) -> None:
        doc = make_doc()
        suite = make_suite([make_case("同一手机号不可重复注册", steps=[TestStep(no=1, action="重复注册")])])
        rule = analyze_coverage(doc, suite).dimension("rule")
        assert rule is not None
        assert rule.total == 4
        assert rule.covered == 1
        assert len(rule.gaps) == 3


class TestReportShape:
    def test_summary_and_overall_ratio(self) -> None:
        doc = make_doc()
        suite = make_suite([make_case("年龄最小", test_data={"age": "18"})])
        report = analyze_coverage(doc, suite)
        assert report.doc_id == "DOC-1"
        assert report.suite_id == "SUITE-1"
        assert 0 <= report.overall_ratio <= 1
        assert "综合覆盖率" in report.summary
        assert [item.key for item in report.dimensions] == ["field", "boundary", "rule"]

    def test_gaps_are_capped(self) -> None:
        doc = RequirementDoc(
            doc_id="DOC-1",
            title="t",
            items=[
                RequirementItem(
                    id="REQ-001",
                    title="大表单",
                    fields=[FieldConstraint(name=f"f{i}", label=f"字段{i}") for i in range(10)],
                )
            ],
        )
        field = analyze_coverage(doc, make_suite([]), max_gaps=3).dimension("field")
        assert field is not None
        assert field.total == 10
        assert len(field.gaps) == 3

    def test_cases_without_requirement_ids_do_not_crash(self) -> None:
        suite = make_suite([make_case("无归属", requirement_ids=[])])
        report = analyze_coverage(make_doc(), suite)
        assert report.summary
