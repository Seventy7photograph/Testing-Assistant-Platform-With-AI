<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { api } from "@/api";
import { getActiveProjectId } from "@/api/client";
import type {
  AssistantAnswer,
  AssistantStatus,
  AssistantWebCitation,
} from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import MarkdownBody from "@/components/MarkdownBody.vue";
import { useProjectStore } from "@/stores/project";

interface AssistantEntry {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  answer?: AssistantAnswer;
  pending?: boolean;
  error?: string;
}

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ (e: "close"): void }>();

const route = useRoute();
const projects = useProjectStore();
const message = ref("");
const turns = ref<AssistantEntry[]>([]);
const loading = ref(false);
const loadingHistory = ref(false);
const indexing = ref(false);
const error = ref("");
const allowWeb = ref(true);
const assistantStatus = ref<AssistantStatus | null>(null);
const conversationId = ref(readConversationId());
const turnCount = ref(0);
const turnLimit = ref(30);
const inputRef = ref<HTMLTextAreaElement | null>(null);
const panelRef = ref<HTMLElement | null>(null);
const bodyRef = ref<HTMLElement | null>(null);
let indexed = false;
let statusLoaded = false;
let previousFocus: HTMLElement | null = null;
let pendingCounter = 0;
let stateVersion = 0;
const inertTargets: HTMLElement[] = [];

const prompts = [
  "平台为什么不可用？",
  "最近生成了什么？",
  "今天还有什么事项？",
];

const turnBlocked = computed(() => turnCount.value >= turnLimit.value);
const webCapabilityLabel = computed(() => {
  if (!assistantStatus.value) return "检查联网";
  return assistantStatus.value.web_search_available ? "联网可用" : "联网不可用";
});
const webCapabilityTitle = computed(() => {
  const status = assistantStatus.value;
  if (!status) return "正在检查服务端联网能力";
  if (status.web_search_available) {
    return `${status.web_search_provider || "网页工具"}：可检索并抓取公开网页`;
  }
  return status.web_search_reason || "当前模型未提供可用的联网检索通道";
});

watch(
  () => props.open,
  async (open) => {
    if (!open) {
      document.removeEventListener("keydown", handleKeydown, true);
      document.body.style.removeProperty("overflow");
      for (const target of inertTargets) target.inert = false;
      inertTargets.length = 0;
      previousFocus?.focus();
      previousFocus = null;
      return;
    }
    previousFocus = document.activeElement as HTMLElement | null;
    document.body.style.overflow = "hidden";
    for (const selector of [".rail", ".shell__main", ".assistant-rail"]) {
      const target = document.querySelector<HTMLElement>(selector);
      if (target && !target.inert) {
        target.inert = true;
        inertTargets.push(target);
      }
    }
    document.addEventListener("keydown", handleKeydown, true);
    await nextTick();
    inputRef.value?.focus();
    await prepareAssistant();
    if (!turns.value.length && conversationId.value) {
      await loadConversation(conversationId.value);
    }
    await scrollToBottom();
  },
);

watch(
  () => projects.activeId,
  async () => {
    stateVersion += 1;
    turns.value = [];
    message.value = "";
    error.value = "";
    loading.value = false;
    loadingHistory.value = false;
    turnCount.value = 0;
    turnLimit.value = assistantStatus.value?.max_turns ?? 30;
    conversationId.value = readConversationId();
    if (props.open && conversationId.value) {
      await loadConversation(conversationId.value);
      await scrollToBottom();
    }
  },
);

function readConversationId(): string {
  try {
    return localStorage.getItem(conversationStorageKey()) ?? "";
  } catch {
    return "";
  }
}

function conversationStorageKey(): string {
  return `tap.assistant-conversation:${getActiveProjectId() || "default"}`;
}

function saveConversationId(id: string): void {
  conversationId.value = id;
  try {
    if (id) localStorage.setItem(conversationStorageKey(), id);
    else localStorage.removeItem(conversationStorageKey());
  } catch {
    /* localStorage 不可用时，会话仍在当前面板生命周期内有效。 */
  }
}

