<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";

import { api } from "@/api";
import type {
  AgentRun,
  Job,
  KnowledgeIndexStats,
  ModelRouteInfo,
  ProjectContextInfo,
  Schedule,
  ToolCall,
} from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import { useProjectStore } from "@/stores/project";
import { useNoticeStore } from "@/stores/notice";
import { usePlatformDraftStore } from "@/stores/platformDraft";

type Tab = "overview" | "projects" | "integrations" | "execution" | "knowledge";

const props = defineProps<{ section?: Tab }>();
const tabs: { id: Tab; label: string }[] = [
  { id: "overview", label: "总览" },
  { id: "projects", label: "项目与审计" },
  { id: "integrations", label: "外部同步" },
  { id: "execution", label: "执行与任务" },
  { id: "knowledge", label: "知识与路由" },
];

const projectStore = useProjectStore();
const notice = useNoticeStore();
const draft = usePlatformDraftStore();
const {
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
} = storeToRefs(draft);
const activeTab = ref<Tab>(props.section ?? "overview");
const scoped = computed(() => Boolean(props.section));
const loading = ref(false);
const error = ref("");
const message = ref("");
const context = ref<ProjectContextInfo | null>(null);
const jobs = ref<Job[]>([]);
const schedules = ref<Schedule[]>([]);
const agentRuns = ref<AgentRun[]>([]);
const toolCalls = ref<ToolCall[]>([]);
const knowledge = ref<KnowledgeIndexStats | null>(null);
const routes = ref<ModelRouteInfo[]>([]);

const activeProject = computed(() => context.value?.project ?? projectStore.activeProject);
const openJobs = computed(() => jobs.value.filter((item) => ["queued", "running"].includes(item.status)));
const executionRunning = computed(() => executionPhase.value === "running");
const executionResultJson = computed(() =>
  executionResult.value ? JSON.stringify(executionResult.value, null, 2) : "",
);
const executionStatusLabel = computed(() => {
  if (executionPhase.value === "running") return "执行中";
  if (executionPhase.value === "succeeded") return "执行成功";
  if (executionPhase.value === "failed") return "执行失败";
  return "待执行";
});

function setFeedback(text: string, failure = false) {
  if (failure) {
    error.value = text;
    message.value = "";
  } else {
    message.value = text;
    error.value = "";
  }
}

async function loadAll() {
  loading.value = true;
  const results = await Promise.allSettled([
    api.currentProject(),
    api.jobs({ limit: 100 }),
    api.schedules(),
    api.agentRuns(50),
    api.toolCalls("", 100),
    api.knowledgeStats(),
    api.routing(),
  ]);
  if (results[0].status === "fulfilled") context.value = results[0].value;
  if (results[1].status === "fulfilled") jobs.value = results[1].value;
  if (results[2].status === "fulfilled") schedules.value = results[2].value;
  if (results[3].status === "fulfilled") agentRuns.value = results[3].value;
  if (results[4].status === "fulfilled") toolCalls.value = results[4].value;
  if (results[5].status === "fulfilled") knowledge.value = results[5].value;
  if (results[6].status === "fulfilled") routes.value = results[6].value.routes;
  const failed = results.find((item) => item.status === "rejected");
  if (failed?.status === "rejected") {
    setFeedback((failed.reason as Error).message, true);
  } else {
    error.value = "";
  }
  loading.value = false;
}

async function createProject() {
  try {
    const project = await api.createProject(newProject.value);
    newProject.value = { key: "", name: "", description: "" };
    await projectStore.load();
    await projectStore.switchTo(project.project_id);
    await loadAll();
    notice.success("项目已创建", `${project.key} · ${project.name}`);
    setFeedback(`项目 ${project.key} 已创建并切换。`);
  } catch (err) {
    setFeedback((err as Error).message, true);
  }
}

async function checkIntegration() {
  try {
    integrationHealth.value = await api.integrationHealth(integration.value, {
      project_key: integrationProject.value,
      options: {},
    });
    setFeedback(integrationHealth.value.message, !integrationHealth.value.available);
  } catch (err) {
    setFeedback((err as Error).message, true);
  }
}

