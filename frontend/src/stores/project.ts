import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { api, getActiveProjectId, setActiveProjectId } from "@/api";
import type { Project, ProjectContextInfo } from "@/api";

export const useProjectStore = defineStore("project", () => {
  const projects = ref<Project[]>([]);
  const current = ref<ProjectContextInfo | null>(null);
  const activeId = ref(getActiveProjectId());
  const loading = ref(false);
  const error = ref("");

  const activeProject = computed(
    () =>
      current.value?.project
      ?? projects.value.find((item) => item.project_id === activeId.value)
      ?? projects.value.find((item) => item.status === "active")
      ?? null,
  );

  async function load() {
    loading.value = true;
    try {
      projects.value = await api.projects();
      if (!activeId.value && projects.value.length) {
        setActive(projects.value[0].project_id);
      }
      current.value = await api.currentProject();
      error.value = "";
    } catch (err) {
      error.value = (err as Error).message;
    } finally {
      loading.value = false;
    }
  }

  function setActive(projectId: string) {
    activeId.value = projectId;
    setActiveProjectId(projectId);
    current.value = null;
  }

  async function switchTo(projectId: string) {
    setActive(projectId);
    await load();
  }

  return {
    projects,
    current,
    activeId,
    activeProject,
    loading,
    error,
    load,
    setActive,
    switchTo,
  };
});
