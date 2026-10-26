"""V2.3 工作事项、提醒和双存储回归。"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from app.core.config import Settings
from app.repository import Repository
from app.schemas.work_item import WorkItemCreate, WorkItemUpdate
from app.services.work_item_service import WorkItemService, local_now

API = "/api/v1"


def _settings(tmp_path: Path, backend: str = "json") -> Settings:
    settings = Settings(
        storage_dir=tmp_path / backend,
        storage_backend=backend,
        llm_provider="none",
        llm_api_key="",
    )
    settings.ensure_dirs()
    return settings


class TestWorkItemRoutes:
    def test_crud_filters_completion_and_summary(self, client) -> None:
        now = local_now()
        create = client.post(
            f"{API}/work-items",
            json={
                "item_type": "task",
                "title": "回归支付接口",
                "body": "检查 **超时重试** 与重复扣款。",
                "status": "todo",
                "priority": "P0",
                "due_at": now.replace(hour=23, minute=0, second=0, microsecond=0).isoformat(),
                "remind_at": (now - timedelta(minutes=1)).isoformat(),
                "tags": ["回归", "支付"],
                "pinned": True,
            },
        )
        assert create.status_code == 200, create.text
        item = create.json()["data"]
        assert item["tags"] == ["回归", "支付"]

        today = client.get(f"{API}/work-items", params={"view": "today"}).json()["data"]
        assert any(row["work_item_id"] == item["work_item_id"] for row in today)
        tagged = client.get(
            f"{API}/work-items", params={"view": "all", "tag": "支付", "priority": "P0"}
        ).json()["data"]
        assert len(tagged) == 1
        assert tagged[0]["pinned"] is True

        updated = client.put(
            f"{API}/work-items/{item['work_item_id']}",
            json={"body": "已补充证据", "status": "doing", "priority": "P1"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["data"]["body"] == "已补充证据"

        completed = client.post(f"{API}/work-items/{item['work_item_id']}/complete")
        assert completed.status_code == 200
        assert completed.json()["data"]["status"] == "done"
        done = client.get(f"{API}/work-items", params={"view": "completed"}).json()["data"]
        assert any(row["work_item_id"] == item["work_item_id"] for row in done)
        today_after = client.get(f"{API}/work-items", params={"view": "today"}).json()["data"]
        assert all(row["work_item_id"] != item["work_item_id"] for row in today_after)

    def test_reminder_poll_is_deduplicated_and_ack_is_idempotent(self, client) -> None:
        now = local_now()
        created = client.post(
            f"{API}/work-items",
            json={
                "item_type": "task",
                "title": "提醒只出现一次",
                "status": "todo",
                "priority": "P1",
                "remind_at": (now - timedelta(seconds=5)).isoformat(),
            },
        ).json()["data"]
        due = client.get(f"{API}/work-items/reminders/due").json()["data"]
        assert any(item["work_item_id"] == created["work_item_id"] for item in due)

        ack1 = client.post(
            f"{API}/work-items/reminders/ack",
            json={"ids": [created["work_item_id"], "WI-MISSING"]},
        )
        assert ack1.status_code == 200
        assert ack1.json()["data"][0]["reminded_at"]
        ack2 = client.post(
            f"{API}/work-items/reminders/ack",
            json={"ids": [created["work_item_id"]]},
        )
        assert ack2.status_code == 200
        saved = client.put(
            f"{API}/work-items/{created['work_item_id']}",
            json={
                "body": "只改正文，提醒时间保持原值",
                "remind_at": created["remind_at"],
            },
        )
        assert saved.status_code == 200
        assert saved.json()["data"]["reminded_at"]
        due_after = client.get(f"{API}/work-items/reminders/due").json()["data"]
        assert all(item["work_item_id"] != created["work_item_id"] for item in due_after)

    def test_invalid_fields_return_422_without_partial_update(self, client) -> None:
        created = client.post(
            f"{API}/work-items",
            json={"title": "待保持原样", "priority": "P2"},
        ).json()["data"]
        invalid = client.put(
            f"{API}/work-items/{created['work_item_id']}",
            json={"status": "unknown", "priority": "P0"},
        )
        assert invalid.status_code == 422
        current = client.get(f"{API}/work-items/{created['work_item_id']}").json()["data"]
        assert current["priority"] == "P2"
        assert current["title"] == "待保持原样"

        bad_date = client.put(
            f"{API}/work-items/{created['work_item_id']}",
            json={"due_at": "not-a-date"},
        )
        assert bad_date.status_code == 422
        assert bad_date.json()["code"] == "SCHEMA_VALIDATION_FAILED"


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_work_item_service_persists_across_repository_reopen(
    tmp_path: Path, backend: str
) -> None:
    settings = _settings(tmp_path, backend)
    service = WorkItemService(settings, Repository(settings))
    item = service.create(
        WorkItemCreate(
            item_type="note",
            title="跨重启笔记",
            body="# 保留\n\n这段正文必须留在本地。",
            tags=["本地"],
        )
    )
    service.update(item.work_item_id, WorkItemUpdate(pinned=True, status="doing"))

    reopened = Repository(settings)
    loaded = reopened.work_items.get(item.work_item_id)
    assert loaded.title == "跨重启笔记"
    assert loaded.body.startswith("# 保留")
    assert loaded.pinned is True
    assert loaded.status == "doing"