async function importRequirements() {
  try {
    const parsed = JSON.parse(integrationFixture.value);
    const items = Array.isArray(parsed) ? parsed : parsed.requirements;
    if (!Array.isArray(items)) throw new Error("JSON 顶层应为数组，或包含 requirements 数组。");
    const result = await api.importIntegrationRequirements(integration.value, {
      project_key: integrationProject.value,
      options: { requirements: items },
    });
    setFeedback(`拉取 ${result.fetched} 条，新增 ${result.created}，更新 ${result.updated}。`);
  } catch (err) {
    setFeedback((err as Error).message, true);
  }
}

async function pushSuite() {
  try {
    const ids = externalIds.value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    const result = await api.pushSuiteToIntegration(integration.value, suiteId.value, {
      project_key: integrationProject.value,
      options: ids.length ? { push_external_ids: ids } : {},
    });
    setFeedback(result.message);
  } catch (err) {
    setFeedback((err as Error).message, true);
  }
}

async function execute() {
  if (executionRunning.value) return;
  const selectedArtifact = artifactId.value.trim();
  if (!selectedArtifact) {
    setFeedback("请先填写自动化资产 ID。", true);
    return;
  }
  let env: Record<string, string>;
  try {
    const parsed = environment.value.trim() ? JSON.parse(environment.value) : {};
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
      throw new Error("环境变量必须是 JSON 对象。");
    }
    env = Object.fromEntries(
      Object.entries(parsed).map(([key, value]) => [key, String(value)]),
    );
  } catch (err) {
    setFeedback(`环境变量 JSON 不合法：${(err as Error).message}`, true);
    return;
  }

  const revision = draft.beginExecution();
  const requestKey =
    typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  setFeedback("执行已提交，正在运行受控 HTTP 用例…");
  try {
    const result = await api.executeHttp({
      artifact_id: selectedArtifact,
      case_ids: caseIds.value.split(",").map((item) => item.trim()).filter(Boolean),
      environment: env,
      idempotency_key: `ui-${selectedArtifact}-${requestKey}`,
    });
    draft.finishExecution(revision, result);
    const failed = result.job.status !== "succeeded";
    setFeedback(
      `${failed ? "执行结束，存在失败" : "执行完成"}：通过 ${result.run.passed}，失败 ${result.run.failed}，错误 ${result.run.errors}。`,
      failed,
    );
    await loadAll();
  } catch (err) {
    const errorMessage = (err as Error).message;
    draft.finishExecution(revision, null, errorMessage);
    setFeedback(`执行失败：${errorMessage}`, true);
  }
}

async function syncKnowledge() {
  try {
    knowledge.value = await api.syncKnowledge();
    setFeedback(`知识索引已更新：${knowledge.value.active_sources} 个活动来源。`);
  } catch (err) {
    setFeedback((err as Error).message, true);
  }
}

async function searchKnowledge() {
  try {
    knowledgeResult.value = await api.searchKnowledge({
      query: knowledgeQuery.value,
      limit: 12,
    });
  } catch (err) {
    setFeedback((err as Error).message, true);
  }
}

async function cancelJob(job: Job) {
  try {
    await api.cancelJob(job.job_id);
    await loadAll();
    setFeedback("任务已取消。");
  } catch (err) {
    setFeedback((err as Error).message, true);
  }
}

