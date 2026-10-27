"""助手会话窗口、轮次限制与基础频率限制。"""
from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from app.core.config import Settings, get_settings
from app.core.context import get_current_project_id
from app.core.exceptions import RateLimitError
from app.core.utils import new_id, now_iso, truncate
from app.repository import Repository, get_repository
from app.schemas.assistant import (
    AssistantAnswer,
    AssistantConversation,
    AssistantConversationSummary,
    AssistantTurn,
)


class AssistantRequestLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, project_id: str, *, limit: int) -> None:
        now = monotonic()
        with self._lock:
            window = self._events[project_id]
            while window and now - window[0] >= 60:
                window.popleft()
            if len(window) >= max(limit, 1):
                retry_after = max(1, int(60 - (now - window[0])))
                raise RateLimitError(
                    f"助手请求过快，每分钟最多 {limit} 次，请 {retry_after} 秒后重试。",
                    detail={"limit": limit, "retry_after_seconds": retry_after},
                )
            window.append(now)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


REQUEST_LIMITER = AssistantRequestLimiter()


class AssistantConversationService:
    def __init__(
        self,
        settings: Settings | None = None,
        repository: Repository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or get_repository()
        self.project_id = get_current_project_id() or "PRJ-default"

    def create(self) -> AssistantConversation:
        stamp = now_iso()
        conversation = AssistantConversation(
            conversation_id=new_id("CONV-"),
            project_id=self.project_id,
            created_at=stamp,
            updated_at=stamp,
        )
        self.repository.assistant_conversations.save(conversation)
        return conversation

    def get(self, conversation_id: str) -> AssistantConversation:
        conversation = self.repository.assistant_conversations.get(conversation_id)
        if conversation.project_id != self.project_id:
            from app.core.exceptions import NotFoundError

            raise NotFoundError(
                "助手会话不存在。",
                detail={"conversation_id": conversation_id},
            )
        # 旧版本曾把所有 warning 都误标为 degraded。新记录会保存真实原因，
        # 因此没有真实原因的旧 degraded 轮次按已完成回答读取。
        for item in conversation.messages:
            if (
                item.role == "assistant"
                and item.status == "degraded"
                and not item.degraded_reason
            ):
                item.status = "answered"
        return conversation

    def get_or_create(self, conversation_id: str) -> AssistantConversation:
        return self.get(conversation_id) if conversation_id else self.create()

    def add_user_turn(
        self,
        conversation: AssistantConversation,
        message: str,
    ) -> AssistantConversation:
        max_turns = max(1, min(self.settings.assistant_max_turns, 100))
        if conversation.turn_count >= max_turns:
            raise RateLimitError(
                f"当前对话已达到 {max_turns} 轮上限，请新建对话后继续。",
                detail={
                    "conversation_id": conversation.conversation_id,
                    "turns": conversation.turn_count,
                    "max_turns": max_turns,
                },
            )
        conversation.turn_count += 1
        if not conversation.title:
            conversation.title = truncate(message.replace("\n", " "), 80, suffix="")
        conversation.messages.append(AssistantTurn(role="user", content=message, created_at=now_iso()))
        conversation.updated_at = now_iso()
        self.repository.assistant_conversations.save(conversation)
        return conversation

    def add_assistant_turn(
        self,
        conversation: AssistantConversation,
        answer: AssistantAnswer | str,
    ) -> AssistantConversation:
        if isinstance(answer, AssistantAnswer):
            content = answer.answer
            status = answer.status
            mode = answer.mode
            knowledge_references = answer.knowledge_references
            web_citations = answer.web_citations
            warnings = answer.warnings
            degraded_reason = answer.degraded_reason
        else:
            content = answer
            status = ""
            mode = ""
            knowledge_references = []
            web_citations = []
            warnings = []
            degraded_reason = ""
        conversation.messages.append(
            AssistantTurn(
                role="assistant",
                content=truncate(content, 16_000, suffix=""),
                created_at=now_iso(),
                status=status,
                mode=mode,
                knowledge_references=knowledge_references,
                web_citations=web_citations,
                warnings=warnings,
                degraded_reason=degraded_reason,
            )
        )
        # 完整对话仍可查询，但只保留最大轮次范围内的消息，避免长期膨胀。
        max_messages = max(2, min(self.settings.assistant_max_turns, 100) * 2)
        conversation.messages = conversation.messages[-max_messages:]
        conversation.updated_at = now_iso()
        self.repository.assistant_conversations.save(conversation)
        return conversation

    def context_messages(
        self,
        conversation: AssistantConversation,
    ) -> list[AssistantTurn]:
        context_turns = max(1, min(self.settings.assistant_context_turns, 50))
        context_chars = max(200, min(self.settings.assistant_context_chars, 120_000))
        limit = context_turns * 2
        candidates = list(reversed(conversation.messages[-limit:]))
        selected: list[AssistantTurn] = []
        total_chars = 0
        for item in candidates:
            size = len(item.content)
            remaining = context_chars - total_chars
            if remaining <= 0:
                break
            if size > remaining:
                selected.append(
                    item.model_copy(update={"content": truncate(item.content, remaining, suffix="")})
                )
                break
            selected.append(item)
            total_chars += size
        selected.reverse()
        return selected

    def can_search_web(self, conversation: AssistantConversation) -> tuple[bool, str]:
        search_limit = max(0, min(self.settings.assistant_web_searches_per_conversation, 100))
        if conversation.web_search_count >= search_limit:
            return False, (
                f"当前对话已达到 {search_limit} 次联网检索上限。"
            )
        if conversation.last_web_search_at:
            from datetime import datetime

            try:
                elapsed = (
                    datetime.now().astimezone()
                    - datetime.fromisoformat(conversation.last_web_search_at)
                ).total_seconds()
            except ValueError:
                elapsed = self.settings.assistant_web_min_interval_seconds
            min_interval = max(0.0, min(self.settings.assistant_web_min_interval_seconds, 60.0))
            if elapsed < min_interval:
                return False, (
                    f"联网检索间隔至少 {min_interval:g} 秒，"
                    "本次先使用已有上下文回答。"
                )
        return True, ""

    def record_web_search(self, conversation: AssistantConversation) -> None:
        conversation.web_search_count += 1
        conversation.last_web_search_at = now_iso()
        conversation.updated_at = now_iso()
        self.repository.assistant_conversations.save(conversation)

    def list_recent(self, limit: int = 20) -> list[AssistantConversationSummary]:
        rows = self.repository.assistant_conversations.list_recent(
            min(max(limit, 1), 100),
            predicate=lambda item: item.project_id == self.project_id,
        )
        return [
            AssistantConversationSummary(
                conversation_id=item.conversation_id,
                title=item.title,
                turn_count=item.turn_count,
                web_search_count=item.web_search_count,
                updated_at=item.updated_at,
            )
            for item in rows
        ]


__all__ = [
    "AssistantConversationService",
    "AssistantRequestLimiter",
    "REQUEST_LIMITER",
]
