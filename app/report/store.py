"""本地存档：SQLite。

刻意保持零依赖、零运维 —— 单文件、可拷贝、可删除，
适配"内网自部署 / 单人使用"的实际场景。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import db_path
from .metrics import excerpt

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id            TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    title         TEXT,
    version       TEXT,
    model         TEXT NOT NULL,
    provider      TEXT,
    instruction   TEXT,
    source_data   TEXT,
    report        TEXT,
    metrics_json  TEXT,
    defects_json  TEXT,
    usage_json    TEXT,
    warnings_json TEXT,
    elapsed_ms    INTEGER DEFAULT 0,
    verdict       TEXT DEFAULT 'unknown',
    verdict_label TEXT DEFAULT '无法判定',
    pass_rate     REAL,
    total         INTEGER,
    failed        INTEGER,
    blocked       INTEGER
);
CREATE INDEX IF NOT EXISTS idx_reports_created ON reports (created_at DESC);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _session() -> Iterator[sqlite3.Connection]:
    """一个连接 = 一个事务，结束时提交并**关闭**。

    `with sqlite3.connect(...)` 只管事务、不关连接，靠 GC 回收句柄；
    长跑时用显式的关闭更稳。
    """

    _ensure_schema()
    conn = _connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


_initialized_paths: set[str] = set()


def init_db() -> None:
    """建表（幂等）。应用启动时调用一次；未调用时首次读写也会自动补建。"""

    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        with conn:
            conn.executescript(_SCHEMA)
    finally:
        conn.close()
    _initialized_paths.add(str(path))


def _ensure_schema() -> None:
    """延迟初始化：让不经过 app lifespan 的调用方（脚本 / 单测）也能直接用。"""

    if str(db_path()) not in _initialized_paths:
        init_db()


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def save_report(payload: dict[str, Any]) -> str:
    report_id = payload.get("id") or new_id()
    metrics = payload.get("metrics") or {}
    with _session() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO reports (
                id, created_at, title, version, model, provider, instruction,
                source_data, report, metrics_json, defects_json, usage_json,
                warnings_json, elapsed_ms, verdict, verdict_label,
                pass_rate, total, failed, blocked
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                payload.get("created_at") or utc_now_iso(),
                payload.get("title"),
                payload.get("version"),
                payload.get("model") or "",
                payload.get("provider") or "",
                payload.get("instruction") or "",
                payload.get("source_data") or "",
                payload.get("report") or "",
                json.dumps(metrics, ensure_ascii=False) if metrics else None,
                json.dumps(payload.get("defects") or [], ensure_ascii=False),
                json.dumps(payload.get("usage"), ensure_ascii=False) if payload.get("usage") else None,
                json.dumps(payload.get("warnings") or [], ensure_ascii=False),
                int(payload.get("elapsed_ms") or 0),
                metrics.get("verdict", "unknown"),
                metrics.get("verdict_label", "无法判定"),
                metrics.get("pass_rate"),
                metrics.get("total"),
                metrics.get("failed"),
                metrics.get("blocked"),
            ),
        )
    return report_id


def _summary(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "version": row["version"],
        "model": row["model"],
        "provider": row["provider"] or "",
        "created_at": row["created_at"],
        "elapsed_ms": row["elapsed_ms"] or 0,
        "verdict": row["verdict"] or "unknown",
        "verdict_label": row["verdict_label"] or "无法判定",
        "pass_rate": row["pass_rate"],
        "total": row["total"],
        "failed": row["failed"],
        "blocked": row["blocked"],
        "excerpt": excerpt(row["report"] or ""),
    }


def _detail(row: sqlite3.Row) -> dict[str, Any]:
    item = _summary(row)
    item.update(
        {
            "instruction": row["instruction"] or "",
            "source_data": row["source_data"] or "",
            "report": row["report"] or "",
            "metrics": _loads(row["metrics_json"], None),
            "defects": _loads(row["defects_json"], []),
            "usage": _loads(row["usage_json"], None),
            "warnings": _loads(row["warnings_json"], []),
        }
    )
    return item


def list_reports(
    limit: int = 20,
    offset: int = 0,
    query: str | None = None,
    verdict: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    where: list[str] = []
    params: list[Any] = []

    if query:
        where.append(
            "(title LIKE ? OR version LIKE ? OR model LIKE ? OR report LIKE ?)"
        )
        like = f"%{query}%"
        params.extend([like, like, like, like])
    if verdict and verdict != "all":
        where.append("verdict = ?")
        params.append(verdict)

    clause = f"WHERE {' AND '.join(where)}" if where else ""

    with _session() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM reports {clause}", params
        ).fetchone()["n"]
        rows = conn.execute(
            f"SELECT * FROM reports {clause} ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return [_summary(row) for row in rows], int(total)


def get_report(report_id: str) -> dict[str, Any] | None:
    with _session() as conn:
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    return _detail(row) if row else None


def delete_report(report_id: str) -> bool:
    with _session() as conn:
        cursor = conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    return cursor.rowcount > 0


def count_reports() -> int:
    with _session() as conn:
        return int(conn.execute("SELECT COUNT(*) AS n FROM reports").fetchone()["n"])


def trend_points(limit: int = 12) -> list[dict[str, Any]]:
    """按时间正序返回最近若干轮的可比指标，供趋势图使用。"""

    with _session() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, version, title, verdict, verdict_label,
                   pass_rate, total, failed, blocked
            FROM reports
            WHERE pass_rate IS NOT NULL AND total > 0
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    points = []
    for row in reversed(rows):
        label = row["version"] or row["title"] or row["created_at"][:10]
        points.append(
            {
                "id": row["id"],
                "label": label,
                "created_at": row["created_at"],
                "pass_rate": row["pass_rate"] or 0.0,
                "total": row["total"] or 0,
                "failed": row["failed"] or 0,
                "blocked": row["blocked"] or 0,
                "verdict": row["verdict"] or "unknown",
                "verdict_label": row["verdict_label"] or "无法判定",
            }
        )
    return points
