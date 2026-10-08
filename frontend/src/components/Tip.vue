<script setup lang="ts">
import { computed, useSlots } from "vue";

/**
 * 悬停提示：术语与口径名词的悬浮解释。
 * 无子内容时自动渲染一个 `?` 标记 —— 提示必须可被发现，不能是看不见的空标签。
 * 键盘可聚焦，不依赖鼠标。
 */
const props = withDefaults(
  defineProps<{
    text: string;
    /** 有子内容时是否加虚线下划线（默认加，保证可发现性） */
    marked?: boolean;
    placement?: "top" | "bottom" | "left" | "right";
  }>(),
  { marked: true, placement: "top" },
);

const slots = useSlots();
const hasContent = computed(() => Boolean(slots.default));
</script>

<template>
  <el-tooltip :content="text" :placement="placement" :show-after="140" effect="dark">
    <span
      class="tip"
      :class="{ 'tip--marked': marked && hasContent }"
      tabindex="0"
      :aria-label="hasContent ? undefined : text"
    >
      <template v-if="hasContent"><slot /></template>
      <span v-else class="tip__mark" aria-hidden="true">?</span>
    </span>
  </el-tooltip>
</template>

<style scoped>
.tip {
  cursor: help;
}

.tip--marked {
  border-bottom: 1px dashed var(--ice-5);
  text-underline-offset: 3px;
}

.tip:hover,
.tip:focus-visible {
  border-bottom-color: var(--glacier);
  color: var(--glacier-deep);
}

/* 与 StatReadout 的口径标记同一套视觉语言 */
.tip__mark {
  display: inline-grid;
  place-items: center;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 1px solid var(--ice-4);
  font-family: var(--font-ui);
  font-size: 9px;
  font-weight: 700;
  line-height: 1;
  color: var(--ink-3);
  transition: border-color var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}

.tip:hover .tip__mark,
.tip:focus-visible .tip__mark {
  border-color: var(--glacier);
  color: var(--glacier-deep);
}
</style>