function formatTime(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

onMounted(async () => {
  await projectStore.load();
  draft.ensureProject(projectStore.activeId || "PRJ-default");
  await loadAll();
});
</script>

<template>
  <div class="platform">
    <header class="platform__head">
      <div>
        <h2>{{ activeProject?.name ?? "当前项目" }}</h2>
        <p class="platform__sub">
          {{ activeProject?.key ?? "-" }} · {{ context?.role ?? "-" }} ·
          {{ context?.storage_backend ?? "-" }}
        </p>
      </div>
      <button type="button" class="btn" :disabled="loading" @click="loadAll">
        <AppIcon name="refresh" :size="15" />
        <span>刷新</span>
      </button>
    </header>

    <nav v-if="!scoped" class="tabs" aria-label="平台治理分区">
      <button
        v-for="item in tabs"
        :key="item.id"
        type="button"
        :class="{ 'tabs__item--on': activeTab === item.id }"
        @click="activeTab = item.id"
      >
        {{ item.label }}
      </button>
    </nav>

    <p v-if="message" class="feedback" role="status">{{ message }}</p>
    <p v-if="error" class="feedback feedback--error" role="alert">{{ error }}</p>

    <section v-if="activeTab === 'overview'" class="band">
      <div class="readouts">
        <div><span>项目</span><strong>{{ projectStore.projects.length }}</strong></div>
        <div><span>运行中任务</span><strong>{{ openJobs.length }}</strong></div>
        <div><span>知识来源</span><strong>{{ knowledge?.active_sources ?? 0 }}</strong></div>
        <div><span>工具调用</span><strong>{{ toolCalls.length }}</strong></div>
      </div>
      <div class="split">
        <section>
          <h3>最近任务</h3>
          <div v-if="jobs.length" class="rows">
            <div v-for="job in jobs.slice(0, 8)" :key="job.job_id" class="row">
              <span class="mono">{{ job.kind }}</span>
              <span class="state" :data-state="job.status">{{ job.status }}</span>
              <time>{{ formatTime(job.created_at) }}</time>
              <button
                v-if="['queued', 'running'].includes(job.status)"
                type="button"
                class="icon-btn"
                title="取消任务"
                @click="cancelJob(job)"
              >
                <AppIcon name="stop" :size="14" />
              </button>
            </div>
          </div>
          <p v-else class="empty">暂无任务。</p>
        </section>
        <section>
          <h3>助手运行记录</h3>
          <div v-if="agentRuns.length" class="rows">
            <div v-for="run in agentRuns.slice(0, 6)" :key="run.run_id" class="row">
              <span class="mono">{{ run.agent_kind }}</span>
              <span class="state" :data-state="run.status">{{ run.status }}</span>
              <span>{{ run.tool_call_ids.length }} 次工具</span>
              <time>{{ formatTime(run.started_at) }}</time>
            </div>
          </div>
          <p v-else class="empty">暂无助手记录。</p>
        </section>
      </div>
    </section>

    <section v-if="activeTab === 'projects'" class="band">
      <div class="split">
        <section>
          <h3>项目分区</h3>
          <div class="rows">
            <button
              v-for="project in projectStore.projects"
              :key="project.project_id"
              type="button"
              class="project-row"
              :class="{ 'project-row--on': project.project_id === activeProject?.project_id }"
              @click="projectStore.switchTo(project.project_id).then(loadAll)"
            >
              <span class="mono">{{ project.key }}</span>
              <strong>{{ project.name }}</strong>
              <span>{{ project.status }}</span>
            </button>
          </div>
        </section>
        <form class="form" @submit.prevent="createProject">
          <h3>新建项目</h3>
          <label>Key<input v-model="newProject.key" maxlength="32" placeholder="QA-CORE" required /></label>
          <label>名称<input v-model="newProject.name" maxlength="80" placeholder="核心质量项目" required /></label>
          <label>描述<textarea v-model="newProject.description" rows="3" maxlength="1000" /></label>
          <button type="submit" class="btn btn--primary">创建并切换</button>
        </form>
      </div>
    </section>

    <section v-if="activeTab === 'integrations'" class="band">
      <div class="inline-form">
        <label>适配器
          <select v-model="integration">
            <option value="jira">Jira</option>
            <option value="zentao">禅道</option>
          </select>
        </label>
        <label>外部项目<input v-model="integrationProject" placeholder="QA 或 8" /></label>
        <button type="button" class="btn" @click="checkIntegration">检查连接</button>
        <span v-if="integrationHealth" class="state" :data-state="integrationHealth.available ? 'succeeded' : 'failed'">
          {{ integrationHealth.available ? "可用" : "不可用" }}
        </span>
      </div>
      <div class="split">
        <section>
          <h3>需求拉取 / fixture 导入</h3>
          <textarea
            v-model="integrationFixture"
            class="code-area"
            rows="10"
            placeholder='[{"external_id":"QA-1","title":"需求","body":"正文"}]'
          />
          <button type="button" class="btn btn--primary" @click="importRequirements">导入需求</button>
        </section>
        <section>
          <h3>用例回写</h3>
          <label>用例集 ID<input v-model="suiteId" placeholder="SUITE-..." /></label>
          <label>离线外部 ID<input v-model="externalIds" placeholder="QA-101, QA-102" /></label>
          <p class="hint">凭据仅从环境变量读取。</p>
          <button type="button" class="btn" :disabled="!suiteId" @click="pushSuite">回写用例集</button>
        </section>
      </div>
    </section>

    <section v-if="activeTab === 'execution'" class="band">
      <div class="split">
        <form class="form" @submit.prevent="execute">
          <h3>受控 HTTP 执行</h3>
          <label>
            自动化资产 ID
            <input
              v-model="artifactId"
              placeholder="AUTO-..."
              required
              :disabled="executionRunning"
            />
          </label>
          <label>
            用例 ID
            <input
              v-model="caseIds"
              placeholder="留空执行资产内全部用例；多个用逗号分隔"
              :disabled="executionRunning"
            />
          </label>
          <label>
            环境变量 JSON
            <textarea
              v-model="environment"
              class="code-area"
              rows="7"
              :disabled="executionRunning"
            />
          </label>
          <button
            type="submit"
            class="btn btn--primary"
            :disabled="executionRunning || !artifactId.trim()"
            :aria-busy="executionRunning"
          >
            <span v-if="executionRunning" class="execution-spinner" aria-hidden="true" />
            <AppIcon v-else name="play" :size="15" />
            <span>{{ executionRunning ? "执行中，请勿重复提交" : "执行" }}</span>
          </button>
        </form>
        <section>
          <h3>执行结果</h3>
          <div class="execution-state" :data-state="executionPhase">
            <div class="execution-state__head">
              <span class="state" :data-state="executionPhase">{{ executionStatusLabel }}</span>
              <time v-if="executionStartedAt">{{ formatTime(executionStartedAt) }}</time>
            </div>
            <p v-if="executionRunning" class="execution-state__note">
              正在发送请求并执行断言。按钮与表单已锁定，完成前不会再次提交。
            </p>
            <p v-else-if="executionError" class="execution-state__error">{{ executionError }}</p>
            <div v-if="executionResult" class="execution-meta">
              <span>Job <code>{{ executionResult.job.job_id }}</code></span>
              <span>Run <code>{{ executionResult.run.run_id }}</code></span>
              <span>通过 {{ executionResult.run.passed }}</span>
              <span>失败 {{ executionResult.run.failed }}</span>
              <span>错误 {{ executionResult.run.errors }}</span>
            </div>
            <p
              v-if="executionPhase === 'idle'"
              class="execution-state__note"
            >
              尚未执行。
            </p>
          </div>
          <pre v-if="executionResultJson" class="code-output">{{ executionResultJson }}</pre>
        </section>
      </div>
      <section class="stack">
        <h3>任务历史</h3>
        <div class="rows">
          <div v-for="job in jobs" :key="job.job_id" class="row">
            <span class="mono">{{ job.job_id }}</span>
            <span>{{ job.kind }}</span>
            <span class="state" :data-state="job.status">{{ job.status }}</span>
            <span class="mono">{{ job.trace_id }}</span>
            <time>{{ formatTime(job.created_at) }}</time>
          </div>
        </div>
      </section>
      <section class="stack">
        <h3>调度定义</h3>
        <div v-if="schedules.length" class="rows">
          <div v-for="schedule in schedules" :key="schedule.schedule_id" class="row">
            <span>{{ schedule.name }}</span>
            <span class="mono">{{ schedule.job_kind }}</span>
            <span>{{ schedule.interval_seconds }}s</span>
            <span class="state" :data-state="schedule.enabled ? 'succeeded' : 'cancelled'">
              {{ schedule.enabled ? "已登记" : "已停用" }}
            </span>
          </div>
        </div>
        <p v-else class="empty">暂无调度。</p>
      </section>
    </section>

    <section v-if="activeTab === 'knowledge'" class="band">
      <div class="split">
        <section>
          <div class="section-head">
            <h3>项目知识库</h3>
            <button type="button" class="btn" :disabled="loading" @click="syncKnowledge">
              <AppIcon name="refresh" :size="14" />
              <span>重建索引</span>
            </button>
          </div>
          <div class="readouts readouts--small">
            <div><span>活动来源</span><strong>{{ knowledge?.active_sources ?? 0 }}</strong></div>
            <div><span>Chunk</span><strong>{{ knowledge?.chunks ?? 0 }}</strong></div>
            <div><span>降级</span><strong>{{ knowledge?.degraded_reason ? "是" : "否" }}</strong></div>
          </div>
          <form class="inline-form" @submit.prevent="searchKnowledge">
            <input v-model="knowledgeQuery" placeholder="检索需求、用例、接口或帮助" required />
            <button type="submit" class="btn">检索</button>
          </form>
          <div v-if="knowledgeResult" class="citations">
            <article v-for="item in knowledgeResult.citations" :key="item.citation_id">
              <strong>{{ item.title }}</strong>
              <p>{{ item.excerpt }}</p>
              <span class="mono">{{ item.source_type }} · v{{ item.version || "-" }} · {{ item.locator }}</span>
            </article>
          </div>
        </section>
        <section>
          <h3>模型路由</h3>
          <div class="routes">
            <div
              v-for="route in routes"
              :key="route.task"
              class="route"
              :title="route.rationale"
            >
              <span class="mono">{{ route.task }}</span>
              <strong>{{ route.model }}</strong>
              <span>{{ route.strategy }} · {{ route.quality_tier }} / {{ route.cost_tier }}</span>
            </div>
          </div>
        </section>
      </div>
    </section>
  </div>
</template>

<style scoped>
.platform {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

.platform__head,
.section-head,
.inline-form {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
}

.platform__head {
  padding-bottom: var(--s4);
  border-bottom: 1px solid var(--ice-3);
}

.platform__head p,
.platform__head h2 {
  margin: 0;
}

.platform__head p.mono {
  margin-bottom: 4px;
  font-size: 9px;
  letter-spacing: 0.14em;
  color: var(--ink-3);
}

.platform__head h2 {
  font-size: var(--fs-xl);
}

.platform__sub {
  margin-top: 4px !important;
  font-size: var(--fs-xs);
  color: var(--ink-3);
}

.tabs {
  display: flex;
  gap: 2px;
  border-bottom: 1px solid var(--ice-3);
  overflow-x: auto;
}

.tabs button {
  padding: 8px 12px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--ink-3);
  font: inherit;
  font-size: var(--fs-sm);
  white-space: nowrap;
  cursor: pointer;
}

.tabs button:hover,
.tabs .tabs__item--on {
  color: var(--ink-1);
}

.tabs .tabs__item--on {
  border-bottom-color: var(--glacier);
}

.feedback {
  margin: 0;
  padding: 8px 10px;
  border-left: 2px solid var(--glacier);
  background: var(--glacier-wash);
  font-size: var(--fs-sm);
  color: var(--ink-2);
}

.feedback--error {
  border-left-color: var(--danger, #a43c47);
  background: var(--ice-1);
}

.band {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

.readouts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border-block: 1px solid var(--ice-3);
}

.readouts > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--s3) var(--s4);
  border-right: 1px solid var(--ice-3);
}

