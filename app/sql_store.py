"""SQLAlchemy 持久化实现（V2.0 S6）。

与 :class:`app.repository.JsonObjectStore` **接口完全一致**，因此
``Repository`` 只需要换掉装配的存储实现，业务层（services / api）零改动。

存储模型刻意做得很薄：一张 ``objects`` 表，(kind, obj_id) 主键 + payload 文本
+ 更新时间。理由：

  1. 三种实体（文档 / 需求 / 用例集）的结构差异极大且会持续演进，
     把它们的字段拆成列意味着每次改模型都要写迁移；payload 存 JSON 则模型演进
     与存储解耦，与 V1.0 的 JSON 文件语义严格一致（同样的 model_dump_json）；
  2. SQLite 自带 JSON 函数，真需要按字段查询时仍可在 SQL 侧提取，
     不必为此重构表结构；
  3. 主键 (kind, obj_id) 天然隔离三类实体，避免三张表重复写同样的读写代码。

并发注意：FastAPI 的同步路由跑在线程池里，SQLite 连接默认禁止跨线程使用，
因此引擎必须显式 ``check_same_thread=False``，并为每次操作开一个短生命周期连接。
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    func,
    select,
)
from sqlalchemy.engine import Engine, make_url

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.repository import StorageCorruptedError, safe_id

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

METADATA = MetaData()

#: 唯一的物理表：三类实体共用，用 kind 区分。
OBJECTS = Table(
    "objects",
    METADATA,
    Column("kind", String(32), primary_key=True),
    Column("obj_id", String(128), primary_key=True),
    Column("payload", Text, nullable=False),
    Column("revision", Integer, nullable=False, default=0, server_default="0"),
    Column("updated_at", Float, nullable=False, index=True),
)


def create_db_engine(database_path: Path) -> Engine:
    """创建（并初始化）SQLite 引擎。"""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    url = make_url(f"sqlite:///{database_path.as_posix()}")
    engine = create_engine(
        url,
        # 同步路由在线程池里执行，连接必须允许跨线程使用。
        connect_args={"check_same_thread": False, "timeout": 15},
        future=True,
    )
    METADATA.create_all(engine)
    return engine


class SqlObjectStore(Generic[T]):
    """SQLAlchemy 版对象存储（与 JsonObjectStore 同接口）。"""

    def __init__(
        self,
        engine: Engine,
        model: type[T],
        *,
        kind: str,
        id_attr: str,
        label: str,
    ) -> None:
        self.engine = engine
        self.model = model
        self.kind = kind
        self.id_attr = id_attr
        self.label = label

    # ------------------------------------------------------------------ #
    def save(self, obj: T) -> T:
        obj_id = safe_id(getattr(obj, self.id_attr))
        payload = obj.model_dump_json(indent=2)
        revision = _revision_of(obj)
        with self.engine.begin() as connection:
            connection.execute(
                delete(OBJECTS).where(
                    OBJECTS.c.kind == self.kind, OBJECTS.c.obj_id == obj_id
                )
            )
            connection.execute(
                OBJECTS.insert().values(
                    kind=self.kind,
                    obj_id=obj_id,
                    payload=payload,
                    revision=revision,
                    updated_at=time.time(),
                )
            )
        logger.debug("保存 %s：%s", self.label, obj_id)
        return obj

    def get(self, obj_id: object) -> T:
        key = safe_id(obj_id)
        with self.engine.connect() as connection:
            row = connection.execute(
                select(OBJECTS.c.payload).where(
                    OBJECTS.c.kind == self.kind, OBJECTS.c.obj_id == key
                )
            ).first()
        if row is None:
            raise NotFoundError(
                f"{self.label}不存在：{obj_id}",
                detail={"kind": self.label, "id": str(obj_id)},
            )
        return self._load(row[0], key)

    def try_get(self, obj_id: object) -> T | None:
        try:
            return self.get(obj_id)
        except (NotFoundError, StorageCorruptedError):
            return None

    def exists(self, obj_id: object) -> bool:
        try:
            key = safe_id(obj_id)
        except NotFoundError:
            return False
        with self.engine.connect() as connection:
            row = connection.execute(
                select(OBJECTS.c.obj_id).where(
                    OBJECTS.c.kind == self.kind, OBJECTS.c.obj_id == key
                )
            ).first()
        return row is not None

    def delete(self, obj_id: object) -> bool:
        try:
            key = safe_id(obj_id)
        except NotFoundError:
            return False
        with self.engine.begin() as connection:
            result = connection.execute(
                delete(OBJECTS).where(OBJECTS.c.kind == self.kind, OBJECTS.c.obj_id == key)
            )
        return bool(result.rowcount)

    def list_recent(
        self, limit: int = 20, predicate: Callable[[T], bool] | None = None
    ) -> list[T]:
        """按更新时间倒序列出；predicate 必须先过滤再截断。

        顺序与 JsonObjectStore 保持一致：边筛边计数，够了就停 —— 先按 limit
        截断再过滤会给出「这条需求只生成过一两份用例集」的假读数。
        """
        cap = max(limit, 0)
        results: list[T] = []
        if cap == 0:
            return results
        statement = (
            select(OBJECTS.c.obj_id, OBJECTS.c.payload)
            .where(OBJECTS.c.kind == self.kind)
            .order_by(OBJECTS.c.updated_at.desc())
        )
        with self.engine.connect() as connection:
            for row in connection.execute(statement):
                obj = self._load(row[1], row[0])
                if predicate is not None and not predicate(obj):
                    continue
                results.append(obj)
                if len(results) >= cap:
                    break
        return results

    def count(self) -> int:
        with self.engine.connect() as connection:
            return int(
                connection.execute(
                    select(func.count()).select_from(OBJECTS).where(OBJECTS.c.kind == self.kind)
                ).scalar_one()
            )

    def list_ids(self) -> list[str]:
        with self.engine.connect() as connection:
            return [
                row[0]
                for row in connection.execute(
                    select(OBJECTS.c.obj_id).where(OBJECTS.c.kind == self.kind)
                )
            ]

    def iter_payloads(self) -> Iterator[dict[str, Any]]:
        """轻量遍历原始 payload（供统计口径使用，不做完整模型校验）。"""
        with self.engine.connect() as connection:
            for row in connection.execute(
                select(OBJECTS.c.payload).where(OBJECTS.c.kind == self.kind)
            ):
                try:
                    payload = json.loads(row[0])
                except (TypeError, ValueError):
                    continue
                if isinstance(payload, dict):
                    yield payload

    def _load(self, payload: str, obj_id: str) -> T:
        try:
            return self.model.model_validate_json(payload)
        except ValidationError as exc:
            raise StorageCorruptedError(
                f"{self.label}（{obj_id}）内容损坏，无法反序列化。",
                detail={"kind": self.kind, "id": obj_id, "error": exc.error_count()},
            ) from exc


def _revision_of(obj: BaseModel) -> int:
    try:
        return int(getattr(obj, "revision", 0) or 0)
    except (TypeError, ValueError):
        return 0


def max_revision(store: SqlObjectStore, *, filter_key: str, filter_value: str) -> int:
    """某分组（如 doc_id）下的最大版本号，用于用例版本管理。"""
    best = 0
    for payload in store.iter_payloads():
        if str(payload.get(filter_key) or "") != filter_value:
            continue
        try:
            best = max(best, int(payload.get("revision") or 0))
        except (TypeError, ValueError):
            continue
    return best


def migrate_payloads(engine: Engine, records: list[tuple[str, str, str, int]]) -> int:
    """把 ``(kind, obj_id, payload, revision)`` 批量写入（迁移脚本用）。"""
    written = 0
    with engine.begin() as connection:
        for kind, obj_id, payload, revision in records:
            connection.execute(
                delete(OBJECTS).where(OBJECTS.c.kind == kind, OBJECTS.c.obj_id == obj_id)
            )
            connection.execute(
                OBJECTS.insert().values(
                    kind=kind,
                    obj_id=obj_id,
                    payload=payload,
                    revision=revision,
                    updated_at=time.time(),
                )
            )
            written += 1
    return written


__all__ = [
    "METADATA",
    "OBJECTS",
    "SqlObjectStore",
    "create_db_engine",
    "max_revision",
    "migrate_payloads",
]
