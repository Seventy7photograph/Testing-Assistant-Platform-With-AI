<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { api } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import { engineLabel } from "@/utils/labels";

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ (e: "close"): void }>();

const router = useRouter();
const query = ref("");
const cursor = ref(0);
const inputRef = ref<HTMLInputElement | null>(null);
const recents = ref<{ label: string; hint: string; to: string }[]>([]);

interface Entry {
  label: string;
  hint: string;
  icon: string;
  to: string;
  group: string;
}

const pages: Entry[] = [
  { label: "总览", hint: "AI 工作流状态与最近动态", icon: "gauge", to: "/", group: "页面" },
  { label: "用例生成", hint: "需求文档 → 结构化需求 → 用例集", icon: "sparkle", to: "/generate", group: "页面" },
  { label: "文档与需求", hint: "上传 · 解析 · 追溯", icon: "doc", to: "/documents", group: "页面" },
  { label: "接口资产", hint: "OpenAPI → 契约用例 → Postman", icon: "route", to: "/apis", group: "页面" },
  { label: "用例集", hint: "浏览 · 统计 · 导出", icon: "cases", to: "/suites", group: "页面" },
  { label: "报告工作台", hint: "执行数据 → 指标 → AI 报告", icon: "chart", to: "/report", group: "页面" },
  { label: "报告存档", hint: "趋势 · 检索 · 对比", icon: "archive", to: "/report/archive", group: "页面" },
  { label: "交付工作台", hint: "自动化资产 · 执行记录 · 工作事项", icon: "route", to: "/workspace", group: "页面" },
  { label: "大模型与阈值", hint: "所有模型任务共用配置", icon: "sliders", to: "/settings", group: "页面" },
];

function score(entry: Entry, needle: string): number {
  if (!needle) return 1;
  const haystack = `${entry.label}${entry.hint}`.toLowerCase();
  if (haystack.includes(needle)) return 3;
  let index = 0;
  for (const char of needle) {
    index = haystack.indexOf(char, index);
    if (index === -1) return 0;
    index += 1;
  }
  return 1;
}

const results = computed(() => {
  const needle = query.value.trim().toLowerCase();
  const pool = [...pages, ...recents.value.map((item) => ({ ...item, icon: "file", group: "最近" }))];
  return pool
    .map((entry) => ({ entry, weight: score(entry, needle) }))
    .filter((item) => item.weight > 0)
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 9)
    .map((item) => item.entry);
});

watch(
  () => props.open,
  async (open) => {
    if (!open) return;
    query.value = "";
    cursor.value = 0;
    await nextTick();
    inputRef.value?.focus();
    void loadRecents();
  },
);

async function loadRecents() {
  try {
    const [{ items: reports }, suites] = await Promise.all([
      api.reports({ limit: 4 }),
      api.suites(4),
    ]);
    recents.value = [
      ...reports.map((item) => ({
        label: item.title || "未命名报告",
        hint: item.version ? `报告 · ${item.version}` : "报告存档",
        to: `/report/archive/${item.id}`,
      })),
      ...suites.map((item) => ({
        label: item.doc_title || "未命名用例集",
        hint: `用例集 · ${item.stats.total} 条 · ${engineLabel(item.generation_meta)}`,
        to: `/suites/${item.suite_id}`,
      })),
    ];
  } catch {
    recents.value = [];
  }
}

function move(step: number) {
  const total = results.value.length;
  if (!total) return;
  cursor.value = (cursor.value + step + total) % total;
}

function choose(index: number) {
  const entry = results.value[index];
  if (!entry) return;
  emit("close");
  void router.push(entry.to);
}
</script>

<template>
  <Teleport to="body">
    <Transition name="palette">
      <div v-if="open" class="scrim" @click.self="emit('close')">
        <div
          class="panel"
          role="dialog"
          aria-modal="true"
          aria-label="快速跳转"
          @keydown.esc="emit('close')"
          @keydown.down.prevent="move(1)"
          @keydown.up.prevent="move(-1)"
          @keydown.enter.prevent="choose(cursor)"
        >
          <div class="panel__field">
            <AppIcon name="search" :size="17" />
            <input
              ref="inputRef"
              v-model="query"
              class="panel__input"
              type="text"
              placeholder="跳转到页面、用例集或报告…"
              autocomplete="off"
            />
            <kbd class="panel__kbd mono">Esc</kbd>
          </div>

          <ul v-if="results.length" class="panel__list">
            <li v-for="(entry, index) in results" :key="`${entry.group}-${entry.to}`">
              <button
                type="button"
                class="opt"
                :class="{ 'opt--on': index === cursor }"
                @mousemove="cursor = index"
                @click="choose(index)"
              >
                <span class="opt__icon"><AppIcon :name="entry.icon" :size="16" /></span>
                <span class="opt__label">{{ entry.label }}</span>
                <span class="opt__hint">{{ entry.hint }}</span>
                <span class="opt__group mono">{{ entry.group }}</span>
              </button>
            </li>
          </ul>
          <p v-else class="panel__empty">没有匹配的目标。试试页面名，或直接按 Esc 退出。</p>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.scrim {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 14vh var(--s4) var(--s4);
  background: var(--scrim);
  backdrop-filter: blur(3px);
}

.panel {
  width: min(620px, 100%);
  background: var(--ice-0);
  border: 1px solid var(--ice-3);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-overlay);
  overflow: hidden;
}

.panel__field {
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  border-bottom: 1px solid var(--ice-3);
  color: var(--ink-3);
}

.panel__input {
  flex: 1 1 auto;
  border: none;
  outline: none;
  background: transparent;
  font: inherit;
  font-size: var(--fs-md);
  color: var(--ink-1);
}

.panel__input::placeholder {
  color: var(--ink-placeholder);
}

.panel__kbd {
  padding: 1px 6px;
  border: 1px solid var(--ice-4);
  border-radius: 4px;
  font-size: 10px;
  color: var(--ink-3);
}

.panel__list {
  list-style: none;
  margin: 0;
  padding: 6px;
  max-height: 52vh;
  overflow-y: auto;
}

.opt {
  display: grid;
  grid-template-columns: 24px auto 1fr auto;
  align-items: center;
  gap: var(--s3);
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: var(--radius);
  background: transparent;
  color: var(--ink-2);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.opt--on {
  background: var(--glacier-wash);
  color: var(--ink-1);
}

.opt__icon {
  display: grid;
  place-items: center;
  color: var(--glacier-deep);
}

.opt__label {
  font-size: var(--fs-base);
  font-weight: 500;
}

.opt__hint {
  font-size: var(--fs-xs);
  color: var(--ink-3);
}

.opt__group {
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--ink-3);
}

.panel__empty {
  padding: var(--s6) var(--s5);
  text-align: center;
  font-size: var(--fs-sm);
  color: var(--ink-3);
}

.palette-enter-active,
.palette-leave-active {
  transition: opacity var(--dur) var(--ease);
}

.palette-enter-active .panel,
.palette-leave-active .panel {
  transition: transform var(--dur) var(--ease), opacity var(--dur) var(--ease);
}

.palette-enter-from,
.palette-leave-to {
  opacity: 0;
}

.palette-enter-from .panel {
  transform: translateY(-10px) scale(0.985);
  opacity: 0;
}
</style>
