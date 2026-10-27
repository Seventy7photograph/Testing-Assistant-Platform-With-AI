<script setup lang="ts">
import { computed, onMounted } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import { useProjectStore } from "@/stores/project";

const projects = useProjectStore();

const options = computed(() =>
  projects.projects.filter((item) => item.status === "active"),
);

onMounted(() => {
  if (!projects.projects.length) void projects.load();
});

function change(event: Event) {
  const value = (event.target as HTMLSelectElement).value;
  if (value) void projects.switchTo(value);
}
</script>

<template>
  <label class="project" title="切换项目分区">
    <AppIcon name="layers" :size="15" />
    <select
      class="project__select"
      :value="projects.activeId || projects.activeProject?.project_id || ''"
      :disabled="projects.loading"
      aria-label="当前项目"
      @change="change"
    >
      <option v-if="!options.length" value="">默认项目</option>
      <option
        v-for="item in options"
        :key="item.project_id"
        :value="item.project_id"
      >
        {{ item.key }} · {{ item.name }}
      </option>
    </select>
    <span class="project__role mono">{{ projects.current?.role ?? "local" }}</span>
  </label>
</template>

<style scoped>
.project {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  width: 210px;
  max-width: 210px;
  padding: 0 8px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-1);
  color: var(--ink-3);
}

.project__select {
  flex: 1 1 auto;
  min-width: 0;
  max-width: 176px;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--ink-2);
  font: inherit;
  font-size: var(--fs-xs);
  text-overflow: ellipsis;
}

.project__role {
  padding-left: 6px;
  border-left: 1px solid var(--ice-3);
  font-size: 9px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

@media (max-width: 1180px) {
  .project {
    width: 180px;
    max-width: 180px;
  }
  .project__role {
    display: none;
  }
}

@media (max-width: 820px) {
  .project {
    width: 148px;
    max-width: 148px;
    padding-inline: 6px;
  }

  .project__select {
    max-width: 108px;
  }
}

@media (max-width: 480px) {
  .project {
    width: 112px;
    max-width: 112px;
  }

  .project__select {
    max-width: 78px;
  }
}
</style>