async function prepareAssistant(): Promise<void> {
  const jobs: Promise<unknown>[] = [];
  if (!indexed) {
    indexed = true;
    indexing.value = true;
    jobs.push(
      api
        .syncKnowledge()
        .catch(() => null)
        .finally(() => {
          indexing.value = false;
        }),
    );
  }
  if (!statusLoaded) {
    statusLoaded = true;
    jobs.push(
      api
        .assistantStatus()
        .then((status) => {
          assistantStatus.value = status;
          turnLimit.value = status.max_turns;
          if (!status.web_search_available) allowWeb.value = false;
        })
        .catch(() => {
          statusLoaded = false;
        }),
    );
  }
  await Promise.allSettled(jobs);
}

async function loadConversation(id: string): Promise<void> {
  const requestVersion = stateVersion;
  loadingHistory.value = true;
  error.value = "";
  try {
    const conversation = await api.assistantConversation(id);
    if (requestVersion !== stateVersion) return;
    turns.value = conversation.messages.map((item, index) => {
      const historicalStatus =
        item.status === "degraded" && !item.degraded_reason
          ? "answered"
          : item.status;
      const answer: AssistantAnswer | undefined =
        item.role === "assistant" && historicalStatus
          ? {
              run_id: "",
              conversation_id: conversation.conversation_id,
              turn_index: conversation.turn_count,
              turn_limit: assistantStatus.value?.max_turns ?? 30,
              context_messages: 0,
              status: historicalStatus,
              answer: item.content,
              mode: item.mode || "deterministic",
              current_facts: [],
              knowledge_references: item.knowledge_references,
              web_citations: item.web_citations,
              web_search_used: item.web_citations.length > 0,
              web_search_status: "",
              model_inferences: [],
              links: [],
              tool_calls: [],
              warnings: item.warnings,
              degraded_reason: item.degraded_reason,
            }
          : undefined;
      return {
        id: `${conversation.conversation_id}-${index}`,
        role: item.role,
        content: item.content,
        createdAt: item.created_at,
        answer,
      };
    });
    turnCount.value = conversation.turn_count;
  } catch {
    if (requestVersion !== stateVersion) return;
    saveConversationId("");
    turns.value = [];
    turnCount.value = 0;
  } finally {
    if (requestVersion === stateVersion) loadingHistory.value = false;
  }
}

