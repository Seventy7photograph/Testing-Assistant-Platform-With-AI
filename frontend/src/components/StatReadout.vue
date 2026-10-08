<script setup lang="ts">
import { computed, ref } from "vue";

/**
 * 读数：任何"正在计算"的值先以虚线冰川轮廓出现，完成后冻结成实心刻度。
 * 这是全站唯一被编排的瞬间。
 */
const props = withDefaults(
  defineProps<{
    label: string;
    value: string | number | null | undefined;
    unit?: string;
    hint?: string;
    tone?: "default" | "pass" | "warn" | "fail" | "glacier";
    /** 计算中：显示未冻结的轮廓 */
    pending?: boolean;
    /** 数值有变化时重播落定动画 */
    animate?: boolean;
  }>(),
  { tone: "default", pending: false, animate: true },
);

const key = ref(0);
const display = computed(() => {
  const value = props.value;
  if (value === null || value === undefined || value === "") return "—";
  return value;
});

function replay() {
  key.value += 1;
}
defineExpose({ replay });
</script>

<template>
  <div class="readout" :data-tone="tone">
    <div class="readout__head">
      <span class="readout__label">{{ label }}</span>
      <el-tooltip v-if="hint" :content="hint" placement="top" effect="dark" :show-after="140">
        <span class="readout__hint" tabindex="0" aria-label="口径说明">?</span>
      </el-tooltip>
    </div>

    <p
      :key="key"
      class="readout__value mono"
      :class="{
        'is-unfrozen': pending,
        'is-frozen': animate && !pending,
      }"
    >
      {{ pending ? "–––" : display }}<span v-if="unit && !pending" class="readout__unit">{{ unit }}</span>
    </p>

    <span class="readout__rule" :class="{ 'readout__rule--draw': animate && !pending }" />
    <p v-if="$slots.note" class="readout__note"><slot name="note" /></p>
  </div>
</template>

<style scoped>
.readout {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.readout__head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.readout__label {
  font-size: var(--fs-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--ink-3);
}

.readout__hint {
  display: grid;
  place-items: center;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 1px solid var(--ice-4);
  font-size: 9px;
  font-weight: 700;
  color: var(--ink-3);
  cursor: help;
}

.readout__hint:hover,
.readout__hint:focus-visible {
  border-color: var(--glacier);
  color: var(--glacier-deep);
}

.readout__value {
  font-size: var(--fs-2xl);
  font-weight: 500;
  line-height: 1.1;
  letter-spacing: -0.02em;
  color: var(--ink-1);
}

.readout__unit {
  margin-left: 4px;
  font-size: var(--fs-sm);
  color: var(--ink-3);
}

.readout[data-tone="pass"] .readout__value {
  color: var(--pass);
}

.readout[data-tone="warn"] .readout__value {
  color: var(--warn);
}

.readout[data-tone="fail"] .readout__value {
  color: var(--fail);
}

.readout[data-tone="glacier"] .readout__value {
  color: var(--glacier-deep);
}

.readout__rule {
  display: block;
  height: 1px;
  background: var(--ice-4);
  transform-origin: left center;
}

.readout__rule--draw {
  animation: rule-draw var(--dur-slow) var(--ease) both;
}

.readout__note {
  font-size: var(--fs-xs);
  line-height: 1.55;
  color: var(--ink-3);
}
</style>
