"""S6 回归：SQLAlchemy 持久化后端与用例版本管理。

重点验证「业务层零改动即可切换」：同一套服务代码分别跑在 json 与 sqlite 后端上，
读写结果与统计口径必须一致。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.config import Settings
from app.llm.null_provider import NullProvider
from app.repository import Repository, build_repository, normalize_backend
from app.services.document_service import DocumentService
from app.services.pipeline_service import PipelineService

SAMPLE = """# 订单模块

## 1、下单
数量：1~99
备注：不超过 50 位
"""


def make_settings(tmp_path: Path, backend: str) -> Settings:
    settings = Settings(storage_dir=tmp_path / backend, storage_backend=backend)
    settings.ensure_dirs()
    return settings


def upload_document(settings: Settings, repository: Repository, *, filename: str = "订单需求.md") -> str:
    record = asyncio.run(
        DocumentService(settings, repository).save_and_parse(
            filename=filename, data=SAMPLE.encode("utf-8")
        )
    )
    return record.doc_id


def generate(settings: Settings, repository: Repository, doc_id: str, methods: list[str]):
    service = PipelineService(settings, NullProvider(settings), repository)
    return asyncio.run(service.run(doc_id=doc_id, methods=methods, use_llm=False))


class TestBackendSwitch:
    def test_normalize_backend_aliases(self) -> None:
        assert normalize_backend("sqlite") == Repository.BACKEND_SQLITE
        assert normalize_backend("SQL") == Repository.BACKEND_SQLITE
        assert normalize_backend("db") == Repository.BACKEND_SQLITE
        assert normalize_backend("json") == Repository.BACKEND_JSON
        assert normalize_backend("") == Repository.BACKEND_JSON
        # 未知取值回落 json：写错一个词不该让使用者的数据"消失"。
        assert normalize_backend("postgres") == Repository.BACKEND_JSON

    def test_repository_selects_backend(self, tmp_path: Path) -> None:
        json_repo = build_repository(make_settings(tmp_path, "json"))
        sql_repo = build_repository(make_settings(tmp_path, "sqlite"))
        assert type(json_repo.documents).__name__ == "JsonObjectStore"
        assert type(sql_repo.documents).__name__ == "SqlObjectStore"
        assert sql_repo.engine is not None
        assert json_repo.engine is None

    def test_sqlite_roundtrip_matches_json(self, tmp_path: Path) -> None:
        json_repo = build_repository(make_settings(tmp_path, "json"))
        sql_repo = build_repository(make_settings(tmp_path, "sqlite"))
        json_doc = upload_document(json_repo.settings, json_repo)
        sql_doc = upload_document(sql_repo.settings, sql_repo)
        generate(json_repo.settings, json_repo, json_doc, ["equivalence"])
        generate(sql_repo.settings, sql_repo, sql_doc, ["equivalence"])

        assert json_repo.documents.count() == sql_repo.documents.count() == 1
        assert json_repo.requirements.count() == sql_repo.requirements.count() == 1
        assert json_repo.suites.count() == sql_repo.suites.count() == 1
        assert json_repo.count_cases() == sql_repo.count_cases()
        assert json_repo.count_linked_requirements() == sql_repo.count_linked_requirements() == 1
        # 两个后端的 doc_id 各自随机生成，比集合大小而不是比具体 ID。
        assert len(json_repo.referenced_requirement_ids()) == 1
        assert len(sql_repo.referenced_requirement_ids()) == 1

        json_suite = json_repo.suites.list_recent(5)[0]
        sql_suite = sql_repo.suites.list_recent(5)[0]
        assert [case.title for case in json_suite.cases] == [case.title for case in sql_suite.cases]

    def test_sqlite_stores_are_isolated_by_kind(self, tmp_path: Path) -> None:
        """三类实体同名主键不能互相覆盖（同一张表用 kind 区分）。"""
        repo = build_repository(make_settings(tmp_path, "sqlite"))
        doc_id = upload_document(repo.settings, repo)
        generate(repo.settings, repo, doc_id, ["equivalence"])
        assert repo.documents.get(doc_id).doc_id == doc_id
        assert repo.requirements.get(doc_id).doc_id == doc_id
        assert repo.requirements.exists(doc_id) and repo.documents.exists(doc_id)

    def test_sqlite_delete_and_missing(self, tmp_path: Path) -> None:
        repo = build_repository(make_settings(tmp_path, "sqlite"))
        doc_id = upload_document(repo.settings, repo)
        assert repo.documents.try_get("DOC-nope") is None
        assert repo.documents.delete("DOC-nope") is False
        assert repo.documents.delete(doc_id) is True
        assert repo.documents.exists(doc_id) is False

    def test_purge_orphan_requirements_on_sqlite(self, tmp_path: Path) -> None:
        repo = build_repository(make_settings(tmp_path, "sqlite"))
        doc_id = upload_document(repo.settings, repo)
        generate(repo.settings, repo, doc_id, ["equivalence"])
        suite_id = repo.suites.list_ids()[0]
        repo.documents.delete(doc_id)
        repo.suites.delete(suite_id)
        assert repo.purge_orphan_requirements() == 1
        assert repo.requirements.count() == 0

    def test_list_recent_filters_before_truncating(self, tmp_path: Path) -> None:
        """与 JSON 后端同口径：先过滤再截断，否则会给出「这条需求只有一份用例集」的假读数。"""
        repo = build_repository(make_settings(tmp_path, "sqlite"))
        first = upload_document(repo.settings, repo, filename="A.md")
        second = upload_document(repo.settings, repo, filename="B.md")
        for _ in range(3):
            generate(repo.settings, repo, first, ["boundary"])
        generate(repo.settings, repo, second, ["boundary"])

        matched = repo.suites.list_recent(2, predicate=lambda item: item.doc_id == first)
        assert len(matched) == 2
        assert all(item.doc_id == first for item in matched)


class TestSuiteRevision:
    def test_revision_increments_per_requirement(self, tmp_path: Path) -> None:
        repo = build_repository(make_settings(tmp_path, "sqlite"))
        first_doc = upload_document(repo.settings, repo, filename="A.md")
        second_doc = upload_document(repo.settings, repo, filename="B.md")

        assert generate(repo.settings, repo, first_doc, ["equivalence"]).suite.revision == 1
        assert generate(repo.settings, repo, first_doc, ["boundary"]).suite.revision == 2
        # 版本号按需求分组：换一份需求从 1 重新开始，而不是全局累加。
        assert generate(repo.settings, repo, second_doc, ["equivalence"]).suite.revision == 1

    def test_suite_history_returns_latest_first(self, tmp_path: Path) -> None:
        repo = build_repository(make_settings(tmp_path, "sqlite"))
        doc_id = upload_document(repo.settings, repo)
        generate(repo.settings, repo, doc_id, ["equivalence"])
        generate(repo.settings, repo, doc_id, ["equivalence", "boundary"])
        history = repo.suite_history(doc_id)
        assert [item.revision for item in history] == [2, 1]

    def test_suite_summary_carries_revision(self, tmp_path: Path) -> None:
        repo = build_repository(make_settings(tmp_path, "sqlite"))
        doc_id = upload_document(repo.settings, repo)
        generate(repo.settings, repo, doc_id, ["equivalence"])
        assert repo.suites.list_recent(1)[0].summary().revision == 1

    def test_explicit_revision_is_respected(self, tmp_path: Path) -> None:
        from app.schemas.testcase import TestCaseSuite

        repo = build_repository(make_settings(tmp_path, "sqlite"))
        repo.save_suite(TestCaseSuite(suite_id="SUITE-fixed", doc_id="DOC-x", revision=7))
        assert repo.suites.get("SUITE-fixed").revision == 7


class TestMigration:
    def test_json_to_sqlite_migration_is_idempotent(self, tmp_path: Path) -> None:
        from app.sql_store import create_db_engine, migrate_payloads
        from scripts.migrate_json_to_sqlite import collect_records

        json_settings = make_settings(tmp_path, "json")
        json_repo = build_repository(json_settings)
        doc_id = upload_document(json_settings, json_repo)
        generate(json_settings, json_repo, doc_id, ["equivalence"])

        records, counts = collect_records(json_settings.data_dir)
        assert counts["suites"] == 1
        assert counts["requirements"] == 1
        assert counts["documents"] == 1

        sql_settings = make_settings(tmp_path, "sqlite")
        engine = create_db_engine(sql_settings.db_path)
        assert migrate_payloads(engine, records) == len(records)
        assert migrate_payloads(engine, records) == len(records)  # 重跑不重复

        sql_repo = build_repository(sql_settings)
        assert sql_repo.documents.count() == 1
        assert sql_repo.count_cases() == json_repo.count_cases()
        assert sql_repo.suites.list_recent(1)[0].suite_id == json_repo.suites.list_recent(1)[0].suite_id

    def test_collect_records_skips_broken_files(self, tmp_path: Path) -> None:
        from scripts.migrate_json_to_sqlite import collect_records

        settings = make_settings(tmp_path, "json")
        directory = settings.data_dir / "documents"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "broken.json").write_text("{not json", encoding="utf-8")
        records, counts = collect_records(settings.data_dir)
        assert records == []
        assert counts == {}
