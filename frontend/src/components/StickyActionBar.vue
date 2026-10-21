<script setup lang="ts">
import { onActivated, onDeactivated, ref } from "vue";

import { useUiStore } from "@/stores/ui";

withDefaults(
  defineProps<{
    label: string;
    summary: string;
    disabled?: boolean;
    busy?: boolean;
  }>(),
  { disabled: false, busy: false },
);

const emit = defineEmits<{ (event: "primary"): void }>();
const ui = useUiStore();
/**
 * Teleport targets body, so a cached KeepAlive subtree does not automatically
 * remove the teleported node when its owning route is deactivated. Keep it in
 * sync with the component lifecycle to prevent a report action bar leaking onto
 * the generator or dashboard.
 */
const active = ref(true);

onActivated(() => {
  active.value = true;
});

onDeactivated(() => {
  active.value = false;
});
</script>

<template>
  <Teleport to="body">
    <div
      v-if="active"
      class="sticky-actions"
      data-action-bar
      :data-collapsed="ui.railCollapsed ? '1' : '0'"
    >
      <div class="sticky-actions__inner">
        <p class="sticky-actions__summary" :title="summary">{{ summary }}</p>
        <slot />
        <el-button type="primary" :loading="busy" :disabled="disabled" @click="emit('primary')">
          {{ label }}
        </el-button>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.sticky-actions {
  position: fixed;
  right: 0;
  bottom: 0;
  left: var(--rail-w);
  z-index: 50;
  padding: 10px var(--s5) calc(10px + env(safe-area-inset-bottom));
  border-top: 1px solid var(--ice-3);
  background: color-mix(in srgb, var(--ice-0) 94%, transparent);
  backdrop-filter: saturate(150%) blur(14px);
  -webkit-backdrop-filter: saturate(150%) blur(14px);
  transition: left var(--dur) var(--ease);
}

.sticky-actions[data-collapsed="1"] {
  left: var(--rail-w-mini);
}

.sticky-actions__inner {
  display: flex;
  align-items: center;
  gap: var(--s2);
  width: 100%;
  max-width: var(--content-max);
  margin: 0 auto;
}

.sticky-actions__summary {
  flex: 1 1 auto;
  min-width: 0;
  font-size: var(--fs-xs);
  color: var(--ink-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 1080px) {
  .sticky-actions,
  .sticky-actions[data-collapsed="1"] {
    left: 0;
    padding-inline: var(--s3);
  }
}

@media (max-width: 640px) {
  .sticky-actions__inner {
    align-items: stretch;
  }

  .sticky-actions__summary {
    max-width: 45%;
    white-space: normal;
    line-height: 1.35;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
  }
}
</style>
