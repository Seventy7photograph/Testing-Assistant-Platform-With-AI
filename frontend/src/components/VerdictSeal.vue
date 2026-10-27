<script setup lang="ts">
import { computed } from "vue";

/** 结论冰印：把发版判定印出来。形状 + 文字双通道，不靠颜色单独表意。 */
const props = defineProps<{
  verdict: "pass" | "conditional" | "reject" | "unknown";
  label: string;
  pending?: boolean;
}>();

const tone = computed(() => {
  switch (props.verdict) {
    case "pass":
      return { css: "var(--pass)", mark: "通过" };
    case "conditional":
      return { css: "var(--warn)", mark: "有条件" };
    case "reject":
      return { css: "var(--fail)", mark: "不建议" };
    default:
      return { css: "var(--ink-3)", mark: "无法判定" };
  }
});

const short = computed(() => {
  const text = props.label || tone.value.mark;
  return text.replace(/^不建议发版$/, "不建议").replace(/^有条件通过$/, "有条件");
});
</script>

<template>
  <div class="seal-wrap" :class="{ 'is-unfrozen': pending, 'is-frozen': !pending }">
    <svg viewBox="0 0 120 120" class="seal-wrap__ring" aria-hidden="true">
      <circle cx="60" cy="60" r="54" fill="none" stroke="currentColor" stroke-width="1" />
      <g stroke="currentColor" stroke-width="1">
        <line v-for="tick in 24" :key="tick" x1="60" y1="6" x2="60" y2="11"
          :transform="`rotate(${tick * 15} 60 60)`" />
      </g>
    </svg>
    <div class="seal-wrap__face" :style="{ color: tone.css }">
      <span class="seal-wrap__word">{{ short }}</span>
      <span class="seal-wrap__label mono">VERDICT</span>
    </div>
  </div>
</template>

<style scoped>
.seal-wrap {
  position: relative;
  width: 128px;
  height: 128px;
  display: grid;
  place-items: center;
  flex: none;
  color: var(--ice-4);
}

.seal-wrap__ring {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  animation: rotate-in var(--dur-slow) var(--ease) both;
}

@keyframes rotate-in {
  from {
    transform: rotate(-14deg) scale(0.94);
    opacity: 0;
  }
  to {
    transform: rotate(0) scale(1);
    opacity: 1;
  }
}

.seal-wrap__face {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  width: 92px;
  height: 92px;
  justify-content: center;
  border-radius: var(--radius);
  background: var(--ice-2);
  border: 1px solid currentColor;
  box-shadow: inset 0 0 0 4px var(--seal-ring);
}

.seal-wrap__word {
  font-size: var(--fs-lg);
  font-weight: 600;
  letter-spacing: 0.02em;
  line-height: 1.1;
}

.seal-wrap__label {
  font-size: 9px;
  letter-spacing: 0.18em;
  color: var(--ink-3);
}
</style>
