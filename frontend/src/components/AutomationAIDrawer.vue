<script setup lang="ts">
import { computed } from "vue";

import type { AutomationAIKind, AutomationArtifact } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import AutomationAIReviewPanel from "@/components/AutomationAIReviewPanel.vue";

const props = withDefaults(
  defineProps<{
    open: boolean;
    specId: string;
    artifactId?: string;
    runId?: string;
    kinds?: AutomationAIKind[];
    contextLabel?: string;
  }>(),
  {
    artifactId: "",
    runId: "",
    kinds: () => ["operation_gap", "fixture_recipe", "script_review"],
    contextLabel: "",
  },
);

const emit = defineEmits<{
  (e: "update:open", value: boolean): void;
  (e: "applied", artifact: AutomationArtifact): void;
}>();

const subtitle = computed(
  () => props.contextLabel || "人工确认后应用，原版本保留",
);
</script>

<template>
  <el-drawer
    :model-value="open"
    direction="rtl"
    size="min(720px, 96vw)"
    :show-close="false"
    :with-header="false"
    append-to-body
    class="ai-drawer"
    @update:model-value="emit('update:open', $event)"
  >
    <div class="drawer">
      <header class="drawer__head">
        <span class="drawer__mark"><AppIcon name="sparkle" :size="19" /></span>
        <div>
          <h3>自动化建议</h3>
          <p>{{ subtitle }}</p>
        </div>
        <div class="spacer" />
        <button
          type="button"
          class="drawer__close"
          title="关闭建议抽屉"
          aria-label="关闭建议抽屉"
          @click="emit('update:open', false)"
        >
          <AppIcon name="x" :size="17" />
        </button>
      </header>
      <AutomationAIReviewPanel
        v-if="specId"
        :spec-id="specId"
        :artifact-id="artifactId"
        :run-id="runId"
        :kinds="kinds"
        @applied="emit('applied', $event)"
      />
    </div>
  </el-drawer>
</template>

<style scoped>
.drawer {
  min-height: 100%;
  background: var(--ice-1);
}

.drawer__head {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding: var(--s4) var(--s5);
  border-bottom: 1px solid var(--ice-3);
  background: var(--bar-face);
  backdrop-filter: none;
}

.drawer__mark {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  flex: none;
  border: 1px solid var(--glacier-tint);
  border-radius: 12px;
  background: var(--glacier-wash);
  color: var(--glacier-deep);
}

.drawer__head h3 {
  margin-top: 1px;
  font-size: var(--fs-md);
}

.drawer__head p:last-child {
  margin-top: 2px;
  color: var(--ink-3);
  font-size: var(--fs-xs);
}

.drawer__close {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-0);
  color: var(--ink-3);
  cursor: pointer;
}

.drawer__close:hover {
  border-color: var(--ice-5);
  color: var(--ink-1);
}

:deep(.ai-drawer .el-drawer__body) {
  padding: 0;
  overflow-y: auto;
}

@media (max-width: 760px) {
  .drawer__head {
    padding: var(--s3) var(--s4);
  }
}
</style>
