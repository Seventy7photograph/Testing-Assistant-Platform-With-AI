"""Jira Cloud / Data Center 双向同步适配器。"""
from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

import httpx

from app.core.exceptions import ConflictError
from app.integrations.base import ADAPTER_BUILDERS, ExternalSyncAdapter, SyncResult
from app.schemas.integrations import ExternalRequirement, ExternalStatus
from app.schemas.testcase import TestCaseSuite


def _adf_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if value.get("type") == "text":
            return str(value.get("text") or "")
        return "\n".join(_adf_text(item) for item in value.get("content") or [])
    if isinstance(value, list):
        return "\n".join(_adf_text(item) for item in value)
    return ""


class JiraAdapter(ExternalSyncAdapter):
    name = "jira"
    label = "Jira"

    def _base(self, options: dict[str, Any] | None) -> str:
        base = str((options or {}).get("base_url") or self.settings.jira_base_url).strip().rstrip("/")
        if not base:
            raise self.missing_config(self.label, "JIRA_BASE_URL")
        if not base.startswith(("https://", "http://")):
            raise ConflictError("JIRA_BASE_URL 必须是 http(s) 地址。")
        return base

    def _headers(self, options: dict[str, Any] | None) -> dict[str, str]:
        token = str((options or {}).get("token") or self.settings.jira_token).strip()
        email = str((options or {}).get("email") or self.settings.jira_email).strip()
        if not token:
            raise self.missing_config(self.label, "JIRA_TOKEN")
        if not email:
            raise self.missing_config(self.label, "JIRA_EMAIL")
        encoded = base64.b64encode(f"{email}:{token}".encode()).decode()
        return {"Authorization": f"Basic {encoded}", "Accept": "application/json"}

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
                    f"{self._base(options)}/rest/api/3/myself",
                    headers=self._headers(options),
                )
                response.raise_for_status()
            return True, "Jira 鉴权与连通性正常。"
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
        project = (project_key or self.settings.jira_project_key).strip()
        if not project:
            raise self.missing_config(self.label, "JIRA_PROJECT_KEY")
        jql = str((options or {}).get("jql") or f'project = "{project}" ORDER BY updated DESC')
        body = {
            "jql": jql,
            "maxResults": min(int((options or {}).get("limit") or 50), 100),
            "fields": ["summary", "description", "status", "updated", "labels", "issuetype"],
        }
        async with self._client() as client:
            response = await client.post(
                f"{self._base(options)}/rest/api/3/search/jql",
                headers={**self._headers(options), "Content-Type": "application/json"},
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
        items: list[ExternalRequirement] = []
        base = self._base(options)
        for issue in payload.get("issues") or []:
            key = str(issue.get("key") or issue.get("id") or "")
            fields = issue.get("fields") or {}
            status = fields.get("status") or {}
            items.append(
                ExternalRequirement(
                    external_id=key,
                    title=str(fields.get("summary") or key),
                    body=_adf_text(fields.get("description")).strip() or str(fields.get("summary") or ""),
                    status=str(status.get("name") or ""),
                    url=f"{base}/browse/{quote(key)}",
                    version=str(fields.get("updated") or ""),
                    updated_at=str(fields.get("updated") or ""),
                    metadata={"labels": fields.get("labels") or []},
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
        project = (project_key or self.settings.jira_project_key).strip()
        issue_key = str((options or {}).get("issue_key") or "").strip()
        base = self._base(options)
        headers = {**self._headers(options), "Content-Type": "application/json"}
        lines = [f"- {item.case_id or '-'} · {item.title} · {item.priority.value}" for item in suite.cases]
        summary = f"[测试工程师助手] {suite.doc_title or suite.suite_id} · {len(suite.cases)} 条用例"
        if issue_key:
            description = "用例同步：\n" + "\n".join(lines)
            async with self._client() as client:
                response = await client.post(
                    f"{base}/rest/api/3/issue/{quote(issue_key)}/comment",
                    headers=headers,
                    json={
                        "body": {
                            "type": "doc",
                            "version": 1,
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": description}],
                                }
                            ],
                        }
                    },
                )
                response.raise_for_status()
            return SyncResult(
                success=True,
                external_ids=[issue_key],
                message=f"已把 {len(suite.cases)} 条用例回写到 Jira {issue_key} 评论。",
            )
        if not (options or {}).get("create_issue", True):
            raise ConflictError("未指定 issue_key，且 create_issue=false，无法回写。")
        if not project:
            raise self.missing_config(self.label, "JIRA_PROJECT_KEY")
        issue_type = str((options or {}).get("issue_type") or "Task")
        async with self._client() as client:
            response = await client.post(
                f"{base}/rest/api/3/issue",
                headers=headers,
                json={
                    "fields": {
                        "project": {"key": project},
                        "issuetype": {"name": issue_type},
                        "summary": summary,
                        "description": {
                            "type": "doc",
                            "version": 1,
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "\n".join(lines)}],
                                }
                            ],
                        },
                    }
                },
            )
            response.raise_for_status()
            payload = response.json()
        external_id = str(payload.get("key") or payload.get("id") or "")
        return SyncResult(
            success=bool(external_id),
            external_ids=[external_id] if external_id else [],
            message=f"已在 Jira 创建测试任务 {external_id}。",
        )

    async def read_status(
        self,
        external_id: str,
        *,
        options: dict[str, Any] | None = None,
    ) -> ExternalStatus:
        async with self._client() as client:
            response = await client.get(
                f"{self._base(options)}/rest/api/3/issue/{quote(external_id)}"
                "?fields=summary,status,updated",
                headers=self._headers(options),
            )
            response.raise_for_status()
            payload = response.json()
        fields = payload.get("fields") or {}
        return ExternalStatus(
            external_id=external_id,
            title=str(fields.get("summary") or ""),
            status=str((fields.get("status") or {}).get("name") or ""),
            updated_at=str(fields.get("updated") or ""),
            url=f"{self._base(options)}/browse/{quote(external_id)}",
        )


ADAPTER_BUILDERS.register("jira", JiraAdapter)

__all__ = ["JiraAdapter"]
