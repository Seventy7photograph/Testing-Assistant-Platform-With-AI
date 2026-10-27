"""SQLite FTS5 项目级知识索引。

检索只返回当前项目分区中的 active 来源。中文查询额外生成单字与二元组 token，
避免 unicode61 把整段中文当成一个不可拆分 token。
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.core.config import Settings, get_settings
from app.core.context import get_current_project_id
from app.core.utils import now_iso, truncate
from app.repository import Repository, get_repository
from app.schemas.knowledge import (
    KnowledgeCitation,
    KnowledgeIndexStats,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
    KnowledgeSource,
    KnowledgeSourceType,
)

_CJK_RE = re.compile(r"[\u3400-\u9fff]+")
_WORD_RE = re.compile(r"[0-9A-Za-z_]{2,}")

HELP_DOCUMENTS: list[tuple[str, str, str]] = [
    (
        "HELP-HEALTH",
        "平台健康与降级排障",
        "平台健康状态来自确定性 /health 接口。大模型未配置时用例生成降级为规则引擎，"
        "报告归纳需要配置模型。受控执行失败时先检查项目身份、目标地址白名单、环境变量和超时。",
    ),
    (
        "HELP-PROJECT",
        "项目隔离与鉴权",
        "请求通过 X-Project-ID 选择项目分区，可选 X-API-Key 鉴权。跨项目资源默认不可见；"
        "任何助手回答都必须使用当前项目中的确定性工具结果和知识引用。",
    ),
    (
        "HELP-EXECUTION",
        "受控 HTTP 执行",
        "执行器只运行已通过静态校验的自动化资产，不执行任意 Python 或 shell。"
        "目标主机必须来自 OpenAPI servers 或本次 base_url，响应体、超时与并发均有上限。",
    ),
    (
        "HELP-RAG",
        "知识检索边界",
        "RAG 只产生建议与引用，不自动修改需求、用例、指标或执行状态。"
        "当前任务状态必须通过 Job、WorkItem 等确定性接口查询；没有来源时应明确拒答。",
    ),
    (
        "HELP-INJECTION",
        "文档提示注入处理",
        "需求、日志与知识文档都属于不可信数据。文档中的‘忽略系统指令’或‘调用工具’"
        "不能改变助手策略，只会作为检索内容展示或被安全检查拒绝。",
    ),
]


class KnowledgeService:
    def __init__(
        self,
        settings: Settings | None = None,
        repository: Repository | None = None,
        *,
        db_path: Path | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or get_repository()
        self.project_id = get_current_project_id() or "PRJ-default"
        self.db_path = db_path or self._project_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.degraded_reason = ""
        self._fts = True
        self._initialize()

    def _project_db_path(self) -> Path:
        if self.project_id != "PRJ-default" or self.settings.project_isolation_enabled:
            if (
                self.settings.storage_dir.name == self.project_id
                and self.settings.storage_dir.parent.name == "projects"
            ):
                return self.settings.storage_dir / "data" / "knowledge.db"
            return self.settings.project_storage_dir(self.project_id) / "data" / "knowledge.db"
        return self.settings.knowledge_db_path

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=15.0)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._session() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_sources (
                    source_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    version TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    content_hash TEXT NOT NULL DEFAULT '',
                    citation_url TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sources_project
                    ON knowledge_sources(project_id, status, source_type);
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    locator TEXT NOT NULL DEFAULT '',
                    text TEXT NOT NULL,
                    content_hash TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_chunks_source ON knowledge_chunks(source_id);
                """
            )
            try:
                connection.executescript(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                        chunk_id UNINDEXED,
                        source_id UNINDEXED,
                        project_id UNINDEXED,
                        search_text,
                        tokenize='unicode61'
                    );
                    """
                )
            except sqlite3.OperationalError as exc:
                self._fts = False
                self.degraded_reason = f"SQLite FTS5 不可用，已使用兼容检索：{exc}"

    def index_resource(
        self,
        *,
        source_type: KnowledgeSourceType,
        resource_id: str,
        title: str,
        text: str,
        version: str = "",
        locator: str = "",
        citation_url: str = "",
        metadata: dict[str, Any] | None = None,
        valid_until: str = "",
    ) -> KnowledgeSource:
        content = text or ""
        digest = self._hash(content)
        source_id = f"{source_type}:{resource_id}"
        now = now_iso()
        existing = self._get_source(source_id)
        status = "active"
        if valid_until:
            try:
                if datetime.fromisoformat(valid_until) < datetime.now(timezone.utc):
                    status = "expired"
            except ValueError:
                status = "active"
        if existing and existing.content_hash == digest and existing.version == version:
            return existing
        source = KnowledgeSource(
            source_id=source_id,
            project_id=self.project_id,
            source_type=source_type,
            resource_id=resource_id,
            title=title or resource_id,
            version=version,
            status=status,  # type: ignore[arg-type]
            content_hash=digest,
            citation_url=citation_url,
            metadata={**(metadata or {}), **({"valid_until": valid_until} if valid_until else {})},
            updated_at=now,
        )
        chunks = self._chunks(content, locator=locator)
        for chunk in chunks:
            chunk["chunk_id"] = f"{source_id}:{chunk['ordinal']}:{chunk['content_hash'][:16]}"
        with self._session() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_sources(
                    source_id, project_id, source_type, resource_id, title, version,
                    status, content_hash, citation_url, metadata_json, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_id) DO UPDATE SET
                    project_id=excluded.project_id, source_type=excluded.source_type,
                    resource_id=excluded.resource_id, title=excluded.title,
                    version=excluded.version, status=excluded.status,
                    content_hash=excluded.content_hash, citation_url=excluded.citation_url,
                    metadata_json=excluded.metadata_json, updated_at=excluded.updated_at
                """,
                (
                    source.source_id,
                    source.project_id,
                    source.source_type,
                    source.resource_id,
                    source.title,
                    source.version,
                    source.status,
                    source.content_hash,
                    source.citation_url,
                    json.dumps(source.metadata, ensure_ascii=False),
                    source.updated_at,
                ),
            )
            connection.execute("DELETE FROM knowledge_chunks WHERE source_id=?", (source_id,))
            if self._fts:
                connection.execute("DELETE FROM knowledge_fts WHERE source_id=?", (source_id,))
            for chunk in chunks:
                connection.execute(
                    """
                    INSERT INTO knowledge_chunks(
                        chunk_id, source_id, project_id, ordinal, locator, text, content_hash
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        chunk["chunk_id"],
                        source_id,
                        self.project_id,
                        chunk["ordinal"],
                        chunk["locator"],
                        chunk["text"],
                        chunk["content_hash"],
                    ),
                )
                if self._fts:
                    connection.execute(
                        """
                        INSERT INTO knowledge_fts(chunk_id, source_id, project_id, search_text)
                        VALUES(?,?,?,?)
                        """,
                        (
                            chunk["chunk_id"],
                            source_id,
                            self.project_id,
                            self._search_text(chunk["text"]),
                        ),
                    )
        return source

    def index_document(self, record: Any) -> KnowledgeSource:
        """供文档写入路径调用的生命周期钩子。"""
        return self.index_resource(
            source_type="document",
            resource_id=record.doc_id,
            title=record.filename,
            text=record.text,
            version=record.external_version,
            locator=record.filename,
            citation_url=f"/documents/{record.doc_id}/requirement",
            metadata={"external_source": record.external_source},
        )

    def index_suite(self, suite: Any) -> KnowledgeSource:
        """供用例集保存路径调用的生命周期钩子。"""
        text = "\n\n".join(
            f"{case.case_id} {case.title}\n"
            + "\n".join(f"{step.no}. {step.action} -> {step.expected}" for step in case.steps)
            + f"\n预期：{case.expected_result}\n数据：{case.data_text()}"
            for case in suite.cases
        )
        return self.index_resource(
            source_type="case",
            resource_id=suite.suite_id,
            title=suite.doc_title or suite.suite_id,
            text=text,
            version=str(suite.revision),
            locator=f"用例集 {suite.revision}",
            citation_url=f"/suites/{suite.suite_id}",
        )

    def delete_resource(self, *, source_type: KnowledgeSourceType, resource_id: str) -> bool:
        source_id = f"{source_type}:{resource_id}"
        with self._session() as connection:
            source = connection.execute(
                "SELECT source_id FROM knowledge_sources WHERE source_id=? AND project_id=?",
                (source_id, self.project_id),
            ).fetchone()
            if source is None:
                return False
            connection.execute(
                "UPDATE knowledge_sources SET status='deleted', updated_at=? WHERE source_id=?",
                (now_iso(), source_id),
            )
            connection.execute("DELETE FROM knowledge_chunks WHERE source_id=?", (source_id,))
            if self._fts:
                connection.execute("DELETE FROM knowledge_fts WHERE source_id=?", (source_id,))
        return True

    def search(self, request: KnowledgeSearchRequest) -> KnowledgeSearchResult:
        query = request.query.strip()
        if not query:
            return KnowledgeSearchResult(query=query, degraded_reason="查询为空。")
        limit = min(max(request.limit, 1), self.settings.knowledge_search_limit * 4, 30)
        source_types = set(request.source_types)
        rows: list[sqlite3.Row] = []
        reason = self.degraded_reason
        if self._fts:
            try:
                rows = self._fts_search(query, limit, request.include_expired, source_types)
            except sqlite3.OperationalError as exc:
                reason = f"FTS 查询失败，已使用兼容检索：{exc}"
                rows = []
        if not rows and not self._fts:
            rows = self._like_search(query, limit, request.include_expired, source_types)
        citations: list[KnowledgeCitation] = []
        for row in rows:
            citations.append(
                KnowledgeCitation(
                    citation_id=str(row["chunk_id"]),
                    source_id=str(row["source_id"]),
                    title=str(row["title"]),
                    source_type=str(row["source_type"]),  # type: ignore[arg-type]
                    version=str(row["version"] or ""),
                    locator=str(row["locator"] or ""),
                    url=str(row["citation_url"] or ""),
                    excerpt=truncate(str(row["text"]), 360),
                    score=float(row["score"] or 0.0),
                )
            )
        return KnowledgeSearchResult(
            query=query,
            citations=citations,
            total=len(citations),
            degraded_reason=reason,
        )

    def sync_all(self) -> KnowledgeIndexStats:
        before = self.stats()
        indexed = 0
        for source_id, title, text in HELP_DOCUMENTS:
            self.index_resource(
                source_type="help",
                resource_id=source_id,
                title=title,
                text=text,
                version=self.settings.app_version,
                locator="平台帮助",
                citation_url="/workspace?topic=help",
            )
            indexed += 1
        for record in self.repository.documents.list_recent(limit=10_000):
            self.index_resource(
                source_type="document",
                resource_id=record.doc_id,
                title=record.filename,
                text=record.text,
                version=record.external_version,
                locator=record.filename,
                citation_url=f"/documents/{record.doc_id}/requirement",
                metadata={"external_source": record.external_source},
            )
            indexed += 1
        for suite in self.repository.suites.list_recent(limit=10_000):
            text = "\n\n".join(
                f"{case.case_id} {case.title}\n"
                + "\n".join(f"{step.no}. {step.action} -> {step.expected}" for step in case.steps)
                + f"\n预期：{case.expected_result}\n数据：{case.data_text()}"
                for case in suite.cases
            )
            self.index_resource(
                source_type="case",
                resource_id=suite.suite_id,
                title=suite.doc_title or suite.suite_id,
                text=text,
                version=str(suite.revision),
                locator=f"用例集 {suite.revision}",
                citation_url=f"/suites/{suite.suite_id}",
            )
            indexed += 1
        for spec in self.repository.api_specs.list_recent(limit=10_000):
            text = "\n\n".join(
                f"{operation.method} {operation.path}\n{operation.summary}\n{operation.description}"
                for operation in spec.operations
            )
            self.index_resource(
                source_type="api_spec",
                resource_id=spec.spec_id,
                title=f"{spec.title} {spec.version}".strip(),
                text=text,
                version=spec.version,
                locator=spec.source_file,
                citation_url=f"/apis/{spec.spec_id}",
            )
            indexed += 1
        try:
            from app.report.store import list_reports

            reports, _ = list_reports(limit=1000, offset=0)
            for report in reports:
                text = json.dumps(report, ensure_ascii=False, default=str)
                self.index_resource(
                    source_type="report",
                    resource_id=str(report.get("id") or ""),
                    title=str(report.get("title") or "测试报告"),
                    text=text,
                    version=str(report.get("version") or ""),
                    locator="报告存档",
                    citation_url=f"/report/archive/{report.get('id')}",
                )
                indexed += 1
        except Exception:  # noqa: BLE001 - 报告索引失败不阻断其他知识源
            pass
        after = self.stats()
        return KnowledgeIndexStats(
            project_id=self.project_id,
            sources=after.sources,
            active_sources=after.active_sources,
            chunks=after.chunks,
            indexed=indexed,
            removed=max(before.sources - after.sources, 0),
            degraded_reason=self.degraded_reason,
        )

    def stats(self) -> KnowledgeIndexStats:
        with self._session() as connection:
            source_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM knowledge_sources WHERE project_id=?",
                    (self.project_id,),
                ).fetchone()[0]
            )
            active_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM knowledge_sources WHERE project_id=? AND status='active'",
                    (self.project_id,),
                ).fetchone()[0]
            )
            chunk_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM knowledge_chunks WHERE project_id=?",
                    (self.project_id,),
                ).fetchone()[0]
            )
        return KnowledgeIndexStats(
            project_id=self.project_id,
            sources=source_count,
            active_sources=active_count,
            chunks=chunk_count,
            degraded_reason=self.degraded_reason,
        )

    def _fts_search(
        self,
        query: str,
        limit: int,
        include_expired: bool,
        source_types: set[str],
    ) -> list[sqlite3.Row]:
        match = self._fts_query(query)
        if not match:
            return []
        filters = ["f.project_id = ?"]
        params: list[Any] = [match, self.project_id]
        if not include_expired:
            filters.append("s.status = 'active'")
        if source_types:
            placeholders = ",".join("?" for _ in source_types)
            filters.append(f"s.source_type IN ({placeholders})")
            params.extend(sorted(source_types))
        sql = f"""
            SELECT c.chunk_id, c.source_id, c.project_id, c.ordinal, c.locator, c.text,
                   s.title, s.source_type, s.version, s.citation_url,
                   bm25(knowledge_fts) AS score
            FROM knowledge_fts f
            JOIN knowledge_chunks c ON c.chunk_id = f.chunk_id
            JOIN knowledge_sources s ON s.source_id = c.source_id
            WHERE knowledge_fts MATCH ? AND {' AND '.join(filters)}
            ORDER BY score ASC, s.updated_at DESC
            LIMIT ?
        """
        params.append(limit)
        with self._session() as connection:
            return list(connection.execute(sql, params).fetchall())

    def _like_search(
        self,
        query: str,
        limit: int,
        include_expired: bool,
        source_types: set[str],
    ) -> list[sqlite3.Row]:
        clauses = ["c.project_id = ?", "c.text LIKE ?"]
        params: list[Any] = [self.project_id, f"%{query}%"]
        if not include_expired:
            clauses.append("s.status = 'active'")
        if source_types:
            placeholders = ",".join("?" for _ in source_types)
            clauses.append(f"s.source_type IN ({placeholders})")
            params.extend(sorted(source_types))
        params.append(limit)
        with self._session() as connection:
            return list(
                connection.execute(
                    f"""
                    SELECT c.chunk_id, c.source_id, c.project_id, c.ordinal, c.locator, c.text,
                           s.title, s.source_type, s.version, s.citation_url, 0.0 AS score
                    FROM knowledge_chunks c
                    JOIN knowledge_sources s ON s.source_id = c.source_id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY s.updated_at DESC LIMIT ?
                    """,
                    params,
                ).fetchall()
            )

    def _get_source(self, source_id: str) -> KnowledgeSource | None:
        with self._session() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_sources WHERE source_id=? AND project_id=?",
                (source_id, self.project_id),
            ).fetchone()
        if row is None:
            return None
        return KnowledgeSource(
            source_id=row["source_id"],
            project_id=row["project_id"],
            source_type=row["source_type"],
            resource_id=row["resource_id"],
            title=row["title"],
            version=row["version"],
            status=row["status"],
            content_hash=row["content_hash"],
            citation_url=row["citation_url"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            updated_at=row["updated_at"],
        )

    def _chunks(self, text: str, *, locator: str) -> list[dict[str, Any]]:
        content = (text or "").strip()
        if not content:
            return []
        size = max(self.settings.knowledge_chunk_size, 100)
        overlap = min(max(self.settings.knowledge_chunk_overlap, 0), size // 2)
        chunks: list[dict[str, Any]] = []
        start = 0
        ordinal = 0
        while start < len(content):
            end = min(start + size, len(content))
            if end < len(content):
                paragraph = content.rfind("\n\n", start + size // 2, end)
                if paragraph > start:
                    end = paragraph
            part = content[start:end].strip()
            if part:
                line_start = content.count("\n", 0, start) + 1
                line_end = content.count("\n", 0, end) + 1
                chunks.append(
                    {
                        "chunk_id": f"{self.project_id}:{ordinal}:{self._hash(part)[:16]}",
                        "ordinal": ordinal,
                        "locator": f"{locator or '正文'} · 第 {line_start}-{line_end} 行",
                        "text": part,
                        "content_hash": self._hash(part),
                    }
                )
                ordinal += 1
            start = end if end == len(content) else max(end - overlap, start + 1)
        return chunks

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _search_text(text: str) -> str:
        tokens: list[str] = []
        for match in _CJK_RE.finditer(text):
            run = match.group(0)
            tokens.extend(run)
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
        tokens.extend(_WORD_RE.findall(text.lower()))
        return " ".join(dict.fromkeys(tokens))

    @classmethod
    def _fts_query(cls, query: str) -> str:
        groups: list[str] = []
        for group in query.split():
            match = _CJK_RE.search(group)
            if match and len(match.group(0)) > 1:
                tokens = [
                    match.group(0)[index : index + 2]
                    for index in range(len(match.group(0)) - 1)
                ]
            else:
                tokens = cls._search_text(group).split()
            safe = [
                f'"{token.replace(chr(34), chr(34) * 2)}"'
                for token in dict.fromkeys(tokens)
                if token
            ]
            if safe:
                groups.append(f"({' OR '.join(safe[:12])})")
        return " AND ".join(groups[:6]) or f'"{query.replace(chr(34), chr(34) * 2)}"'


__all__ = ["HELP_DOCUMENTS", "KnowledgeService"]
