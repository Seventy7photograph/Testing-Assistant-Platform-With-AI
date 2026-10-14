"""S5 回归：需求变更差异对比 与 需求-用例双向追溯矩阵。"""
from __future__ import annotations

from app.schemas.common import CaseType, DataType, DesignMethod, Priority
from app.schemas.requirement import FieldConstraint, RequirementDoc, RequirementItem
from app.schemas.testcase import TestCase, TestCaseSuite
from app.services.traceability import (
    attribute_text,
    build_traceability_matrix,
    describe_field,
    diff_fields,
    diff_requirements,
)

API = "/api/v1"


def item(
    *,
    id: str = "REQ-001",
    title: str = "用户注册",
    fields: list[FieldConstraint] | None = None,
    rules: list[str] | None = None,
) -> RequirementItem:
    return RequirementItem(
        id=id,
        title=title,
        module="用户中心",
        fields=fields
        if fields is not None
        else [FieldConstraint(name="phone", label="手机号", required=True, min_length=11, max_length=11)],
        business_rules=rules if rules is not None else ["同一手机号不可重复注册"],
        main_flow=["进入注册页", "提交注册"],
    )


def doc(items: list[RequirementItem], *, doc_id: str = "DOC-1", title: str = "注册需求") -> RequirementDoc:
    return RequirementDoc(doc_id=doc_id, title=title, items=items)


class TestDiff:
    def test_identical_docs_report_no_change(self) -> None:
        diff = diff_requirements(doc([item()]), doc([item()], doc_id="DOC-2"))
        assert diff.changed_count == 0
        assert diff.unchanged == 1
        assert "新增 0 条" in diff.summary

    def test_added_and_removed(self) -> None:
        older = doc([item(id="REQ-001", title="用户注册"), item(id="REQ-002", title="找回密码")])
        newer = doc([item(id="REQ-001", title="用户注册"), item(id="REQ-003", title="注销账号")], doc_id="DOC-2")
        diff = diff_requirements(older, newer)
        assert [change.title for change in diff.added] == ["注销账号"]
        assert [change.title for change in diff.removed] == ["找回密码"]
        assert diff.unchanged == 1

    def test_field_constraint_change_is_reported(self) -> None:
        older = doc([item(fields=[FieldConstraint(name="age", label="年龄", min_value=18, max_value=120)])])
        newer = doc(
            [item(fields=[FieldConstraint(name="age", label="年龄", min_value=18, max_value=150)])],
            doc_id="DOC-2",
        )
        diff = diff_requirements(older, newer)
        assert len(diff.modified) == 1
        change = diff.modified[0].field_changes[0]
        assert change.field == "age"
        assert change.attribute == "max_value"
        assert (change.before, change.after) == ("120", "150")
        assert "max_value" in change.describe()

    def test_added_and_removed_fields(self) -> None:
        older = doc([item(fields=[FieldConstraint(name="phone", label="手机号")])])
        newer = doc(
            [item(fields=[FieldConstraint(name="email", label="邮箱", data_type=DataType.STRING)])],
            doc_id="DOC-2",
        )
        changes = diff_fields(older.items[0], newer.items[0])
        attributes = {(change.field, change.attribute) for change in changes}
        assert ("phone", "(字段)") in attributes
        assert ("email", "(字段)") in attributes

    def test_rule_change_marks_section(self) -> None:
        older = doc([item(rules=["同一手机号不可重复注册"])])
        newer = doc([item(rules=["同一手机号不可重复注册", "注册需短信验证"])], doc_id="DOC-2")
        diff = diff_requirements(older, newer)
        assert diff.modified[0].changed_sections == ["业务规则"]
        assert "业务规则" in diff.modified[0].detail

    def test_retitled_item_is_matched_not_recreated(self) -> None:
        older = doc([item(id="REQ-001", title="用户注册流程")])
        newer = doc([item(id="REQ-009", title="用户注册流程（新版）")], doc_id="DOC-2")
        diff = diff_requirements(older, newer)
        assert diff.added == [] and diff.removed == []
        assert len(diff.modified) == 1

    def test_unrelated_titles_are_add_and_remove(self) -> None:
        older = doc([item(id="REQ-001", title="用户注册")])
        newer = doc([item(id="REQ-002", title="订单导出")], doc_id="DOC-2")
        diff = diff_requirements(older, newer)
        assert len(diff.added) == 1 and len(diff.removed) == 1

    def test_helpers(self) -> None:
        assert attribute_text(None) == ""
        assert attribute_text(["a", "b"]) == "a | b"
        assert "手机号" in describe_field(FieldConstraint(name="phone", label="手机号", required=True))


def make_case(case_id: str, requirement_ids: list[str], **kwargs) -> TestCase:
    defaults = dict(
        title=f"用例 {case_id}",
        requirement_ids=requirement_ids,
        design_method=DesignMethod.EQUIVALENCE,
        case_type=CaseType.FUNCTIONAL,
        priority=Priority.P2,
    )
    defaults.update(kwargs)
    return TestCase(case_id=case_id, **defaults)


