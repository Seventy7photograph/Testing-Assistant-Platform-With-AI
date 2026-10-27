<script setup lang="ts">
/** 字段说明默认收起，悬停或键盘聚焦时显示。 */
withDefaults(defineProps<{ text?: string; tone?: "muted" | "warn" }>(), {
  tone: "muted",
});
</script>

<template>
  <span class="fieldhint" :data-tone="tone" tabindex="0" aria-label="字段说明">
    <span class="fieldhint__mark" aria-hidden="true">?</span>
    <span class="fieldhint__text"><slot>{{ text }}</slot></span>
  </span>
</template>

<style scoped>
.fieldhint {
  position: relative;
  display: inline-flex;
  width: fit-content;
  align-items: center;
  font-size: var(--fs-xs);
  color: var(--ink-3);
}

.fieldhint__mark {
  display: grid;
  place-items: center;
  width: 16px;
  height: 16px;
  border: 1px solid var(--ice-4);
  border-radius: 50%;
  font-family: var(--font-data);
  font-size: 9px;
}

.fieldhint__text {
  position: absolute;
  z-index: 30;
  top: calc(100% + 6px);
  left: 0;
  display: none;
  width: min(320px, 80vw);
  padding: 7px 9px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-0);
  box-shadow: var(--shadow-overlay);
  line-height: 1.5;
}

.fieldhint:hover .fieldhint__text,
.fieldhint:focus-visible .fieldhint__text {
  display: block;
}

.fieldhint[data-tone="warn"] {
  color: var(--warn);
}
</style>
