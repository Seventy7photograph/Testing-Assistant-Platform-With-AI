"""存储层的最小回归：`list_recent` 的「先过滤还是先截断」直接决定界面读数。

顺序反了，列表接口就会给出「这条需求只生成过一两份用例集」的假象——
文件先被 limit 砍掉一半，再去筛其中属于该需求的，剩下的自然少。
"""
from __future__ import annotations

from pathlib import Path

from app.repository import JsonObjectStore
from app.schemas.testcase import TestCaseSuite


def _suite(suite_id: str, doc_id: str) -> TestCaseSuite:
    return TestCaseSuite(suite_id=suite_id, doc_id=doc_id, doc_title=doc_id)


def test_list_recent_filters_before_limit(tmp_path: Path) -> None:
    store: JsonObjectStore[TestCaseSuite] = JsonObjectStore(
        tmp_path / "suites", TestCaseSuite, id_attr="suite_id", label="用例集"
    )
    for index in range(6):
        store.save(_suite(f"SUITE-other-{index}", "DOC-other"))
    for index in range(3):
        store.save(_suite(f"SUITE-target-{index}", "DOC-target"))

    picked = store.list_recent(limit=2, predicate=lambda suite: suite.doc_id == "DOC-target")

    assert len(picked) == 2
    assert all(item.doc_id == "DOC-target" for item in picked)


def test_list_recent_without_predicate_keeps_limit(tmp_path: Path) -> None:
    store: JsonObjectStore[TestCaseSuite] = JsonObjectStore(
        tmp_path / "suites", TestCaseSuite, id_attr="suite_id", label="用例集"
    )
    for index in range(4):
        store.save(_suite(f"SUITE-{index}", "DOC-x"))

    assert len(store.list_recent(limit=3)) == 3
    assert len(store.list_recent(limit=0)) == 0