class TestMatrix:
    def test_forward_and_reverse_agree(self) -> None:
        requirement_doc = doc([item(id="REQ-001"), item(id="REQ-002", title="找回密码")])
        suite = TestCaseSuite(
            suite_id="SUITE-1",
            doc_id="DOC-1",
            cases=[
                make_case("TC-1", ["REQ-001"]),
                make_case("TC-2", ["REQ-001", "REQ-002"]),
            ],
        )
        matrix = build_traceability_matrix(requirement_doc, [suite])
        forward = {trace.requirement_id: trace.case_count for trace in matrix.requirements}
        assert forward == {"REQ-001": 2, "REQ-002": 1}
        assert sum(trace.case_count for trace in matrix.requirements) == 3
        assert len(matrix.cases) == 2
        assert matrix.uncovered_requirement_ids == []

    def test_uncovered_and_orphan(self) -> None:
        requirement_doc = doc([item(id="REQ-001"), item(id="REQ-002", title="找回密码")])
        suite = TestCaseSuite(
            suite_id="SUITE-1",
            doc_id="DOC-1",
            cases=[make_case("TC-1", ["REQ-001"]), make_case("TC-9", ["REQ-404"])],
        )
        matrix = build_traceability_matrix(requirement_doc, [suite])
        assert matrix.uncovered_requirement_ids == ["REQ-002"]
        assert matrix.orphan_case_ids == ["TC-9"]
        orphan = next(trace for trace in matrix.cases if trace.case_id == "TC-9")
        assert orphan.missing_requirement_ids == ["REQ-404"]
        assert orphan.resolved_requirement_ids == []
        assert "未覆盖 1 条" in matrix.summary

    def test_cases_without_requirement_ids_are_not_orphans(self) -> None:
        """没标需求的用例只是没归属，不等于「关联到了不存在的需求」。"""
        requirement_doc = doc([item(id="REQ-001")])
        suite = TestCaseSuite(suite_id="SUITE-1", doc_id="DOC-1", cases=[make_case("TC-1", [])])
        matrix = build_traceability_matrix(requirement_doc, [suite])
        assert matrix.orphan_case_ids == []
        assert matrix.uncovered_requirement_ids == ["REQ-001"]


class TestApi:
    def _parse(self, client, text: str, title: str) -> str:
        body = client.post(
            f"{API}/requirements/parse", json={"text": text, "title": title, "use_llm": False}
        ).json()
        assert body["success"] is True, body
        return body["data"]["doc_id"]

    def test_diff_endpoint(self, client) -> None:
        older = self._parse(client, "# 注册\n## 用户注册\n年龄：18~120\n", "旧版需求")
        newer = self._parse(client, "# 注册\n## 用户注册\n年龄：18~150\n- 昵称：2-20位\n", "新版需求")
        response = client.get(f"{API}/requirements/{newer}/diff", params={"against": older})
        assert response.status_code == 200, response.text
        diff = response.json()["data"]
        assert diff["older_doc_id"] == older
        assert diff["newer_doc_id"] == newer
        assert diff["changed_count"] >= 1

    def test_diff_requires_existing_baseline(self, client) -> None:
        doc_id = self._parse(client, "# 注册\n## 用户注册\n年龄：18~120\n", "需求")
        response = client.get(f"{API}/requirements/{doc_id}/diff", params={"against": "DOC-nope"})
        assert response.status_code == 404

    def test_traceability_endpoint(self, client) -> None:
        upload = client.post(
            f"{API}/documents/upload",
            files={"file": ("需求.md", "# 注册\n## 用户注册\n年龄：18~120\n".encode("utf-8"), "text/markdown")},
        ).json()["data"]
        doc_id = upload["doc_id"]
        suite = client.post(
            f"{API}/testcases/generate",
            json={"doc_id": doc_id, "methods": ["boundary"], "use_llm": False},
        ).json()["data"]

        response = client.get(f"{API}/requirements/{doc_id}/traceability")
        assert response.status_code == 200, response.text
        matrix = response.json()["data"]
        assert matrix["doc_id"] == doc_id
        assert matrix["suite_ids"] == [suite["suite_id"]]
        assert matrix["requirements"]
        assert matrix["summary"]


class TestCoverageApi:
    def test_coverage_endpoint(self, client) -> None:
        upload = client.post(
            f"{API}/documents/upload",
            files={"file": ("需求.md", "# 注册\n## 用户注册\n年龄：18~120\n昵称：2-20位\n".encode("utf-8"), "text/markdown")},
        ).json()["data"]
        doc_id = upload["doc_id"]
        suite = client.post(
            f"{API}/testcases/generate",
            json={"doc_id": doc_id, "methods": ["boundary"], "use_llm": False},
        ).json()["data"]

        response = client.get(f"{API}/testcases/{suite['suite_id']}/coverage")
        assert response.status_code == 200, response.text
        report = response.json()["data"]
        assert [item["key"] for item in report["dimensions"]] == ["field", "boundary", "rule"]
        assert report["summary"]

    def test_coverage_missing_requirement_returns_404(self, client) -> None:
        response = client.get(f"{API}/testcases/SUITE-nope/coverage")
        assert response.status_code == 404