.readouts > div:last-child {
  border-right: 0;
}

.readouts span {
  font-size: var(--fs-xs);
  color: var(--ink-3);
}

.readouts strong {
  font-size: var(--fs-xl);
  font-weight: 500;
}

.readouts--small {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-block: var(--s3);
}

.readouts--small strong {
  font-size: var(--fs-md);
}

.split {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--s5);
}

.split > section,
.stack,
.form {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}

.split + .stack,
.stack + .stack {
  margin-top: var(--s3);
  padding-top: var(--s4);
  border-top: 1px solid var(--ice-3);
}

h3 {
  margin: 0;
  font-size: var(--fs-md);
  font-weight: 600;
}

.rows {
  display: flex;
  flex-direction: column;
  border-top: 1px solid var(--ice-3);
}

.row {
  display: grid;
  grid-template-columns: minmax(110px, 1fr) auto auto auto;
  align-items: center;
  gap: var(--s3);
  min-height: 38px;
  padding: 6px 0;
  border-bottom: 1px solid var(--ice-2);
  font-size: var(--fs-xs);
  color: var(--ink-2);
}

.row time {
  color: var(--ink-3);
  white-space: nowrap;
}

.state {
  display: inline-flex;
  align-items: center;
  padding: 2px 6px;
  border: 1px solid var(--ice-4);
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--ink-3);
}

