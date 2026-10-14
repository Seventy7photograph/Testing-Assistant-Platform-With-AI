"""持久化层：JSON 文件与 SQLAlchemy(SQLite) 双实现，业务层无感知。

V1.0 用 JSON 文件存储（零外部依赖、开箱即跑）；V2.0 S6 补上
``SqlObjectStore``（见 app/sql_store.py），两者接口完全一致，由
``STORAGE_BACKEND`` 在 :func:`build_repository` 里选一个装配。

为什么默认仍是 json：既有用户的数据都在 ``storage/data/*.json``，默认切到
SQLite 会让升级后"数据凭空消失"。切库是一次显式动作（``STORAGE_BACKEND=sqlite``
+ ``scripts/migrate_json_to_sqlite.py``），并在启动日志里给出提示。
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterator
from functools import lru_cache
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError, NotFoundError
from app.core.logging import get_logger
from app.schemas.document import DocumentRecord
from app.schemas.requirement import RequirementDoc
from app.schemas.testcase import TestCaseSuite

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

SAFE_ID_RE = re.compile(r"[^0-9A-Za-z_\-]")


class StorageCorruptedError(AppError):
    code = "STORAGE_CORRUPTED"
    http_status = 500
    default_message = "本地存储数据损坏，无法读取"


def safe_id(raw: object) -> str:
    """把外部传入的 ID 规整为安全文件名，杜绝路径穿越。"""
    cleaned = SAFE_ID_RE.sub("", str(raw or ""))
    if not cleaned:
        raise NotFoundError("非法的资源 ID。", detail={"raw": str(raw)})
    return cleaned


class JsonObjectStore(Generic[T]):
    """把 Pydantic 模型以 JSON 文件形式落盘（一对象一文件）。"""

    def __init__(self, directory: Path, model: type[T], *, id_attr: str, label: str) -> None:
        self.directory = Path(directory)
        self.model = model
        self.id_attr = id_attr
        self.label = label
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, obj_id: object) -> Path:
        return self.directory / f"{safe_id(obj_id)}.json"

    def save(self, obj: T) -> T:
        obj_id = getattr(obj, self.id_attr)
        path = self.path_for(obj_id)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(obj.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp_path, path)
        logger.debug("保存 %s：%s", self.label, path.name)
        return obj

    def exists(self, obj_id: object) -> bool:
        try:
            return self.path_for(obj_id).exists()
        except NotFoundError:
            return False

    def get(self, obj_id: object) -> T:
        path = self.path_for(obj_id)
        if not path.exists():
            raise NotFoundError(
                f"{self.label}不存在：{obj_id}",
                detail={"kind": self.label, "id": str(obj_id)},
            )
        try:
            return self.model.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as exc:
            raise StorageCorruptedError(
                f"{self.label}（{obj_id}）内容损坏，无法反序列化。",
                detail={"path": str(path), "error": exc.error_count()},
            ) from exc
        except OSError as exc:
            raise StorageCorruptedError(
                f"{self.label}（{obj_id}）读取失败：{exc}", detail={"path": str(path)}
            ) from exc

    def try_get(self, obj_id: object) -> T | None:
        try:
            return self.get(obj_id)
        except (NotFoundError, StorageCorruptedError):
            return None

    def delete(self, obj_id: object) -> bool:
        path = self.path_for(obj_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_recent(
        self, limit: int = 20, predicate: Callable[[T], bool] | None = None
    ) -> list[T]:
        """按修改时间倒序列出；``predicate`` 必须**先过滤再截断**。

        顺序反了会得到「这条需求只生成过一两份」这种假象——文件先被 limit 砍掉一半，
        再去筛其中属于该需求的，剩下的自然少。所以这里换成了「边筛边计数，够了就停」。
        """
        files = sorted(self.directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        cap = max(limit, 0)
        results: list[T] = []
        for path in files:
            if len(results) >= cap:
                break
            try:
                obj = self.model.model_validate_json(path.read_text(encoding="utf-8"))
            except (ValidationError, OSError):
                logger.warning("跳过损坏的存储文件：%s", path.name)
                continue
            if predicate is None or predicate(obj):
                results.append(obj)
        return results

    def count(self) -> int:
        return len(list(self.directory.glob("*.json")))

    def list_ids(self) -> list[str]:
        """全部对象 ID（不反序列化内容）。"""
        return [path.stem for path in self.directory.glob("*.json")]

    def iter_payloads(self) -> Iterator[dict]:
        """轻量遍历原始 payload：统计口径只需要少数字段，没必要构造完整模型。"""
        for path in self.directory.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.warning("跳过损坏的存储文件：%s", path.name)
                continue
            if isinstance(payload, dict):
                yield payload


class Repository:
    """业务侧统一门面（依赖倒置：业务只依赖它，不依赖具体存储实现）。

    ``documents`` / ``requirements`` / ``suites`` 三个集合在后端切换时只换类型，
    方法签名逐个对齐，因此 services 与 api 层一行都不用改。
    """

    BACKEND_JSON = "json"
    BACKEND_SQLITE = "sqlite"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.backend = normalize_backend(getattr(self.settings, "storage_backend", self.BACKEND_JSON))
        self.engine = None
        if self.backend == self.BACKEND_SQLITE:
            self._build_sql_collections()
        else:
            self._build_json_collections()

    # ------------------------------------------------------------------ #
    # 装配
    # ------------------------------------------------------------------ #
    def _build_json_collections(self) -> None:
        base = self.settings.data_dir
        self.documents: JsonObjectStore[DocumentRecord] = JsonObjectStore(
            base / "documents", DocumentRecord, id_attr="doc_id", label="文档"
        )
        self.requirements: JsonObjectStore[RequirementDoc] = JsonObjectStore(
            base / "requirements", RequirementDoc, id_attr="doc_id", label="需求解析结果"
        )
        self.suites: JsonObjectStore[TestCaseSuite] = JsonObjectStore(
            base / "suites", TestCaseSuite, id_attr="suite_id", label="用例集"
        )

    def _build_sql_collections(self) -> None:
        # 延迟导入：只用 JSON 后端时不必依赖 SQLAlchemy。
        from app.sql_store import SqlObjectStore, create_db_engine

        self.engine = create_db_engine(self.settings.db_path)
        self.documents = SqlObjectStore(
            self.engine, DocumentRecord, kind="documents", id_attr="doc_id", label="文档"
        )
        self.requirements = SqlObjectStore(
            self.engine, RequirementDoc, kind="requirements", id_attr="doc_id", label="需求解析结果"
        )
        self.suites = SqlObjectStore(
            self.engine, TestCaseSuite, kind="suites", id_attr="suite_id", label="用例集"
        )
        self._warn_if_json_left_behind()

    def _warn_if_json_left_behind(self) -> None:
        """切到 SQLite 但库里是空的、而 JSON 里有数据时，明确提示去做迁移。

        不提示的后果很具体：升级后打开界面一片空白，使用者会以为"数据丢了"。
        """
        try:
            if self.documents.count() or self.requirements.count() or self.suites.count():
                return
        except Exception:  # noqa: BLE001 - 统计失败不影响主流程
            return
        legacy = self.settings.data_dir
        stale = [
            folder
            for folder in ("documents", "requirements", "suites")
            if any((legacy / folder).glob("*.json"))
        ]
        if stale:
            logger.warning(
                "已启用 SQLite 存储，但数据库为空，而 %s 下仍有 JSON 数据（%s）。"
                "如需沿用既有数据，请先执行：python scripts/migrate_json_to_sqlite.py",
                legacy,
                "、".join(stale),
            )

    def count_cases(self) -> int:
        """全部用例集的用例总数。

        只读 `stats.total`，不构造完整模型：一份用例集可能含成百上千条用例，
        为首页一个数字把所有用例完整反序列化一遍并不划算。
        """
        total = 0
        for payload in self.suites.iter_payloads():
            stats = payload.get("stats")
            if not isinstance(stats, dict):
                continue
            try:
                total += int(stats.get("total") or 0)
            except (TypeError, ValueError):
                continue
        return total

    def count_linked_requirements(self) -> int:
        """只统计仍能追溯到源文档的解析结果。

        需求解析结果以 doc_id 为键：从粘贴文本解析出来的结果带的是合成 ID，
        源文档删除后遗留的结果也没有可导航的入口。这类记录在界面里既看不到、
        也删不掉，**不能计入总览**，否则总览会出现一个无法追溯的数字。
        """
        return sum(
            1
            for doc_id in self.requirements.list_ids()
            if self.documents.exists(doc_id)
        )

    def referenced_requirement_ids(self) -> set[str]:
        """全部用例集引用到的需求 ID（轻量读取，不反序列化用例明细）。"""
        ids: set[str] = set()
        for payload in self.suites.iter_payloads():
            doc_id = payload.get("doc_id")
            if isinstance(doc_id, str) and doc_id:
                ids.add(doc_id)
        return ids

    def purge_orphan_requirements(self) -> int:
        """清理孤立的解析结果：既没有源文档、也不再被任何用例集引用。

        粘贴文本生成用例时会为需求合成一个 ID 并落盘，这样用例集详情页才能
        渲染需求追溯矩阵。但当最后一份引用它的用例集被删除后，这个文件就再也
        没有任何入口了——不清理就会在 storage/data/requirements 里无限堆积。
        """
        referenced = self.referenced_requirement_ids()
        removed = 0
        for doc_id in self.requirements.list_ids():
            if doc_id in referenced or self.documents.exists(doc_id):
                continue
            if self.requirements.delete(doc_id):
                removed += 1
        if removed:
            logger.info("已清理 %d 份孤立的解析结果", removed)
        return removed

    # ------------------------------------------------------------------ #
    # 用例版本管理（V2.0 S6）
    # ------------------------------------------------------------------ #
    def next_suite_revision(self, doc_id: str) -> int:
        """同一条需求的上一次生成版本号 + 1。

        以 doc_id 分组而不是全局自增：使用者关心的是「这条需求我生成过几版」，
        全局序号只会给出「第 37 版」这种没有信息量的读数。
        """
        best = 0
        for payload in self.suites.iter_payloads():
            if str(payload.get("doc_id") or "") != doc_id:
                continue
            try:
                best = max(best, int(payload.get("revision") or 0))
            except (TypeError, ValueError):
                continue
        return best + 1

    def save_suite(self, suite: TestCaseSuite) -> TestCaseSuite:
        """保存用例集并补齐版本号（未显式指定时自动递增）。"""
        if not suite.revision:
            suite.revision = self.next_suite_revision(suite.doc_id)
        return self.suites.save(suite)

    def suite_history(self, doc_id: str, *, limit: int = 10) -> list[TestCaseSuite]:
        """同一需求的历史用例集（按版本号倒序）。"""
        suites = self.suites.list_recent(max(limit, 1) * 5, predicate=lambda item: item.doc_id == doc_id)
        suites.sort(key=lambda item: item.revision, reverse=True)
        return suites[: max(limit, 1)]


def normalize_backend(raw: object) -> str:
    """把配置值规整为受支持的后端名，未知值回落 json 并告警。"""
    name = str(raw or "").strip().lower()
    if name in (Repository.BACKEND_SQLITE, "sql", "sqlalchemy", "db"):
        return Repository.BACKEND_SQLITE
    if name in ("", Repository.BACKEND_JSON, "file", "files"):
        return Repository.BACKEND_JSON
    logger.warning("未知的 STORAGE_BACKEND=%s，已回落为 json。", raw)
    return Repository.BACKEND_JSON


def build_repository(settings: Settings | None = None) -> Repository:
    """按 STORAGE_BACKEND 装配仓储（业务层不感知具体存储）。"""
    return Repository(settings)


@lru_cache(maxsize=1)
def get_repository() -> Repository:
    return build_repository(get_settings())


def reset_repository_cache() -> None:
    get_repository.cache_clear()
