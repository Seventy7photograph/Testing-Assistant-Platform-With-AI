"""一次性迁移：把 storage/data 下的 JSON 文件导入 SQLite（V2.0 S6）。

用法：
    python scripts/migrate_json_to_sqlite.py            # 迁移（幂等，可重跑）
    python scripts/migrate_json_to_sqlite.py --dry-run  # 只统计，不写库
    python scripts/migrate_json_to_sqlite.py --rollback # 反向导出回 JSON 文件

为什么必须提供这个脚本：切库是显式动作，而使用者的数据全在 JSON 文件里。
没有迁移路径的「后端可切换」等于逼人手动搬数据，实际结果就是没人敢切。

回滚说明：``--rollback`` 会把数据库里的对象按原来的目录结构写回
``storage/data/{documents,requirements,suites}/*.json``；因此在迁移到 SQLite 后
**不要立刻删除原 JSON 文件** —— 保留它们就是最省事的备份。确认新后端工作正常后再清理。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402
from app.sql_store import OBJECTS, create_db_engine  # noqa: E402

#: 目录名 -> (kind, id 字段)。与 Repository 的装配保持一致。
COLLECTIONS: dict[str, tuple[str, str]] = {
    "documents": ("documents", "doc_id"),
    "requirements": ("requirements", "doc_id"),
    "suites": ("suites", "suite_id"),
}


def collect_records(data_dir: Path) -> tuple[list[tuple[str, str, str, int]], dict[str, int]]:
    records: list[tuple[str, str, str, int]] = []
    counts: dict[str, int] = {}
    for folder, (kind, id_attr) in COLLECTIONS.items():
        directory = data_dir / folder
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                print(f"  ! 跳过无法解析的文件 {path.name}：{exc}")
                continue
            if not isinstance(payload, dict):
                print(f"  ! 跳过非对象内容 {path.name}")
                continue
            obj_id = str(payload.get(id_attr) or path.stem)
            try:
                revision = int(payload.get("revision") or 0)
            except (TypeError, ValueError):
                revision = 0
            records.append((kind, obj_id, json.dumps(payload, ensure_ascii=False), revision))
            counts[folder] = counts.get(folder, 0) + 1
    return records, counts


def run_migration(*, dry_run: bool) -> int:
    settings = get_settings()
    settings.ensure_dirs()
    data_dir = settings.data_dir
    records, counts = collect_records(data_dir)

    print(f"存储目录：{data_dir}")
    if not counts:
        print("未发现任何 JSON 数据，无需迁移。")
        return 0
    for folder, count in counts.items():
        print(f"  {folder}: {count} 条")
    print(f"合计 {len(records)} 条。")

    if dry_run:
        print("--dry-run：未写入数据库。")
        return 0

    engine = create_db_engine(settings.db_path)
    from app.sql_store import migrate_payloads

    written = migrate_payloads(engine, records)
    print(f"已写入 {settings.db_path}（{written} 条）。")
    print("提示：请确认新后端工作正常后再清理原 JSON 文件；它们就是回滚备份。")
    return written


def run_rollback() -> int:
    settings = get_settings()
    engine = create_db_engine(settings.db_path)
    from sqlalchemy import select

    imported = 0
    with engine.connect() as connection:
        for kind, folder in ((kind, folder) for folder, (kind, _) in COLLECTIONS.items()):
            directory = settings.data_dir / folder
            directory.mkdir(parents=True, exist_ok=True)
            rows = connection.execute(
                select(OBJECTS.c.obj_id, OBJECTS.c.payload).where(OBJECTS.c.kind == kind)
            ).all()
            for obj_id, payload in rows:
                path = directory / f"{obj_id}.json"
                path.write_text(payload, encoding="utf-8")
                imported += 1
            print(f"  {folder}: 导出 {len(rows)} 条")
    print(f"已从 {settings.db_path} 导出 {imported} 条到 JSON。")
    return imported


def main() -> int:
    parser = argparse.ArgumentParser(description="JSON 存储 -> SQLite 存储的一次性迁移")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写库")
    parser.add_argument("--rollback", action="store_true", help="反向导出：SQLite -> JSON")
    args = parser.parse_args()
    setup_logging("WARNING")
    if args.rollback:
        return 0 if run_rollback() >= 0 else 1
    return 0 if run_migration(dry_run=args.dry_run) >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
