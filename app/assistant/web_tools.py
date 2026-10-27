"""DeepSeek Search / Fetch 与兼容端点的受控网页工具。"""
from __future__ import annotations

import asyncio
import ipaddress
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger, sanitize_log_text
from app.core.utils import truncate
from app.schemas.assistant import AssistantStatus, WebCitation

logger = get_logger(__name__)


@dataclass(slots=True)
class WebResearch:
    citations: list[WebCitation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    used: bool = False
    status: str = ""


class AssistantWebClient:
    """只允许 Search / Fetch 两个只读操作，不执行网页中的任何指令。"""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        client_factory: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.transport = transport
        self.client_factory = client_factory or httpx.AsyncClient

    def status(self) -> AssistantStatus:
        base_url, api_key, provider, reason = self._configuration()
        if not self.settings.assistant_web_search_enabled:
            reason = "联网检索已在服务端关闭。"
        available = bool(base_url and api_key and reason == "")
        return AssistantStatus(
            model_available=False,
            web_search_available=available,
            web_search_provider=provider,
            web_search_reason=reason,
            max_turns=max(1, min(self.settings.assistant_max_turns, 100)),
            context_turns=max(1, min(self.settings.assistant_context_turns, 50)),
            context_chars=max(200, min(self.settings.assistant_context_chars, 120_000)),
            rate_limit_per_minute=max(
                1, min(self.settings.assistant_rate_limit_per_minute, 120)
            ),
            web_searches_per_conversation=max(
                0, min(self.settings.assistant_web_searches_per_conversation, 100)
            ),
            web_fetch_limit=max(0, min(self.settings.assistant_web_fetch_limit, 10)),
            web_fetch_chars=max(
                500, min(self.settings.assistant_web_fetch_chars, 50_000)
            ),
            max_output_tokens=max(
                512, min(self.settings.assistant_max_output_tokens, 32_768)
            ),
        )

    async def research(
        self,
        query: str,
        *,
        direct_url: str = "",
    ) -> WebResearch:
        base_url, api_key, _provider, reason = self._configuration()
        if not base_url or not api_key:
            return WebResearch(status=reason or "网页检索不可用。")
        if direct_url:
            try:
                page = await self._fetch(direct_url, base_url=base_url, api_key=api_key)
                content = self._page_content(page)
            except ExternalServiceError as exc:
                return WebResearch(status=exc.message, warnings=[exc.message])
            citation = WebCitation(
                citation_id="W1",
                title=str(page.get("title") or direct_url),
                url=direct_url,
                site_name=urlparse(direct_url).hostname or "",
                content_excerpt=content,
                fetched=True,
            )
            return WebResearch(
                citations=[citation],
                used=True,
                status="direct_url_fetch",
            )

        clean_query = " ".join(query.replace("\x00", " ").split())[:128]
        if not clean_query:
            return WebResearch(status="联网检索词为空。")
        try:
            payload = await self._search(
                clean_query,
                count=max(1, min(self.settings.assistant_web_search_max_results, 8)),
                base_url=base_url,
                api_key=api_key,
            )
        except ExternalServiceError as exc:
            return WebResearch(status=exc.message, warnings=[exc.message])
        raw_results = payload.get("results")
        if not isinstance(raw_results, list) or not raw_results:
            return WebResearch(status="联网检索没有返回结果。")

        warnings: list[str] = []
        citations: list[WebCitation] = []
        fetch_candidates: list[tuple[int, dict[str, Any]]] = []
        for index, raw in enumerate(raw_results, start=1):
            if not isinstance(raw, dict):
                continue
            url = str(raw.get("url") or "").strip()
            if not self._safe_public_url(url):
                warnings.append(f"已跳过不安全的网页地址：{truncate(url, 120)}")
                continue
            citation = WebCitation(
                citation_id=f"W{index}",
                title=str(raw.get("title") or url),
                url=url,
                site_name=str(raw.get("site_name") or ""),
                snippet=str(raw.get("snippet") or ""),
                summary=str(raw.get("summary") or ""),
                content_excerpt=truncate(
                    str(raw.get("content") or raw.get("summary") or raw.get("snippet") or ""),
                    600,
                ),
                published_at=str(raw.get("date") or ""),
                authority=int(raw.get("authority") or -1),
                rerank_score=float(raw.get("rerank_score") or 0),
            )
            citations.append(citation)
            fetch_candidates.append((len(citations) - 1, raw))

        fetch_limit = min(
            max(0, min(self.settings.assistant_web_fetch_limit, 10)),
            len(fetch_candidates),
        )
        for index, raw in fetch_candidates[:fetch_limit]:
            try:
                page = await self._fetch(
                    citations[index].url,
                    base_url=base_url,
                    api_key=api_key,
                )
            except ExternalServiceError as exc:
                warnings.append(f"{citations[index].url} 抓取失败：{exc.message}")
                continue
            citations[index].title = str(page.get("title") or citations[index].title)
            citations[index].content_excerpt = self._page_content(page)
            citations[index].fetched = True

        return WebResearch(citations=citations, warnings=warnings, used=True, status="searched")

    async def fetch_url(self, url: str) -> dict[str, str]:
        base_url, api_key, _provider, reason = self._configuration()
        if not base_url or not api_key:
            raise ExternalServiceError(reason or "网页抓取不可用。")
        page = await self._fetch(url, base_url=base_url, api_key=api_key)
        return {
            "title": str(page.get("title") or ""),
            "content": str(page.get("content") or ""),
        }

    async def _search(
        self,
        query: str,
        *,
        count: int,
        base_url: str,
        api_key: str,
    ) -> dict[str, Any]:
        return await self._post(
            self._endpoint(base_url, "search"),
            {"query": query, "count": count, "need_content": False},
            api_key=api_key,
        )

    async def _fetch(
        self,
        url: str,
        *,
        base_url: str,
        api_key: str,
    ) -> dict[str, Any]:
        if not self._safe_public_url(url):
            raise ExternalServiceError("网页地址不合法、包含凭据或指向本地/私网地址。")
        return await self._post(
            self._endpoint(base_url, "fetch"),
            {"url": url},
            api_key=api_key,
        )

    def _page_content(self, page: dict[str, Any]) -> str:
        content = str(page.get("content") or "").strip()
        if not content:
            raise ExternalServiceError("网页抓取未返回可用的 Markdown 正文。")
        max_chars = max(500, min(self.settings.assistant_web_fetch_chars, 50_000))
        return truncate(content, max_chars, suffix="\n\n[正文已按服务端上限截断]")

    async def _post(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        api_key: str,
    ) -> dict[str, Any]:
        client_kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(self.settings.assistant_web_search_timeout, connect=8.0),
            "follow_redirects": False,
        }
        if self.transport is not None:
            client_kwargs["transport"] = self.transport
        last_error = ""
        for attempt in range(2):
            try:
                async with self.client_factory(**client_kwargs) as client:
                    response = await client.post(
                        endpoint,
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                    )
            except httpx.TimeoutException as exc:
                last_error = f"网页工具请求超时（>{self.settings.assistant_web_search_timeout:g}s）"
                if attempt == 0:
                    await asyncio.sleep(0.4)
                    continue
                raise ExternalServiceError(last_error) from exc
            except httpx.HTTPError as exc:
                raise ExternalServiceError(
                    f"网页工具请求失败：{sanitize_log_text(exc)}"
                ) from exc

            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError as exc:
                    raise ExternalServiceError("网页工具返回体不是合法 JSON。") from exc
                if not isinstance(data, dict):
                    raise ExternalServiceError("网页工具返回体结构不符合预期。")
                return data

            last_error = self._http_error(response.status_code, response.text)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 0:
                    retry_after = response.headers.get("retry-after", "0.5")
                    try:
                        delay = min(max(float(retry_after), 0.2), 2.0)
                    except ValueError:
                        delay = 0.5
                    await asyncio.sleep(delay)
                    continue
            raise ExternalServiceError(last_error, detail={"status_code": response.status_code})
        raise ExternalServiceError(last_error or "网页工具请求失败。")

    def _configuration(self) -> tuple[str, str, str, str]:
        if not self.settings.assistant_web_search_enabled:
            return "", "", "none", "联网检索已在服务端关闭。"
        provider = (self.settings.llm_provider or "none").strip().lower()
        explicit_base = (self.settings.assistant_web_search_base_url or "").strip()
        explicit_key = (self.settings.assistant_web_search_api_key or "").strip()
        if explicit_base:
            if not explicit_key:
                return "", "", "configured", "已配置联网端点，但缺少 ASSISTANT_WEB_SEARCH_API_KEY。"
            parsed = urlparse(explicit_base)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                return "", "", "configured", "ASSISTANT_WEB_SEARCH_BASE_URL 必须是有效的 HTTP(S) 地址。"
            return explicit_base.rstrip("/"), explicit_key, "configured", ""
        if provider == "deepseek":
            key = (self.settings.llm_api_key or "").strip()
            if not key:
                return "", "", "deepseek", "DeepSeek Search / Fetch 需要 LLM_API_KEY。"
            base = (self.settings.llm_base_url or "https://api.deepseek.com").rstrip("/")
            return base, key, "deepseek", ""
        return (
            "",
            "",
            provider,
            "当前模型未声明 Search / Fetch 能力；可配置 "
            "ASSISTANT_WEB_SEARCH_BASE_URL 与 ASSISTANT_WEB_SEARCH_API_KEY 启用兼容端点。",
        )

    @staticmethod
    def _endpoint(base_url: str, operation: str) -> str:
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        return f"{base}/v1/tools/{operation}"

    @staticmethod
    def _safe_public_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                return False
            if parsed.username or parsed.password or len(url) > 8192:
                return False
            hostname = parsed.hostname.rstrip(".").lower()
            if hostname in {"localhost"} or hostname.endswith(".local"):
                return False
            try:
                address = ipaddress.ip_address(hostname)
            except ValueError:
                return True
            return not (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_reserved
                or address.is_multicast
            )
        except ValueError:
            return False

    @staticmethod
    def _http_error(status_code: int, body: str) -> str:
        messages = {
            400: "网页工具请求参数不合法。",
            401: "DeepSeek API Key 缺失或无效。",
            402: "账户余额不足，无法使用联网工具。",
            403: "网页抓取被安全策略拒绝。",
            404: "网页不可访问、无可用正文或不受支持。",
            408: "网页工具读取请求超时。",
            413: "网页工具请求体过大。",
            429: "联网工具触发 QPS 限制，请稍后再试。",
            500: "联网工具内部错误。",
            504: "联网工具下游请求超时。",
        }
        return messages.get(status_code, f"联网工具返回 HTTP {status_code}：{truncate(body, 160)}")


__all__ = ["AssistantWebClient", "WebResearch"]
