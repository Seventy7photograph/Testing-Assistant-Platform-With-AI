<script setup lang="ts">
import { computed } from "vue";

import { methodLabel } from "@/utils/labels";

const props = defineProps<{ method: string; muted?: boolean }>();
const label = computed(() => methodLabel(props.method));
</script>

<template>
  <span class="tag" :class="{ 'tag--muted': muted }" :title="label">{{ label }}</span>
</template>

<style scoped>
.tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--glacier-tint);
  background: var(--glacier-wash);
  color: var(--glacier-deep);
  font-size: var(--fs-xs);
  font-weight: 500;
  white-space: nowrap;
}

.tag--muted {
  border-color: var(--ice-4);
  background: var(--ice-2);
  color: var(--ink-3);
}
</style>
