<script setup lang="ts">
import { computed } from "vue";

import { PRIORITY_LABELS, priorityTone } from "@/utils/labels";

const props = defineProps<{ priority: string }>();

const tone = computed(() => priorityTone(props.priority));
const label = computed(() => PRIORITY_LABELS[props.priority] ?? props.priority);
</script>

<template>
  <span class="prio" :data-tone="tone" :title="label">
    <svg viewBox="0 0 10 10" width="9" height="9" aria-hidden="true">
      <rect v-if="tone === 'p0'" x="0.5" y="0.5" width="9" height="9" rx="1.6" fill="currentColor" />
      <rect v-else-if="tone === 'p1'" x="0.5" y="0.5" width="9" height="9" rx="1.6" fill="none" stroke="currentColor" stroke-width="1.4" />
      <polygon v-else-if="tone === 'p2'" points="5,0.6 9.4,9.4 0.6,9.4" fill="currentColor" />
      <circle v-else cx="5" cy="5" r="3.4" fill="none" stroke="currentColor" stroke-width="1.4" />
    </svg>
    <span class="prio__text">{{ props.priority }}</span>
  </span>
</template>

<style scoped>
.prio {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-family: var(--font-data);
  font-size: var(--fs-xs);
  font-weight: 500;
  white-space: nowrap;
}

.prio[data-tone="p0"] {
  color: var(--fail);
}

.prio[data-tone="p1"] {
  color: var(--warn);
}

.prio[data-tone="p2"] {
  color: var(--glacier-deep);
}

.prio[data-tone="p3"] {
  color: var(--ink-3);
}
</style>
