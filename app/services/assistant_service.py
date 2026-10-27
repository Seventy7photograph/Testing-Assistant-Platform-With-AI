"""对话式知识助手：模型回答、受控工具、网页检索与会话窗口。"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.agent.tools_readonly import ReadonlyToolbox, ToolObservation
from app.assistant.web_tools import AssistantWebClient, WebResearch
from app.core.config import Settings, get_settings
from app.core.context import get_current_project_id
from app.core.exceptions import LLMError
from app.core.logging import sanitize_log_text
from app.core.utils import dump_json, truncate
from app.llm.base import LLMMessage, LLMProvider, assistant, user
from app.llm.factory import get_llm_provider
from app.llm.prompts import PROMPT_ASSISTANT_ANSWER, build_assistant_answer_messages
from app.repository import Repository, get_repository
from app.schemas.assistant import (
    AssistantAnswer,
    AssistantAskRequest,
    AssistantClaim,
    AssistantFactGroup,
    AssistantLink,
    AssistantStatus,
)
from app.schemas.knowledge import KnowledgeCitation
from app.services.assistant_conversation_service import (
    AssistantConversationService,
    REQUEST_LIMITER,
)
from app.services.evidence import detect_prompt_injection
from app.services.job_service import JobService

_HEALTH_RE = re.compile(r"(不可用|故障|异常|健康|降级|为什么|why|unavailable|health|degrad)", re.I)
_RECENT_RE = re.compile(r"(最近|生成|新增|recent|latest)", re.I)
_WORK_RE = re.compile(r"(今天|待办|逾期|事项|任务提醒|todo|overdue)", re.I)
_JOB_RE = re.compile(r"(任务|作业|job|执行状态|运行状态)", re.I)
_WEB_RE = re.compile(
    r"(新闻|最新|近期|实时|发布|版本|价格|官网|搜索|网页|"
    r"news|latest|current|release|pricing|search|web|2026)",
    re.I,
)
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
_WEB_CITATION_RE = re.compile(r"\[(W\d+)\]")


class _LLMAssistantAnswer(BaseModel):
    answer: str = Field(default="")
    model_inferences: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AssistantService:
    def __init__(
        self,
        settings: Settings | None = None,
        repository: Repository | None = None,
        *,
        llm: LLMProvider | None = None,
        web_client: AssistantWebClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or get_repository()
        self.llm = llm
        self.web = web_client or AssistantWebClient(self.settings)
        self.jobs = JobService(self.settings, self.repository)
        self.conversations = AssistantConversationService(self.settings, self.repository)

    def status(self) -> AssistantStatus:
        provider = self.llm or get_llm_provider()
        status = self.web.status()
        status.model_available = provider.available
        status.model_provider = provider.name
        status.model_name = provider.model
        status.model_reason = provider.degraded_reason
        return status

    async def ask(self, payload: AssistantAskRequest) -> AssistantAnswer:
        project_id = get_current_project_id() or "PRJ-default"
        REQUEST_LIMITER.check(
            project_id,
            limit=self.settings.assistant_rate_limit_per_minute,
        )
        conversation = self.conversations.get_or_create(payload.conversation_id)
        context_turns = self.conversations.context_messages(conversation)
        conversation = self.conversations.add_user_turn(conversation, payload.message)
        run = self.jobs.create_agent_run(
            payload.message,
            conversation_id=conversation.conversation_id,
        )

        toolbox = ReadonlyToolbox(self.settings, self.repository)
        observations: list[ToolObservation] = []
        call_records: list[dict[str, Any]] = []
        warnings = [
            f"用户输入包含疑似指令注入，已按数据处理：{item}"
            for item in detect_prompt_injection(payload.message)
        ]
        degradation_reasons: list[str] = []

        def invoke(name: str, **kwargs: Any) -> ToolObservation | None:
            try:
                observation = toolbox.call(name, **kwargs)
            except Exception as exc:  # noqa: BLE001 - 单个工具失败不能伪造其余事实
                call = self.jobs.record_tool_call(
                    run=run,
                    tool_name=name,
                    status="failed",
                    arguments=kwargs,
                    result={},
                    error=str(exc),
                )
                call_records.append(
                    {
                        "tool_call_id": call.tool_call_id,
                        "tool_name": name,
                        "status": "failed",
                        "error": call.error,
                    }
                )
                return None
            observations.append(observation)
            call = self.jobs.record_tool_call(
                run=run,
                tool_name=name,
                status="succeeded",
                arguments=kwargs,
                result={"summary": observation.summary},
            )
            call_records.append(
                {
                    "tool_call_id": call.tool_call_id,
                    "tool_name": name,
                    "status": "succeeded",
                    "summary": observation.summary,
                }
            )
            return observation

        invoke("assistant_context", current_path=payload.current_path)
        facts: list[AssistantFactGroup] = []
        answer_parts: list[str] = []
        matched = False

        if _HEALTH_RE.search(payload.message):
            matched = True
            observation = invoke("health_status")
            if observation:
                data = observation.data
                claims = [
                    AssistantClaim(text=f"平台状态：{data.get('status')}。", evidence="health_status")
                ]
                claims.append(
                    AssistantClaim(
                        text=(
                            f"模型：{data.get('llm_provider')} / {data.get('llm_model')}，"
                            f"可用={data.get('llm_available')}。"
                        ),
                        evidence="health_status",
                    )
                )
                if not data.get("llm_available"):
                    claims.append(
                        AssistantClaim(
                            text=f"模型降级原因：{data.get('degraded_reason') or '未配置'}。",
                            evidence="health_status",
                        )
                    )
                facts.append(AssistantFactGroup(label="当前平台状态", claims=claims))
                answer_parts.append(observation.summary)

        if _RECENT_RE.search(payload.message):
            matched = True
            observation = invoke("recent_resources")
            if observation:
                data = observation.data
                claims = [
                    AssistantClaim(
                        text=(
                            f"用例集「{item['title'] or item['id']}」"
                            f"共 {item['cases']} 条，版本 {item['revision']}。"
                        ),
                        evidence="recent_resources",
                    )
                    for item in data.get("suites", [])[:3]
                ]
                facts.append(AssistantFactGroup(label="当前最近资源", claims=claims))
                answer_parts.append(observation.summary)

        if _WORK_RE.search(payload.message):
            matched = True
            today = invoke("work_items_today")
            overdue = invoke("work_items_overdue")
            today_items = today.data.get("items", []) if today else []
            overdue_items = overdue.data.get("items", []) if overdue else []
            facts.append(
                AssistantFactGroup(
                    label="当前工作事项",
                    claims=[
                        AssistantClaim(text=f"今日事项 {len(today_items)} 条。", evidence="work_items_today"),
                        AssistantClaim(
                            text=f"逾期事项 {len(overdue_items)} 条。",
                            evidence="work_items_overdue",
                        ),
                    ],
                )
            )
            answer_parts.append(f"今天有 {len(today_items)} 条事项；逾期 {len(overdue_items)} 条。")

        if _JOB_RE.search(payload.message) and not _WORK_RE.search(payload.message):
            matched = True
            observation = invoke("job_status")
            if observation:
                jobs = observation.data.get("jobs", [])
                facts.append(
                    AssistantFactGroup(
                        label="当前任务状态",
                        claims=[
                            AssistantClaim(
                                text=f"{item['kind']}：{item['status']}。",
                                evidence="job_status",
                            )
                            for item in jobs[:5]
                        ],
                    )
                )
                answer_parts.append(observation.summary)

        knowledge_query = (
            "平台安全 提示注入 只读工具 边界"
            if warnings
            else self._knowledge_query(payload.message)
        )
        knowledge = invoke(
            "knowledge_search",
            query=knowledge_query,
            limit=self.settings.assistant_max_knowledge_results,
        )
        citations: list[KnowledgeCitation] = list(knowledge.citations) if knowledge else []

        direct_url = (_URL_RE.search(payload.message) or [None])[0] if _URL_RE.search(payload.message) else ""
        wants_web = bool(payload.allow_web_search and (direct_url or _WEB_RE.search(payload.message)))
        web_research = WebResearch(status="未请求联网检索。")
        if wants_web:
            allowed, reason = self.conversations.can_search_web(conversation)
            web_status = self.web.status()
            if not allowed:
                web_research.status = reason
                warnings.append(reason)
                degradation_reasons.append(reason)
            elif not web_status.web_search_available:
                web_research.status = web_status.web_search_reason
                reason = (
                    "本次未联网核验："
                    + (web_status.web_search_reason or "当前模型不支持网页工具。")
                )
                warnings.append(reason)
                degradation_reasons.append(reason)
            else:
                web_research = await self.web.research(
                    payload.message,
                    direct_url=direct_url or "",
                )
                if web_research.used:
                    self.conversations.record_web_search(conversation)
                    call = self.jobs.record_tool_call(
                        run=run,
                        tool_name="web_fetch" if direct_url else "web_search",
                        status="succeeded",
                        arguments={"query": payload.message[:128], "url": direct_url},
                        result={
                            "results": len(web_research.citations),
                            "status": web_research.status,
                        },
                    )
                    call_records.append(
                        {
                            "tool_call_id": call.tool_call_id,
                            "tool_name": call.tool_name,
                            "status": call.status,
                            "summary": f"{len(web_research.citations)} 条网页引用",
                        }
                    )
                warnings.extend(web_research.warnings)
                if not web_research.used:
                    degradation_reasons.append(
                        web_research.status or "联网检索未返回可用结果。"
                    )
                web_text = json.dumps(
                    [item.model_dump(mode="json") for item in web_research.citations],
                    ensure_ascii=False,
                )
                warnings.extend(
                    f"网页内容包含疑似注入，已按资料处理：{item}"
                    for item in detect_prompt_injection(web_text)
                )

        current_facts_text = self._format_observations(observations)
        knowledge_context = self._format_knowledge(citations)
        web_context = self._format_web(web_research.citations)
        llm = self.llm or get_llm_provider()
        provider_reason = llm.degraded_reason
        llm_warnings: list[str] = []
        llm_degradation_reasons: list[str] = []
        model_inferences: list[AssistantClaim] = []
        llm_used = False
        final_answer = ""

        if llm.available:
            history = self._history_messages(context_turns)
            messages = build_assistant_answer_messages(
                payload.message,
                history=history,
                current_facts=current_facts_text,
                knowledge_context=knowledge_context,
                web_context=web_context,
                web_status=web_research.status,
                now=datetime.now().astimezone().isoformat(timespec="minutes"),
            )
            try:
                response = await llm.complete_json(
                    messages,
                    prompt=PROMPT_ASSISTANT_ANSWER,
                    max_tokens=self.settings.assistant_max_output_tokens,
                    retries=1,
                    expect=dict,
                )
                parsed = _LLMAssistantAnswer.model_validate(response.parsed or {})
                final_answer = parsed.answer.strip()
                llm_warnings = [sanitize_log_text(item, 500) for item in parsed.warnings if item]
                known_web_ids = {item.citation_id for item in web_research.citations}
                unknown_web_ids = sorted(set(_WEB_CITATION_RE.findall(final_answer)) - known_web_ids)
                if unknown_web_ids:
                    reason = (
                        "模型引用了不存在的网页编号，已保留为待核对内容："
                        + "、".join(unknown_web_ids[:8])
                    )
                    llm_warnings.append(reason)
                    llm_degradation_reasons.append(reason)
                for item in parsed.model_inferences:
                    text = str(item.get("text") or "").strip()
                    if text:
                        model_inferences.append(
                            AssistantClaim(
                                text=sanitize_log_text(text, 2000),
                                evidence=sanitize_log_text(item.get("evidence") or "", 500),
                            )
                        )
                llm_used = bool(final_answer)
                if not final_answer:
                    llm_warnings.append("模型返回了空回答，已使用确定性结果。")
                    llm_degradation_reasons.append("模型返回了空回答。")
            except LLMError as exc:
                llm_warnings.append(f"模型回答失败，已降级：{exc.message}")
                llm_degradation_reasons.append(f"模型回答失败：{exc.message}")
            except Exception as exc:  # noqa: BLE001 - 结构化输出异常统一降级
                logger.warning("助手回答解析失败：%s", exc)
                llm_warnings.append("模型回答结构不合法，已使用确定性结果。")
                llm_degradation_reasons.append("模型回答结构不合法。")
        else:
            llm_warnings.append(
                "当前未配置可用模型；已使用平台确定性事实与知识检索结果。"
            )
            llm_degradation_reasons.append(
                provider_reason or "当前未配置可用模型，已使用确定性结果。"
            )

        if not final_answer:
            fallback_parts = list(answer_parts)
            if citations:
                fallback_parts.append(
                    "项目知识命中：" + "；".join(item.title for item in citations[:3]) + "。"
                )
            if web_research.citations:
                fallback_parts.append(
                    "网页参考：" + "；".join(
                        f"[{item.citation_id}] {item.title}"
                        for item in web_research.citations[:3]
                    )
                )
            if fallback_parts:
                final_answer = "\n\n".join(dict.fromkeys(fallback_parts))
            else:
                final_answer = (
                    "当前没有可用的模型回答，也没有足够的确定性工具结果或知识引用。"
                    "请补充项目资源 ID、具体测试问题，或配置可用模型后重试。"
                )

        all_warnings = list(dict.fromkeys([*warnings, *llm_warnings]))
        all_degradation_reasons = list(
            dict.fromkeys([*degradation_reasons, *llm_degradation_reasons])
        )
        degraded_reason = "；".join(all_degradation_reasons)[:1_000]
        status = "degraded" if all_degradation_reasons else "answered"
        mode = "web_assisted" if web_research.used else ("llm_assisted" if llm_used else "deterministic")
        result = AssistantAnswer(
            run_id=run.run_id,
            conversation_id=conversation.conversation_id,
            turn_index=conversation.turn_count,
            turn_limit=max(1, min(self.settings.assistant_max_turns, 100)),
            context_messages=len(context_turns),
            status=status,
            answer=truncate(final_answer, 40_000, suffix=""),
            mode=mode,
            current_facts=facts,
            knowledge_references=citations,
            web_citations=web_research.citations,
            web_search_used=web_research.used,
            web_search_status=web_research.status,
            model_inferences=model_inferences,
            links=self._links(observations),
            tool_calls=call_records,
            warnings=all_warnings,
            degraded_reason=degraded_reason,
        )
        self.conversations.add_assistant_turn(conversation, result)
        self.jobs.finish_agent_run(
            run,
            status="succeeded",
            response=result.answer,
            citation_ids=[
                *(item.citation_id for item in citations),
                *(item.citation_id for item in web_research.citations),
            ],
            tool_call_ids=[item["tool_call_id"] for item in call_records],
            error=degraded_reason,
        )
        return result

    @staticmethod
    def _history_messages(turns: list[Any]) -> list[LLMMessage]:
        messages: list[LLMMessage] = []
        for item in turns:
            if item.role == "user":
                messages.append(user(item.content))
            elif item.role == "assistant":
                messages.append(assistant(item.content))
        return messages

    @staticmethod
    def _format_observations(observations: list[ToolObservation]) -> str:
        rows = [
            {
                "tool": item.name,
                "summary": item.summary,
                "data": item.data,
            }
            for item in observations
        ]
        return dump_json(rows, indent=None)

    @staticmethod
    def _format_knowledge(citations: list[KnowledgeCitation]) -> str:
        return "\n\n".join(
            f"[K{index}] {item.title}\n"
            f"类型：{item.source_type}，版本：{item.version or '-'}，定位：{item.locator}\n"
            f"摘录：{item.excerpt}"
            for index, item in enumerate(citations, start=1)
        )

    @staticmethod
    def _format_web(citations: list[Any]) -> str:
        return "\n\n".join(
            f"[{item.citation_id}] {item.title}\n"
            f"URL: {item.url}\n"
            f"站点：{item.site_name or '-'}；发布时间：{item.published_at or '-'}；"
            f"权威度：{item.authority}；相关度：{item.rerank_score}\n"
            f"摘要：{item.summary or item.snippet}\n"
            f"正文摘录：{item.content_excerpt}"
            for item in citations
        )

    @staticmethod
    def _knowledge_query(message: str) -> str:
        text = message.strip()
        text = re.sub(
            r"(忽略|无视|forget|ignore).{0,40}(指令|规则|instruction|prompt)",
            " ",
            text,
            flags=re.I,
        )
        return text[:300] or "平台帮助 排障"

    @staticmethod
    def _links(observations: list[ToolObservation]) -> list[AssistantLink]:
        seen: set[str] = set()
        links: list[AssistantLink] = []
        for observation in observations:
            for link in observation.links:
                if link.href in seen:
                    continue
                seen.add(link.href)
                links.append(link)
        return links


__all__ = ["AssistantService"]