.state[data-state="succeeded"],
.state[data-state="completed"] {
  border-color: var(--ok-line, #4f8a72);
  color: var(--ok, #33715c);
}

.state[data-state="running"],
.state[data-state="queued"] {
  border-color: var(--glacier);
  color: var(--glacier-deep);
}

.state[data-state="failed"],
.state[data-state="error"] {
  border-color: var(--danger-line, #b65a63);
  color: var(--danger, #a43c47);
}

.execution-state {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  padding: var(--s3);
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-1);
}

.execution-state[data-state="running"] {
  border-color: var(--glacier-tint);
  background: var(--glacier-wash);
}

.execution-state[data-state="succeeded"] {
  border-color: var(--pass-line, #9ac3b5);
  background: var(--pass-wash);
}

.execution-state[data-state="failed"] {
  border-color: var(--fail-line, #d6a1a5);
  background: var(--fail-wash);
}

.execution-state__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
}

.execution-state__head time {
  color: var(--ink-3);
  font-size: 10px;
}

.execution-state__note,
.execution-state__error {
  margin: 0;
  font-size: var(--fs-xs);
  line-height: 1.6;
  color: var(--ink-3);
}

.execution-state__error {
  color: var(--fail);
}

.execution-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px 10px;
  color: var(--ink-2);
  font-size: var(--fs-xs);
}

.execution-meta code {
  font-family: var(--font-mono);
}

.execution-spinner {
  width: 12px;
  height: 12px;
  border: 2px solid color-mix(in srgb, currentColor 35%, transparent);
  border-top-color: currentColor;
  border-radius: 50%;
  animation: execution-spin 0.8s linear infinite;
}

@keyframes execution-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .execution-spinner {
    animation: none;
  }
}

.project-row {
  display: grid;
  grid-template-columns: 110px 1fr auto;
  gap: var(--s3);
  padding: 9px 8px;
  border: 0;
  border-bottom: 1px solid var(--ice-2);
  background: transparent;
  color: var(--ink-2);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.project-row:hover,
.project-row--on {
  background: var(--glacier-wash);
}

.form label {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: var(--fs-xs);
  color: var(--ink-3);
}

input,
select,
textarea {
  width: 100%;
  padding: 7px 9px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  outline: 0;
  background: var(--ice-1);
  color: var(--ink-1);
  font: inherit;
  font-size: var(--fs-sm);
}

input:focus,
select:focus,
textarea:focus {
  border-color: var(--glacier);
}

textarea {
  resize: vertical;
  line-height: 1.5;
}

.inline-form {
  justify-content: flex-start;
  flex-wrap: wrap;
}

.inline-form label {
  display: flex;
  align-items: center;
  gap: var(--s2);
  font-size: var(--fs-xs);
  color: var(--ink-3);
}

.inline-form input,
.inline-form select {
  width: min(220px, 40vw);
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: fit-content;
  min-height: 32px;
  padding: 5px 10px;
  border: 1px solid var(--ice-4);
  border-radius: var(--radius);
  background: var(--ice-1);
  color: var(--ink-2);
  font: inherit;
  font-size: var(--fs-xs);
  cursor: pointer;
}

.btn:hover {
  border-color: var(--glacier);
  color: var(--glacier-deep);
}

.btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.btn--primary {
  border-color: var(--mass);
  background: var(--mass);
  color: var(--on-mass);
}

.btn--primary:hover {
  color: var(--on-mass);
}

.icon-btn {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border: 1px solid var(--ice-3);
  border-radius: 4px;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
}

.code-area,
.code-output {
  font-family: var(--font-mono);
  font-size: 11px;
}

.code-output {
  max-height: 440px;
  margin: 0;
  padding: var(--s3);
  overflow: auto;
  border: 1px solid var(--ice-3);
  background: var(--ice-1);
  color: var(--ink-2);
  white-space: pre-wrap;
}

.empty,
.hint {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--ink-3);
  line-height: 1.6;
}

.citations {
  display: flex;
  flex-direction: column;
  margin-top: var(--s2);
}

.citations article {
  padding: 10px 0;
  border-top: 1px solid var(--ice-2);
}

.citations p {
  margin: 5px 0;
  font-size: var(--fs-sm);
  line-height: 1.6;
  color: var(--ink-2);
}

.citations span {
  font-size: 10px;
  color: var(--ink-3);
}

.routes {
  display: flex;
  flex-direction: column;
}

.route {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) minmax(130px, auto) auto;
  align-items: center;
  gap: var(--s3);
  padding: 9px 0;
  border-top: 1px solid var(--ice-2);
  font-size: var(--fs-xs);
}

.route p {
  grid-column: 1 / -1;
  margin: 0;
  color: var(--ink-3);
}

@media (max-width: 980px) {
  .split {
    grid-template-columns: 1fr;
  }
  .readouts {
    grid-template-columns: repeat(2, 1fr);
  }
  .readouts > div:nth-child(2) {
    border-right: 0;
  }
}

@media (max-width: 640px) {
  .platform__head {
    align-items: flex-start;
  }
  .readouts {
    grid-template-columns: 1fr 1fr;
  }
  .row {
    grid-template-columns: 1fr auto;
  }
  .row time,
  .row > .mono:last-of-type {
    display: none;
  }
  .inline-form input,
  .inline-form select {
    width: 100%;
  }
}
</style>
