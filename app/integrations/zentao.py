"""禅道 REST API 双向同步适配器。

不同部署版本的路径存在差异，因此关键路径可由 options 覆盖；
默认使用官方 v1 REST 路径。离线 fixture 不依赖实例。
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from app.core.exceptions import ConflictError
from app.integrations.base import ADAPTER_BUILDERS, ExternalSyncAdapter, SyncResult
from app.schemas.integrations import ExternalRequirement, ExternalStatus
from app.schemas.testcase import TestCaseSuite


class ZentaoAdapter(ExternalSyncAdapter):
    name = "zentao"
    label = "禅道"

    def _base(self, options: dict[str, Any] | None) -> str:
        base = str((options or {}).get("base_url") or self.settings.zentao_base_url).strip().rstrip("/")
        if not base:
            raise self.missing_config(self.label, "ZENTAO_BASE_URL")
        if not base.startswith(("https://", "http://")):
            raise ConflictError("ZENTAO_BASE_URL 必须是 http(s) 地址。")
        return base

    def _headers(self, options: dict[str, Any] | None) -> dict[str, str]:
        token = str((options or {}).get("token") or self.settings.zentao_token).strip()
        if not token:
            raise self.missing_config(self.label, "ZENTAO_TOKEN")
        return {"Token": token, "Accept": "application/json"}

    def _path(self, options: dict[str, Any] | None, key: str, default: str) -> str:
        return str((options or {}).get(key) or default)

    async def health_check(
        self,
        *,
        project_key: str = "",
        options: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        if self.fixture_requirements(options):
            return True, "离线 fixture 模式可用。"
        try:
            async with self._client() as client:
                response = await client.get(
                    f"{self._base(options)}{self._path(options, 'health_path', '/api.php/v1/user')}",
                    headers=self._headers(options),
                )
                response.raise_for_status()
            return True, "禅道鉴权与连通性正常。"
        except (ConflictError, httpx.HTTPError) as exc:
            return False, str(getattr(exc, "message", exc))

    async def pull_requirements(
        self,
        *,
        project_key: str = "",
        options: dict[str, Any] | None = None,
    ) -> list[ExternalRequirement]:
        fixture = self.fixture_requirements(options)
        if fixture:
            return fixture
        project = (project_key or self.settings.zentao_project_key).strip()
        if not project:
            raise self.missing_config(self.label, "ZENTAO_PROJECT_KEY")
        path = self._path(
            options,
            "stories_path",
            f"/api.php/v1/projects/{quote(project)}/stories",
        )
        async with self._client() as client:
            response = await client.get(
                f"{self._base(options)}{path}",
                headers=self._headers(options),
                params={"limit": min(int((options or {}).get("limit") or 50), 100)},
            )
            response.raise_for_status()
            payload = response.json()
        raw = payload.get("stories") or payload.get("data") or []
        if isinstance(raw, dict):
            raw = raw.get("stories") or raw.get("items") or []
        items: list[ExternalRequirement] = []
        for story in raw if isinstance(raw, list) else []:
            external_id = str(story.get("id") or story.get("storyID") or "")
            items.append(
                ExternalRequirement(
                    external_id=external_id,
                    title=str(story.get("title") or story.get("name") or external_id),
                    body=str(story.get("spec") or story.get("description") or ""),
                    status=str(story.get("status") or ""),
                    url=f"{self._base(options)}{self._path(options, 'story_web_path', '/story-view-')}"
                    f"{quote(external_id)}.html",
                    version=str(story.get("version") or ""),
                    updated_at=str(story.get("lastEditedDate") or story.get("updatedAt") or ""),
                )
            )
        return items

    async def push_cases(
        self,
        suite: TestCaseSuite,
        *,
        project_key: str = "",
        options: dict[str, Any] | None = None,
    ) -> SyncResult:
        fixture = (options or {}).get("push_external_ids")
        if isinstance(fixture, list):
            ids = [str(item) for item in fixture if str(item)]
            return SyncResult(
                success=True,
                external_ids=ids,
                message=f"离线 fixture 已模拟回写 {len(ids)} 个外部对象。",
            )
        project = (project_key or self.settings.zentao_project_key).strip()
        if not project:
            raise self.missing_config(self.label, "ZENTAO_PROJECT_KEY")
        path = self._path(options, "testcases_path", "/api.php/v1/testcases")
        created: list[str] = []
        async with self._client() as client:
            for case in suite.cases:
                response = await client.post(
                    f"{self._base(options)}{path}",
                    headers={**self._headers(options), "Content-Type": "application/json"},
                    json={
                        "product": int(project) if project.isdigit() else project,
                        "title": case.title,
                        "steps": [
                            {"desc": step.action, "expect": step.expected}
                            for step in case.steps
                        ],
                        "type": case.case_type.value,
                        "pri": int(case.priority.value.removeprefix("P")),
                    },
                )
                response.raise_for_status()
                payload = response.json()
                data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
                case_id = str(data.get("id") or data.get("caseID") or "")
                if case_id:
                    created.append(case_id)
        return SyncResult(
            success=len(created) == len(suite.cases),
            external_ids=created,
            message=f"已向禅道回写 {len(created)}/{len(suite.cases)} 条用例。",
            warnings=[] if len(created) == len(suite.cases) else ["部分用例未返回外部 ID。"],
        )

    async def read_status(
        self,
        external_id: str,
        *,
        options: dict[str, Any] | None = None,
    ) -> ExternalStatus:
        path = self._path(options, "story_detail_path", f"/api.php/v1/stories/{quote(external_id)}")
        async with self._client() as client:
            response = await client.get(
                f"{self._base(options)}{path}",
                headers=self._headers(options),
            )
            response.raise_for_status()
            payload = response.json()
        data = payload.get("story") or payload.get("data") or payload
        return ExternalStatus(
            external_id=external_id,
            title=str(data.get("title") or data.get("name") or ""),
            status=str(data.get("status") or ""),
            updated_at=str(data.get("lastEditedDate") or data.get("updatedAt") or ""),
            url=f"{self._base(options)}{self._path(options, 'story_web_path', '/story-view-')}"
            f"{quote(external_id)}.html",
        )


ADAPTER_BUILDERS.register("zentao", ZentaoAdapter)

__all__ = ["ZentaoAdapter"]
