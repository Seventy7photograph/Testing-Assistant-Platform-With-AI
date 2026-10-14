<script setup lang="ts">
/**
 * 过程提示列表：分组 + 折叠 + 强制换行。
 *
 * 为什么需要它：一次完整生成会产生二十几条提示，其中绝大多数是**过程信息**
 * （「判定表：5 个条件展开 32 种组合 → 6 条规则」），只有少数是**要人动手的**
 * （「用例数超过单条需求上限，已截断」）。平铺成二十几行大字，结果是真正要注意的
 * 那两条被淹没 —— 提示越多，等于没有提示。
 *
 * 三条规则：
 *   1. **少量直接平铺**（≤ 4 条），没必要为一个两行列表加折叠壳；
 *   2. **多了就分组折叠**：折叠态只露「需要复核」的条目 + 一行分组计数摘要；
 *   3. **长文本必须断行**：水平取值、正则、填充字符串都可能是几十上百字符的长 token，
 *      它们会把页面撑宽、把相邻模块挤出屏幕 —— 这里统一强制换行并限高，
 *      悬停可看全文（title 里放原文）。
 */
import { computed, ref } from "vue";

import AppIcon from "@/components/AppIcon.vue";

const props = defineProps<{ items: string[] }>();

const expanded = ref(false);

/** 出现这些词说明「需要人做事」，而不是「过程长这样」。 */
const ACTIONABLE = [
  "超过单条需求上限",
  "已截断",
  "失败",
  "降级",
  "未识别",
  "不可用",
  "置信度低",
  "无法",
];

/**
 * 「本次未产出用例」被有意排除在外：它是对结果的**解释**（这条需求没有主流程，
 * 所以场景法生成不出东西），不是要你动手修的东西，归到方法分组里更合适。
 * 折叠态最多露这么多条「需要复核」，再多也该收起 —— 否则折叠就失去意义了。
 */
const MAX_COLLAPSED = 5;

const METHOD_KEYWORDS: [string, string][] = [
  ["判定表", "判定表"],
  ["因果图", "因果图"],
  ["正交实验", "正交实验"],
  ["等价类", "等价类划分"],
  ["边界", "边界值分析"],
  ["场景", "场景法"],
];

interface Group {
  key: string;
  label: string;
  actionable: boolean;
  items: string[];
}

const PLAIN_LIMIT = 4;

function isActionable(text: string): boolean {
  return ACTIONABLE.some((word) => text.includes(word));
}

function groupOf(text: string): string {
  for (const [keyword, label] of METHOD_KEYWORDS) {
    if (text.includes(keyword)) return label;
  }
  return "解析与文档";
}

const groups = computed<Group[]>(() => {
  const buckets = new Map<string, Group>();
  for (const text of props.items) {
    const label = isActionable(text) ? "需要复核" : groupOf(text);
    const group = buckets.get(label) ?? {
      key: label,
      label,
      actionable: label === "需要复核",
      items: [],
    };
    group.items.push(text);
    buckets.set(label, group);
  }
  // 「需要复核」永远排最前，其余按条数从多到少。
  return [...buckets.values()].sort((a, b) => {
    if (a.actionable !== b.actionable) return a.actionable ? -1 : 1;
    return b.items.length - a.items.length;
  });
});

const actionable = computed(() => groups.value.filter((group) => group.actionable));
const routine = computed(() => groups.value.filter((group) => !group.actionable));
const routineCount = computed(() => routine.value.reduce((sum, group) => sum + group.items.length, 0));

const summary = computed(() =>
  routine.value.map((group) => `${group.label} ${group.items.length}`).join(" · "),
);

/** 折叠态展示的内容：「需要复核」全列，过程信息只留计数。 */
const collapsedItems = computed(() => actionable.value.flatMap((group) => group.items));
const shownItems = computed(() => collapsedItems.value.slice(0, MAX_COLLAPSED));
const clippedActionable = computed(() => collapsedItems.value.length - shownItems.value.length);
const simple = computed(() => props.items.length <= PLAIN_LIMIT);
</script>

<template>
  <div
    v-if="items.length"
    class="wl"
    :data-total="items.length"
    :data-actionable="collapsedItems.length"
    :data-shown="simple ? items.length : shownItems.length"
    :data-routine="routineCount"
  >
    <ul v-if="simple || expanded" class="wl__list">
      <template v-for="group in groups" :key="group.key">
        <li v-if="expanded && !simple" class="wl__group">{{ group.label }}（{{ group.items.length }}）</li>
        <li v-for="item in group.items" :key="item" :data-tone="group.actionable ? 'warn' : 'info'">
          <AppIcon :name="group.actionable ? 'alert' : 'info'" :size="14" />
          <span class="wl__text" :title="item">{{ item }}</span>
        </li>
      </template>
    </ul>

    <template v-else>
      <ul v-if="shownItems.length" class="wl__list">
        <li v-for="item in shownItems" :key="item" data-tone="warn">
          <AppIcon name="alert" :size="14" />
          <span class="wl__text" :title="item">{{ item }}</span>
        </li>
      </ul>
      <p v-if="clippedActionable || routineCount" class="wl__summary">
        <template v-if="clippedActionable">
          还有 {{ clippedActionable }} 条需要复核、{{ routineCount }} 条过程提示
        </template>
        <template v-else>另有 {{ routineCount }} 条过程提示<span v-if="summary">：{{ summary }}</span></template>
      </p>
    </template>

    <button v-if="!simple" type="button" class="wl__toggle" @click="expanded = !expanded">
      <AppIcon :name="expanded ? 'chevronDown' : 'chevronRight'" :size="14" />
      {{ expanded ? "收起过程提示" : `查看全部 ${items.length} 条提示` }}
    </button>
  </div>
</template>

<style scoped>
.wl {
  margin-top: var(--s3);
}

.wl__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.wl__list li {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: var(--fs-xs);
  line-height: 1.6;
  color: var(--ink-2);
  min-width: 0;
}

.wl__list li[data-tone="warn"] {
  color: var(--warn);
}

.wl__list li svg {
  flex: 0 0 auto;
  margin-top: 2px;
}

/* 长 token（填充字符串、正则、@media 片段）必须能断行，否则会把页面撑宽。 */
.wl__text {
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.wl__group {
  margin-top: var(--s2);
  font-size: var(--fs-2xs);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  color: var(--ink-3);
}

.wl__list li.wl__group:first-child {
  margin-top: 0;
}

.wl__summary {
  margin: 4px 0 0;
  font-size: var(--fs-2xs);
  line-height: 1.7;
  color: var(--ink-3);
  overflow-wrap: anywhere;
}

.wl__toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 6px;
  padding: 2px 8px 2px 4px;
  border: 1px solid var(--ice-3);
  border-radius: 999px;
  background: transparent;
  font-size: var(--fs-2xs);
  color: var(--ink-2);
  cursor: pointer;
}

.wl__toggle:hover {
  border-color: var(--glacier-tint);
  color: var(--glacier-deep);
}
</style>
