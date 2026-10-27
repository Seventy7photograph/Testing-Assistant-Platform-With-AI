import { defineStore } from "pinia";
import { reactive, ref } from "vue";

import type {
  IntegrationHealth,
  Job,
  KnowledgeSearchResult,
  TestRun,
} from "@/api";

export type ExecutionPhase = "idle" | "running" | "succeeded" | "failed";

const DEFAULT_ENVIRONMENT = '{\n  "baseUrl": "http://127.0.0.1:8000"\n}';

export const usePlatformDraftStore = defineStore("platform-draft", () => {
  const projectId = ref("");
  const newProject = reactive({ key: "", name: "", description: "" });

  const integration = ref<"jira" | "zentao">("jira");
  const integrationHealth = ref<IntegrationHealth | null>(null);
  const integrationFixture = ref("");
  const integrationProject = ref("");
  const suiteId = ref("");
  const externalIds = ref("");

  const artifactId = ref("");
  const caseIds = ref("");
  const environment = ref(DEFAULT_ENVIRONMENT);
  const executionPhase = ref<ExecutionPhase>("idle");
  const executionStartedAt = ref("");
  const executionError = ref("");
  const executionResult = ref<{ job: Job; run: TestRun } | null>(null);

  const knowledgeQuery = ref("");
  const knowledgeResult = ref<KnowledgeSearchResult | null>(null);

  let executionRevision = 0;

  function ensureProject(nextProjectId: string): void {
    const normalized = nextProjectId || "PRJ-default";
    if (projectId.value === normalized) return;
    projectId.value = normalized;
    executionRevision += 1;
    newProject.key = "";
    newProject.name = "";
    newProject.description = "";
    integration.value = "jira";
    integrationHealth.value = null;
    integrationFixture.value = "";
    integrationProject.value = "";
    suiteId.value = "";
    externalIds.value = "";
    artifactId.value = "";
    caseIds.value = "";
    environment.value = DEFAULT_ENVIRONMENT;
    executionPhase.value = "idle";
    executionStartedAt.value = "";
    executionError.value = "";
    executionResult.value = null;
    knowledgeQuery.value = "";
    knowledgeResult.value = null;
  }

  function setExecutionArtifact(nextArtifactId: string): void {
    const normalized = nextArtifactId.trim();
    if (!normalized || normalized === artifactId.value) return;
    executionRevision += 1;
    artifactId.value = normalized;
    caseIds.value = "";
    executionPhase.value = "idle";
    executionStartedAt.value = "";
    executionError.value = "";
    executionResult.value = null;
  }

  function beginExecution(): number {
    executionRevision += 1;
    executionPhase.value = "running";
    executionStartedAt.value = new Date().toISOString();
    executionError.value = "";
    executionResult.value = null;
    return executionRevision;
  }

  function finishExecution(
    revision: number,
    result: { job: Job; run: TestRun } | null,
    message = "",
  ): boolean {
    if (revision !== executionRevision) return false;
    executionResult.value = result;
    executionError.value = result
      ? result.job.status === "succeeded"
        ? ""
        : result.job.error || "执行结束，存在失败或错误用例。"
      : message;
    executionPhase.value = result && result.job.status === "succeeded" ? "succeeded" : "failed";
    return true;
  }

  return {
    projectId,
    newProject,
    integration,
    integrationHealth,
    integrationFixture,
    integrationProject,
    suiteId,
    externalIds,
    artifactId,
    caseIds,
    environment,
    executionPhase,
    executionStartedAt,
    executionError,
    executionResult,
    knowledgeQuery,
    knowledgeResult,
    ensureProject,
    setExecutionArtifact,
    beginExecution,
    finishExecution,
  };
});