function handleKeydown(event: KeyboardEvent) {
  if (!props.open) return;
  if (event.key === "Escape") {
    event.preventDefault();
    emit("close");
    return;
  }
  if (event.key !== "Tab" || !panelRef.value) return;
  const focusable = [
    ...panelRef.value.querySelectorAll<HTMLElement>(
      'button:not([disabled]), textarea:not([disabled]), input:not([disabled]), summary, a[href], [tabindex]:not([tabindex="-1"])',
    ),
  ].filter((item) => item.offsetParent !== null);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function close() {
  emit("close");
}

function entryId(): string {
  pendingCounter += 1;
  return `assistant-entry-${Date.now()}-${pendingCounter}`;
}

async function scrollToBottom(): Promise<void> {
  await nextTick();
  if (bodyRef.value) bodyRef.value.scrollTop = bodyRef.value.scrollHeight;
}

async function ask(text?: string) {
  const content = (text ?? message.value).trim();
  if (!content || loading.value || turnBlocked.value) return;
  const now = new Date().toISOString();
  const pendingId = entryId();
  message.value = "";
  error.value = "";
  turns.value.push({
    id: `${pendingId}-user`,
    role: "user",
    content,
    createdAt: now,
  });
  turns.value.push({
    id: pendingId,
    role: "assistant",
    content: "",
    createdAt: now,
    pending: true,
  });
  loading.value = true;
  const requestVersion = stateVersion;
  await scrollToBottom();
  try {
    const response = await api.askAssistant({
      message: content,
      current_path: route.fullPath,
      conversation_id: conversationId.value,
      allow_web_search: allowWeb.value && assistantStatus.value?.web_search_available !== false,
    });
    if (requestVersion !== stateVersion) return;
    const pending = turns.value.find((item) => item.id === pendingId);
    if (pending) {
      pending.pending = false;
      pending.content = response.answer;
      pending.answer = response;
    }
    saveConversationId(response.conversation_id);
    turnCount.value = response.turn_index;
    turnLimit.value = response.turn_limit;
  } catch (err) {
    if (requestVersion !== stateVersion) return;
    const pending = turns.value.find((item) => item.id === pendingId);
    if (pending) {
      pending.pending = false;
      pending.error = (err as Error).message;
    }
    error.value = (err as Error).message;
  } finally {
    if (requestVersion === stateVersion) {
      loading.value = false;
      await scrollToBottom();
    }
  }
}

function newConversation(): void {
  if (loading.value) return;
  stateVersion += 1;
  loadingHistory.value = false;
  saveConversationId("");
  turns.value = [];
  message.value = "";
  error.value = "";
  turnCount.value = 0;
  nextTick(() => inputRef.value?.focus());
}

function statusLabel(answer: AssistantAnswer): string {
  if (answer.status === "refused") return "没有依据";
  if (answer.status === "degraded") return "已降级";
  return "已回答";
}

function modeLabel(answer: AssistantAnswer): string {
  if (answer.mode === "web_assisted") return "模型 + 网页";
  if (answer.mode === "llm_assisted") return "模型回答";
  return "系统数据";
}

function sourceHref(url: string): string {
  return /^https?:\/\//i.test(url) ? url : url || "#";
}

function citationSummary(item: AssistantWebCitation): string {
  const text = item.summary || item.snippet || item.content_excerpt;
  return text.length > 320 ? `${text.slice(0, 320)}…` : text;
}

onBeforeUnmount(() => {
  document.removeEventListener("keydown", handleKeydown, true);
  document.body.style.removeProperty("overflow");
  for (const target of inertTargets) target.inert = false;
});
</script>

<template>
  <Teleport to="body">
    <Transition name="assistant">
      <div v-if="open" class="assistant-root">
        <button
          type="button"
          class="assistant-scrim"
          aria-label="关闭助手"
          tabindex="-1"
          aria-hidden="true"
          @click="close"
        />
        <aside
          ref="panelRef"
          class="assistant"
          role="dialog"
          aria-modal="true"
          aria-label="只读助手"
          @keydown.esc="close"
        >
          <header class="assistant__head">
            <div class="assistant__identity">
              <h2>知识助手</h2>
              <span
                class="capability"
                :class="{ 'capability--off': assistantStatus && !assistantStatus.web_search_available }"
                :title="webCapabilityTitle"
              >
                <AppIcon name="search" :size="12" />
                {{ webCapabilityLabel }}
              </span>
            </div>
            <div class="assistant__actions">
              <button
                type="button"
                class="icon"
                title="新建对话"
                aria-label="新建对话"
                :disabled="loading"
                @click="newConversation"
              >
                <AppIcon name="refresh" :size="16" />
              </button>
              <button type="button" class="icon" title="关闭" aria-label="关闭" @click="close">
                <AppIcon name="x" :size="17" />
              </button>
            </div>
          </header>

          <div ref="bodyRef" class="assistant__body">
            <p v-if="indexing" class="assistant__state mono">正在同步项目知识索引…</p>
            <p v-if="loadingHistory" class="assistant__state mono">正在读取会话…</p>

            <div v-if="turns.length" class="transcript" aria-live="polite">
              <template v-for="entry in turns" :key="entry.id">
                <article v-if="entry.role === 'user'" class="message message--user">
                  <p>{{ entry.content }}</p>
                </article>

                <article v-else class="message message--assistant">
                  <div v-if="entry.pending" class="answer-pending">
                    <span class="pulse" aria-hidden="true" />
                    <span>正在结合项目上下文回答…</span>
                  </div>
                  <template v-else-if="entry.content || entry.answer">
                    <div v-if="entry.answer" class="answer__head">
                      <span
                        class="status"
                        :data-status="entry.answer.status"
                        :title="entry.answer.degraded_reason || '回答完成'"
                      >
                        {{ statusLabel(entry.answer) }}
                      </span>
                      <span class="mono">{{ modeLabel(entry.answer) }}</span>
                    </div>
                    <div v-else class="answer__head">
                      <span class="status">历史回答</span>
                    </div>

                    <MarkdownBody :source="entry.answer?.answer ?? entry.content" copyable-code />

                    <template v-if="entry.answer">
                      <div v-if="entry.answer.current_facts.length" class="facts">
                        <p class="section-label">当前事实</p>
                        <div
                          v-for="group in entry.answer.current_facts"
                          :key="group.label"
                          class="fact-group"
                        >
                          <p class="fact-group__label">{{ group.label }}</p>
                          <p v-for="claim in group.claims" :key="claim.text" class="fact">
                            {{ claim.text }}
                            <span class="mono">{{ claim.evidence }}</span>
                          </p>
                        </div>
                      </div>

                      <details
                        v-if="entry.answer.knowledge_references.length"
                        class="source-fold"
                      >
                        <summary>
                          项目引用
                          <span class="mono">{{ entry.answer.knowledge_references.length }}</span>
                        </summary>
                        <a
                          v-for="item in entry.answer.knowledge_references"
                          :key="item.citation_id"
                          class="source"
                          :href="sourceHref(item.url)"
                          :target="sourceHref(item.url).startsWith('http') ? '_blank' : undefined"
                          tabindex="0"
                          rel="noreferrer"
                        >
                          <strong>{{ item.title }}</strong>
                          <span>{{ item.locator }}</span>
                          <span class="mono">{{ item.source_type }} · v{{ item.version || "-" }}</span>
                        </a>
                      </details>

                      <div v-if="entry.answer.model_inferences.length" class="inferences">
                        <p class="section-label">推断与建议</p>
                        <p v-for="item in entry.answer.model_inferences" :key="item.text">
                          {{ item.text }}
                        </p>
                      </div>

                      <div v-if="entry.answer.warnings.length" class="warnings">
                        <p v-for="item in entry.answer.warnings" :key="item">{{ item }}</p>
                      </div>

                      <div v-if="entry.answer.links.length" class="jump-links">
                        <RouterLink
                          v-for="item in entry.answer.links"
                          :key="item.href"
                          :to="item.href"
                          @click="emit('close')"
                        >
                          {{ item.label }}
                          <AppIcon name="chevronRight" :size="13" />
                        </RouterLink>
                      </div>

                      <details
                        v-if="entry.answer.web_citations.length"
                        class="web-sources"
                      >
                        <summary>
                          网页来源
                          <span class="mono">{{ entry.answer.web_citations.length }}</span>
                        </summary>
                        <a
                          v-for="item in entry.answer.web_citations"
                          :key="item.citation_id"
                          class="web-source"
                          :href="sourceHref(item.url)"
                          target="_blank"
                          rel="noreferrer noopener"
                        >
                          <span class="web-source__rank mono">[{{ item.citation_id }}]</span>
                          <strong>{{ item.title }}</strong>
                          <span class="web-source__meta">
                            {{ item.site_name || "网页" }}
                            <template v-if="item.published_at"> · {{ item.published_at }}</template>
                            <template v-if="item.fetched"> · 已抓取正文</template>
                          </span>
                          <span v-if="citationSummary(item)" class="web-source__summary">
                            {{ citationSummary(item) }}
                          </span>
                        </a>
                      </details>
                    </template>
                  </template>
                  <p v-if="entry.error" class="assistant__error">{{ entry.error }}</p>
                </article>
              </template>
            </div>

            <div v-else-if="!loadingHistory" class="starting">
              <button
                v-for="item in prompts"
                :key="item"
                type="button"
                class="starter"
                @click="ask(item)"
              >
                <span>{{ item }}</span>
                <AppIcon name="chevronRight" :size="14" />
              </button>
            </div>

            <p v-if="error && !turns.length" class="assistant__error">{{ error }}</p>
          </div>

          <form class="composer" @submit.prevent="ask()">
            <textarea
              ref="inputRef"
              v-model="message"
              rows="3"
              maxlength="4000"
              :disabled="turnBlocked"
              placeholder="提问测试、代码或当前平台问题…"
              @keydown.enter.exact.prevent="ask()"
            />
            <div class="composer__foot">
              <label
                class="web-toggle"
                :class="{ 'web-toggle--disabled': assistantStatus && !assistantStatus.web_search_available }"
                :title="webCapabilityTitle"
              >
                <input
                  v-model="allowWeb"
                  type="checkbox"
                  :disabled="assistantStatus ? !assistantStatus.web_search_available : false"
                />
                <span>联网核验</span>
              </label>
              <span v-if="turnCount" class="mono turn-count">
                {{ turnCount }}/{{ turnLimit }}
              </span>
              <span v-if="turnBlocked" class="limit-note">请新建对话继续</span>
              <button
                type="submit"
                class="send"
                :disabled="loading || turnBlocked || !message.trim()"
                title="发送"
                aria-label="发送"
              >
                <AppIcon v-if="!loading" name="chevronRight" :size="17" />
                <span v-else class="pulse" aria-hidden="true" />
              </button>
            </div>
          </form>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.assistant-root {
  position: fixed;
  inset: 0;
  z-index: 90;
  pointer-events: none;
}

.assistant-scrim {
  position: absolute;
  inset: 0;
  border: 0;
  background: var(--scrim);
  pointer-events: auto;
}

.assistant {
  position: absolute;
  top: 0;
  right: var(--assistant-rail-w);
  display: flex;
  flex-direction: column;
  width: min(560px, calc(100vw - var(--assistant-rail-w)));
  height: 100vh;
  border-left: 1px solid var(--rail-line);
  background: var(--ice-0);
  box-shadow: var(--shadow-overlay);
  pointer-events: auto;
}

.assistant__head {
  display: flex;
  flex: 0 0 auto;
  justify-content: space-between;
  align-items: center;
  gap: var(--s3);
  padding: 16px 20px;
  border-bottom: 1px solid var(--ice-3);
}

.assistant__identity,
.assistant__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.assistant h2 {
  margin: 0;
  font-size: var(--fs-md);
}

.capability {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 6px;
  border: 1px solid color-mix(in srgb, var(--glacier) 35%, var(--ice-3));
  border-radius: 4px;
  color: var(--glacier-deep);
  font-size: 10px;
  white-space: nowrap;
}

.capability--off {
  border-color: var(--ice-4);
  color: var(--ink-3);
}

.icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border: 1px solid transparent;
  border-radius: var(--radius);
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
}

