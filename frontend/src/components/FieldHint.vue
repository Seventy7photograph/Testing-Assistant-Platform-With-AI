<script setup lang="ts">
/**
 * 行内说明：字段下方一行小字，解释口径、单位、取值范围。常驻，不依赖悬停。
 */
withDefaults(defineProps<{ text?: string; tone?: "muted" | "warn" }>(), {
  tone: "muted",
});
</script>

<template>
  <p class="fieldhint" :data-tone="tone">
    <slot>{{ text }}</slot>
  </p>
</template>

<style scoped>
.fieldhint {
  font-size: var(--fs-xs);
  line-height: 1.6;
  color: var(--ink-3);
}

.fieldhint[data-tone="warn"] {
  color: var(--warn);
}
</style>