.icon:hover:not(:disabled) {
  border-color: var(--ice-3);
  background: var(--ice-1);
  color: var(--ink-1);
}

.icon:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.assistant__body {
  flex: 1 1 auto;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 18px 20px 28px;
}

.assistant__state,
.assistant__error {
  margin: 0 0 var(--s3);
  font-size: var(--fs-xs);
  color: var(--ink-3);
}

.assistant__error {
  color: var(--danger, #a43c47);
}

.transcript {
  display: grid;
  gap: 18px;
}

.message {
  min-width: 0;
}

.message p {
  margin: 0;
}

.message--user {
  justify-self: end;
  max-width: 86%;
  padding: 9px 11px;
  border: 1px solid var(--ice-3);
  border-radius: 8px;
  background: var(--ice-1);
  color: var(--ink-1);
  font-size: var(--fs-sm);
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.message--assistant {
  min-width: 0;
  padding-top: 2px;
}

.answer-pending {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  color: var(--ink-3);
  font-size: var(--fs-sm);
}

.answer__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
  margin-bottom: var(--s3);
  font-size: 10px;
  color: var(--ink-3);
}

.status {
  padding: 2px 7px;
  border: 1px solid var(--ice-4);
  border-radius: 4px;
  color: var(--ink-2);
}

.status[data-status="degraded"] {
  border-color: var(--warn-line, #b88642);
}

.status[data-status="refused"] {
  border-color: var(--danger, #a43c47);
}

.section-label,
.fact-group__label {
  margin: 0 0 4px;
  font-size: 10px;
  letter-spacing: 0.06em;
  color: var(--ink-3);
}

.facts,
.inferences,
.warnings {
  padding-top: var(--s3);
  margin-top: var(--s3);
  border-top: 1px solid var(--ice-2);
}

.fact-group + .fact-group {
  margin-top: var(--s2);
}

.fact-group__label {
  color: var(--ink-2);
}

.fact {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: var(--s2);
  margin: 5px 0 !important;
  font-size: var(--fs-sm);
}

.fact .mono {
  color: var(--ink-3);
  font-size: 10px;
}

.source-fold,
.web-sources {
  margin-top: var(--s3);
  border-top: 1px solid var(--ice-2);
}

.source-fold summary,
.web-sources summary {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 9px 0 5px;
  color: var(--ink-3);
  font-size: var(--fs-xs);
  cursor: pointer;
  user-select: none;
}

.source-fold summary:hover,
.web-sources summary:hover {
  color: var(--ink-1);
}

.source-fold summary .mono,
.web-sources summary .mono {
  padding: 0 4px;
  border-radius: 3px;
  background: var(--ice-2);
  font-size: 9px;
}

.source {
  display: grid;
  gap: 3px;
  padding: 8px 0;
  border-bottom: 1px solid var(--ice-3);
  color: var(--ink-2);
  text-decoration: none;
}

.source:hover strong {
  color: var(--glacier-deep);
  text-decoration: underline;
}

.source span {
  font-size: var(--fs-xs);
  color: var(--ink-3);
}

.web-sources {
  margin-top: var(--s4);
}

.web-source {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 3px 7px;
  padding: 9px 0;
  border-bottom: 1px solid var(--ice-3);
  color: var(--ink-2);
  text-decoration: none;
}

.web-source:hover strong {
  color: var(--glacier-deep);
  text-decoration: underline;
}

.web-source__rank {
  color: var(--glacier-deep);
  font-size: 10px;
}

.web-source strong {
  min-width: 0;
  overflow-wrap: anywhere;
}

.web-source__meta,
.web-source__summary {
  grid-column: 2;
  color: var(--ink-3);
  font-size: var(--fs-xs);
  line-height: 1.55;
}

.web-source__summary {
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}

.inferences p,
.warnings p {
  margin: 4px 0;
  font-size: var(--fs-xs);
  line-height: 1.6;
}

.warnings p {
  color: var(--warn, #8c6428);
}

.jump-links {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2);
  margin-top: var(--s4);
}

.jump-links a {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 5px 7px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  font-size: var(--fs-xs);
  color: var(--ink-2);
  text-decoration: none;
}

.jump-links a:hover {
  border-color: var(--glacier);
  color: var(--glacier-deep);
}

.starting {
  padding-top: var(--s4);
}

.starter {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 9px 0;
  border: 0;
  border-bottom: 1px solid var(--ice-2);
  background: transparent;
  color: var(--ink-2);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.starter:hover {
  color: var(--glacier-deep);
}

.composer {
  flex: 0 0 auto;
  padding: 12px 20px 16px;
  border-top: 1px solid var(--ice-3);
  background: var(--ice-0);
}

.composer textarea {
  width: 100%;
  min-height: 64px;
  max-height: 180px;
  resize: vertical;
  padding: 9px 10px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  outline: 0;
  background: var(--ice-1);
  color: var(--ink-1);
  font: inherit;
  line-height: 1.5;
}

.composer textarea:focus {
  border-color: var(--glacier);
}

.composer textarea:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.composer__foot {
  display: flex;
  align-items: center;
  gap: var(--s3);
  margin-top: var(--s2);
  color: var(--ink-3);
  font-size: 10px;
}

.web-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
  user-select: none;
}

.web-toggle input {
  width: 13px;
  height: 13px;
  margin: 0;
  accent-color: var(--glacier);
}

.web-toggle--disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.turn-count {
  margin-left: auto;
}

.limit-note {
  color: var(--warn, #8c6428);
}

.send {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 34px;
  height: 34px;
  margin-left: auto;
  border: 1px solid var(--mass);
  border-radius: var(--radius);
  background: var(--mass);
  color: var(--on-mass);
  cursor: pointer;
}

.send:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
  animation: pulse 0.9s ease-in-out infinite alternate;
}

@keyframes pulse {
  to {
    opacity: 0.3;
    transform: scale(0.7);
  }
}

.assistant-enter-active,
.assistant-leave-active {
  transition: opacity var(--dur) var(--ease);
}

.assistant-enter-active .assistant,
.assistant-leave-active .assistant {
  transition: transform var(--dur) var(--ease);
}

.assistant-enter-from,
.assistant-leave-to {
  opacity: 0;
}

.assistant-enter-from .assistant,
.assistant-leave-to .assistant {
  transform: translateX(24px);
}

@media (max-width: 640px) {
  .assistant {
    right: 0;
    width: 100vw;
  }

  .assistant__head,
  .assistant__body,
  .composer {
    padding-inline: var(--s4);
  }

  .capability {
    display: none;
  }

  .message--user {
    max-width: 92%;
  }

  .fact {
    grid-template-columns: 1fr;
  }
}

@media (prefers-reduced-motion: reduce) {
  .assistant-enter-active,
  .assistant-leave-active,
  .assistant-enter-active .assistant,
  .assistant-leave-active .assistant,
  .pulse {
    transition: none;
    animation: none;
  }
}
</style>
