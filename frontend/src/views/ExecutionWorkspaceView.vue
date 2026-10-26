<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api, saveBlob } from "@/api";
import type {
  ApiSpecSummary,
  AutomationAIKind,
  AutomationArtifact,
  AutomationArtifactSummary,
  JobEvent,
  TestRun,
  TestRunSummary,
  WorkItem,
  WorkItemPriority,
} from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import AutomationAIDrawer from "@/components/AutomationAIDrawer.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorNote from "@/components/ErrorNote.vue";
import MarkdownBody from "@/components/MarkdownBody.vue";
import { useNoticeStore } from "@/stores/notice";
import { useReportSession } from "@/stores/reportSession";
import { useWorkItemsStore } from "@/stores/workItems";
import { formatRelative } from "@/utils/labels";

type TabKey = "automation" | "runs" | "items";

const route = useRoute();
const router = useRouter();
const notice = useNoticeStore();
const reportSession = useReportSession();
const workStore = useWorkItemsStore();

const activeTab = ref<TabKey>("automation");
const aiDrawerOpen = ref(false);
const aiDrawerKinds = ref<AutomationAIKind[]>([
  "operation_gap",
  "fixture_recipe",
  "script_review",
]);
const loading = ref(false);
const busy = ref("");
const error = ref("");

const specs = ref<ApiSpecSummary[]>([]);
const artifacts = ref<AutomationArtifactSummary[]>([]);
const selectedSpecId = ref("");
const selectedArtifactId = ref("");
const selectedArtifact = ref<AutomationArtifact | null>(null);

const runs = ref<TestRunSummary[]>([]);
const selectedRunId = ref("");
const selectedRun = ref<TestRun | null>(null);
const runEvents = ref<JobEvent[]>([]);
const junitFile = ref<File | null>(null);
const junitInput = ref<HTMLInputElement | null>(null);

const items = ref<WorkItem[]>([]);
const selectedItem = ref<WorkItem | null>(null);
const itemBusy = ref("");
const saveState = ref<"idle" | "saving" | "saved" | "failed">("idle");
const quick = reactive({
  title: "",
  body: "",
  priority: "P2" as WorkItemPriority,
  due_at: "",
  remind_at: "",
  tags: "",
});
const filters = reactive({
  view: "today",
  q: "",
  priority: "",
  tag: "",
});
const editor = reactive({
  title: "",
  body: "",
  priority: "P2" as WorkItemPriority,
  status: "inbox",
  due_at: "",
  remind_at: "",
  tags: "",
  pinned: false,
  preview: false,
});

const specCount = computed(() => specs.value.length);
const artifactCount = computed(() => artifacts.value.length);
const runCount = computed(() => runs.value.length);
const itemAttention = computed(() => workStore.summary?.overdue ?? 0);

const failedResults = computed(() =>
  selectedRun.value
    ? [...selectedRun.value.cases, ...selectedRun.value.unmatched_cases].filter(
        (item) => item.status === "failed" || item.status === "error",
      )
    : [],
);

const itemResultLabel = computed(() => {
  if (saveState.value === "saving") return "保存中";
  if (saveState.value === "saved") return "已保存";
  if (saveState.value === "failed") return "保存失败";
  return "未修改";
});

const aiDrawerSpecId = computed(() => {
  if (activeTab.value === "runs" && selectedRun.value) {
    return selectedRun.value.spec_id || selectedSpecId.value;
  }
  return selectedSpecId.value;
});

const aiDrawerArtifactId = computed(() => {
  if (activeTab.value === "runs" && selectedRun.value) {
    return selectedRun.value.artifact_id || selectedArtifactId.value;
  }
  return selectedArtifactId.value;
});

const activeFilterLabel = computed(() => {
  const labels: Record<string, string> = {
    today: "今日",
    inbox: "收件箱",
    upcoming: "近期",
    overdue: "逾期",
    all: "全部",
    completed: "已完成",
  };
  return labels[filters.view] ?? filters.view;
});

onMounted(async () => {
  const queryTab = String(route.query.tab ?? "");
  if (queryTab === "runs" || queryTab === "items" || queryTab === "automation") {
    activeTab.value = queryTab;
  }
  await loadAll();
  const runId = String(route.query.run ?? "");
  if (runId) {
    activeTab.value = "runs";
    await openRun(runId);
  }
});

async function loadAll() {
  loading.value = true;
  error.value = "";
  try {
    const [specRows, artifactRows, runRows] = await Promise.all([
      api.apiSpecs(50),
      api.automationArtifacts(undefined, 50),
      api.testRuns({ limit: 50 }),
    ]);
    specs.value = specRows;
    artifacts.value = artifactRows;
    runs.value = runRows;
    if (!selectedSpecId.value && specRows[0]) selectedSpecId.value = specRows[0].spec_id;
    if (!selectedArtifactId.value && artifactRows[0]) {
      await openArtifact(artifactRows[0].artifact_id);
    }
    if (!selectedRunId.value && runRows[0]) {
      await openRun(runRows[0].run_id);
    }
    await refreshItems();
    await workStore.refreshSummary();
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    loading.value = false;
  }
}

async function refreshArtifacts() {
  artifacts.value = await api.automationArtifacts(selectedSpecId.value || undefined, 50);
}

async function createArtifact() {
  if (!selectedSpecId.value) {
    notice.warning("先选择一份接口规范。");
    return;
  }
  busy.value = "artifact";
  try {
    const artifact = await api.createAutomationArtifact(selectedSpecId.value);
    selectedArtifact.value = artifact;
    selectedArtifactId.value = artifact.artifact_id;
    await refreshArtifacts();
    if (artifact.status === "validated") {
      notice.success("自动化资产已生成", `v${artifact.revision} · ${artifact.case_ids.length} 条用例`);
    } else {
      notice.error(
        "资产未通过安全校验",
        artifact.validation_errors.map((issue) => issue.message).join("；"),
      );
    }
  } catch (err) {
    notice.error("生成自动化资产失败", (err as Error).message);
  } finally {
    busy.value = "";
  }
}

async function openArtifact(artifactId: string) {
  selectedArtifactId.value = artifactId;
  selectedArtifact.value = await api.automationArtifact(artifactId);
}

async function downloadArtifact(artifact: AutomationArtifactSummary | AutomationArtifact) {
  if (artifact.status !== "validated") {
    notice.warning("该资产未通过安全校验，不能下载。");
    return;
  }
  busy.value = `download:${artifact.artifact_id}`;
  try {
    const file = await api.downloadAutomationArtifact(artifact.artifact_id);
    saveBlob(file.blob, file.filename || `${artifact.artifact_id}.zip`);
    notice.success("下载已开始", file.filename);
  } catch (err) {
    notice.error("下载资产失败", (err as Error).message);
  } finally {
    busy.value = "";
  }
}

function chooseJunit(event: Event) {
  const input = event.target as HTMLInputElement;
  junitFile.value = input.files?.[0] ?? null;
}

async function importJunit() {
  if (!junitFile.value) {
    notice.warning("先选择一个 JUnit XML 文件。");
    return;
  }
  busy.value = "junit";
  try {
    const run = await api.importJunitRun(junitFile.value, selectedArtifactId.value || undefined);
    junitFile.value = null;
    if (junitInput.value) junitInput.value.value = "";
    await refreshRuns();
    await openRun(run.run_id);
    activeTab.value = "runs";
    notice.success(
      "执行结果已回收",
      `失败 ${run.failed} · 错误 ${run.errors} · 未匹配 ${run.unmatched}`,
    );
  } catch (err) {
    notice.error("导入 JUnit 失败", (err as Error).message);
  } finally {
    busy.value = "";
  }
}

async function refreshRuns() {
  runs.value = await api.testRuns({ limit: 50 });
}

async function openRun(runId: string) {
  selectedRunId.value = runId;
  const [run, events] = await Promise.all([
    api.testRun(runId),
    api.jobEvents({ runId, limit: 100 }),
  ]);
  selectedRun.value = run;
  runEvents.value = events;
}

async function createFollowUp() {
  if (!selectedRun.value) return;
  busy.value = "follow-up";
  try {
    const item = await api.createRunFollowUp(selectedRun.value.run_id, {
      priority: selectedRun.value.failed + selectedRun.value.errors > 0 ? "P1" : "P2",
    });
    await refreshItems();
    openItem(item);
    switchTab("items");
    notice.success("跟进事项已创建", item.title);
  } catch (err) {
    notice.error("创建跟进事项失败", (err as Error).message);
  } finally {
    busy.value = "";
  }
}

async function sendRunToReport() {
  if (!selectedRun.value) return;
  busy.value = "report";
  try {
    const source = await api.testRunReportSource(selectedRun.value.run_id);
    reportSession.testData = source.test_data;
    reportSession.instruction = "重点分析自动化失败、未匹配结果、回归风险，并给出修复与重跑建议。";
    notice.info("执行数据已送入报告工作台", source.suggested_title);
    await router.push("/report");
  } catch (err) {
    notice.error("准备报告数据失败", (err as Error).message);
  } finally {
    busy.value = "";
  }
}

async function quickCreate() {
  const title = quick.title.trim();
  if (!title) {
    notice.warning("先写一句要记住的事。");
    return;
  }
  busy.value = "quick";
  try {
    const item = await api.createWorkItem({
      item_type: quick.due_at || quick.remind_at ? "task" : "note",
      title,
      body: quick.body,
      status: quick.due_at ? "todo" : "inbox",
      priority: quick.priority,
      due_at: quick.due_at || null,
      remind_at: quick.remind_at || null,
      tags: splitTags(quick.tags),
    });
    quick.title = "";
    quick.body = "";
    quick.due_at = "";
    quick.remind_at = "";
    quick.tags = "";
    await refreshItems();
    openItem(item);
    notice.success("已记下", item.title);
  } catch (err) {
    notice.error("创建工作事项失败", (err as Error).message);
  } finally {
    busy.value = "";
  }
}

async function refreshItems() {
  items.value = await api.workItems({
    view: filters.view,
    q: filters.q,
    priority: filters.priority,
    tag: filters.tag,
  });
  await workStore.refreshSummary();
}

async function applyView(view: string) {
  filters.view = view;
  await refreshItems();
}

function openItem(item: WorkItem) {
  selectedItem.value = item;
  editor.title = item.title;
  editor.body = item.body;
  editor.priority = item.priority;
  editor.status = item.status;
  editor.due_at = toLocalInput(item.due_at);
  editor.remind_at = toLocalInput(item.remind_at);
  editor.tags = item.tags.join("，");
  editor.pinned = item.pinned;
  editor.preview = false;
  saveState.value = "idle";
}

async function saveItem() {
  if (!selectedItem.value) return;
  saveState.value = "saving";
  itemBusy.value = "save";
  try {
    const updated = await api.updateWorkItem(selectedItem.value.work_item_id, {
      title: editor.title.trim(),
      body: editor.body,
      priority: editor.priority,
      status: editor.status as WorkItem["status"],
      due_at: editor.due_at || null,
      remind_at: editor.remind_at || null,
      tags: splitTags(editor.tags),
      pinned: editor.pinned,
    });
    selectedItem.value = updated;
    saveState.value = "saved";
    await refreshItems();
    notice.success("工作事项已保存");
  } catch (err) {
    saveState.value = "failed";
    notice.error("保存失败", (err as Error).message);
  } finally {
    itemBusy.value = "";
  }
}

async function completeItem(item: WorkItem) {
  itemBusy.value = `complete:${item.work_item_id}`;
  try {
    const updated = await api.completeWorkItem(item.work_item_id);
    if (selectedItem.value?.work_item_id === item.work_item_id) openItem(updated);
    await refreshItems();
    notice.success("已完成", item.title);
  } catch (err) {
    notice.error("完成事项失败", (err as Error).message);
  } finally {
    itemBusy.value = "";
  }
}

async function archiveItem(item: WorkItem) {
  itemBusy.value = `archive:${item.work_item_id}`;
  try {
    await api.archiveWorkItem(item.work_item_id);
    if (selectedItem.value?.work_item_id === item.work_item_id) selectedItem.value = null;
    await refreshItems();
    notice.info("已归档", item.title);
  } catch (err) {
    notice.error("归档事项失败", (err as Error).message);
  } finally {
    itemBusy.value = "";
  }
}

async function deleteItem(item: WorkItem) {
  if (!window.confirm(`删除“${item.title}”？此操作不可撤销。`)) return;
  itemBusy.value = `delete:${item.work_item_id}`;
  try {
    await api.deleteWorkItem(item.work_item_id);
    if (selectedItem.value?.work_item_id === item.work_item_id) selectedItem.value = null;
    await refreshItems();
    notice.info("已删除", item.title);
  } catch (err) {
    notice.error("删除事项失败", (err as Error).message);
  } finally {
    itemBusy.value = "";
  }
}

function openLinkedItem(item: WorkItem) {
  const link = item.links[0];
  if (!link) return;
  if (link.resource_type === "test_run") {
    activeTab.value = "runs";
    void openRun(link.resource_id);
    return;
  }
  if (link.href.startsWith("/")) void router.push(link.href);
}

async function requestNotifications() {
  if (typeof Notification === "undefined") {
    notice.warning("当前浏览器不支持系统通知；站内提醒仍然可用。");
    return;
  }
  const permission = await Notification.requestPermission();
  notice.info(
    permission === "granted" ? "系统通知已允许" : "系统通知未开启",
    permission === "granted" ? "页面打开时，到期事项可发系统通知。" : "仍会显示站内提醒。",
  );
}

function switchTab(tab: TabKey) {
  activeTab.value = tab;
  const url = new URL(window.location.href);
  url.searchParams.set("tab", tab);
  window.history.replaceState(window.history.state, "", url);
}

function openAIDrawer(kinds: AutomationAIKind[]) {
  aiDrawerKinds.value = kinds;
  aiDrawerOpen.value = true;
}

function handleAIApplied(artifact: AutomationArtifact) {
  selectedArtifactId.value = artifact.artifact_id;
  selectedArtifact.value = artifact;
  aiDrawerOpen.value = false;
  switchTab("automation");
  void refreshArtifacts();
}

function splitTags(raw: string): string[] {
  return raw
    .split(/[,，、\s]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function toLocalInput(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function formatDate(value: string | null): string {
  if (!value) return "无日期";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function duration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
}

function statusLabel(status: string): string {
  return (
    {
      inbox: "收件箱",
      todo: "待办",
      doing: "进行中",
      done: "已完成",
      archived: "已归档",
      passed: "通过",
      failed: "失败",
      error: "错误",
      skipped: "跳过",
    }[status] ?? status
  );
}

function viewLabel(view: string): string {
  return (
    {
      today: "今日",
      overdue: "逾期",
      inbox: "收件箱",
      upcoming: "近期",
      all: "全部",
      completed: "完成",
    }[view] ?? view
  );
}
</script>

<template>
  <div class="workspace stack">
    <ErrorNote
      v-if="error"
      title="交付工作台没有完整加载"
      :message="error"
      recovery="确认后端已启动后重试。已有本地数据不会被本次加载影响。"
      @retry="loadAll"
    />

    <section class="command-band">
      <div class="command-band__intro">
        <p class="calib">DELIVERY LOOP · V2.3.2</p>
        <h2>从接口用例到下一步行动</h2>
        <p>
          生成受控脚本、回收 JUnit、把失败变成带上下文的事项。所有数据留在本地，
          工作事项不会进入 AI 或知识库。
        </p>
      </div>
      <div class="command-band__metrics">
        <div>
          <span class="label">接口规范</span>
          <strong class="mono">{{ specCount }}</strong>
        </div>
        <div>
          <span class="label">自动化资产</span>
          <strong class="mono">{{ artifactCount }}</strong>
        </div>
        <div>
          <span class="label">执行记录</span>
          <strong class="mono">{{ runCount }}</strong>
        </div>
        <div :data-alert="itemAttention > 0 ? '1' : '0'">
          <span class="label">逾期事项</span>
          <strong class="mono">{{ itemAttention }}</strong>
        </div>
      </div>
      <button type="button" class="ghost-btn" @click="requestNotifications">
        <AppIcon name="alert" :size="16" />
        通知权限
      </button>
    </section>

    <nav class="tabs" aria-label="交付工作台视图">
      <button
        type="button"
        data-testid="tab-automation"
        :class="{ 'tabs__item--on': activeTab === 'automation' }"
        @click="switchTab('automation')"
      >
        <AppIcon name="route" :size="16" />
        自动化资产
      </button>
      <button
        type="button"
        data-testid="tab-runs"
        :class="{ 'tabs__item--on': activeTab === 'runs' }"
        @click="switchTab('runs')"
      >
        <AppIcon name="play" :size="16" />
        执行记录
      </button>
      <button
        type="button"
        data-testid="tab-items"
        :class="{ 'tabs__item--on': activeTab === 'items' }"
        @click="switchTab('items')"
      >
        <AppIcon name="cases" :size="16" />
        工作事项
        <span v-if="workStore.summary?.today" class="tabs__badge mono">
          {{ workStore.summary.today }}
        </span>
      </button>
    </nav>

    <!-- 自动化资产 -->
    <section v-if="activeTab === 'automation'" class="workspace-grid workspace__stage">
      <div class="panel">
        <header class="panel__head">
          <div>
            <h3>生成可靠性脚本</h3>
            <p>固定模板输出 pytest + httpx；平台不会执行下载项目。</p>
          </div>
          <div class="row row--wrap">
            <span class="chip chip--glacier">受控生成</span>
            <button
              type="button"
              class="ai-trigger"
              :disabled="!selectedArtifact"
              data-testid="open-ai-drawer"
              @click="openAIDrawer(['operation_gap', 'fixture_recipe', 'script_review'])"
            >
              <AppIcon name="sparkle" :size="14" />
              AI 增强
            </button>
          </div>
        </header>
        <div class="panel__body stack--tight">
          <label class="field">
            <span class="label">接口规范</span>
            <el-select
              v-model="selectedSpecId"
              placeholder="选择 OpenAPI 规范"
              filterable
              style="width: 100%"
            >
              <el-option
                v-for="spec in specs"
                :key="spec.spec_id"
                :label="`${spec.title} · ${spec.stats.cases} 条用例`"
                :value="spec.spec_id"
              />
            </el-select>
          </label>
          <div v-if="selectedSpecId" class="spec-brief">
            <span class="mono">{{ selectedSpecId }}</span>
            <span>模板会把请求数据写进 JSON，不把模型输出拼成 Python 源码。</span>
          </div>
          <el-button
            type="primary"
            :loading="busy === 'artifact'"
            :disabled="!selectedSpecId"
            data-testid="create-artifact"
            @click="createArtifact"
          >
            <AppIcon name="sparkle" :size="16" />
            生成自动化资产
          </el-button>
          <EmptyState
            v-if="!specs.length && !loading"
            icon="route"
            title="还没有接口规范"
            reason="先导入 OpenAPI 3 JSON / YAML，平台会把 operation 转成契约用例。"
            action-label="去接口资产"
            @action="router.push('/apis')"
          />

          <template v-if="selectedArtifact">
            <div class="rule"></div>
            <div class="row row--wrap">
              <div>
                <h4>{{ selectedArtifact.spec_title }}</h4>
                <p class="muted mono">
                  {{ selectedArtifact.artifact_id }} · v{{ selectedArtifact.revision }}
                </p>
                <p v-if="selectedArtifact.parent_artifact_id" class="muted mono">
                  派生自 {{ selectedArtifact.parent_artifact_id }}
                </p>
              </div>
              <div class="spacer"></div>
              <span
                class="chip"
                :class="selectedArtifact.status === 'validated' ? 'chip--pass' : 'chip--fail'"
              >
                {{ selectedArtifact.status === "validated" ? "安全校验通过" : "已阻止下载" }}
              </span>
            </div>
            <div class="file-list">
              <div v-for="file in selectedArtifact.files" :key="file.path" class="file-row">
                <AppIcon name="file" :size="15" />
                <code>{{ file.path }}</code>
                <span class="mono">{{ file.content.length.toLocaleString() }} chars</span>
              </div>
            </div>
            <ul v-if="selectedArtifact.change_summary.length" class="change-summary">
              <li v-for="change in selectedArtifact.change_summary" :key="change">
                <AppIcon name="check" :size="13" />
                {{ change }}
              </li>
            </ul>
            <ul v-if="selectedArtifact.validation_errors.length" class="issue-list">
              <li v-for="issue in selectedArtifact.validation_errors" :key="`${issue.path}-${issue.code}`">
                <strong>{{ issue.code }}</strong>
                <span>{{ issue.path || "asset" }} · {{ issue.message }}</span>
              </li>
            </ul>
            <el-button
              :disabled="selectedArtifact.status !== 'validated'"
              :loading="busy === `download:${selectedArtifact.artifact_id}`"
              data-testid="download-artifact"
              @click="downloadArtifact(selectedArtifact)"
            >
              <AppIcon name="download" :size="16" />
              下载 zip
            </el-button>
          </template>
        </div>
      </div>

      <div class="panel">
        <header class="panel__head">
          <div>
            <h3>资产版本</h3>
            <p>同一规范重新生成会产生新版本，旧版保持可追溯。</p>
          </div>
          <button type="button" class="icon-btn" title="刷新资产" @click="refreshArtifacts">
            <AppIcon name="refresh" :size="16" />
          </button>
        </header>
        <div v-if="artifacts.length" class="artifact-list">
          <button
            v-for="artifact in artifacts"
            :key="artifact.artifact_id"
            type="button"
            class="artifact-row"
            :class="{ 'artifact-row--on': artifact.artifact_id === selectedArtifactId }"
            @click="openArtifact(artifact.artifact_id)"
          >
            <span class="artifact-row__mark mono">v{{ artifact.revision }}</span>
            <span class="artifact-row__main">
              <strong>{{ artifact.spec_title || artifact.spec_id }}</strong>
              <span>
                {{ artifact.case_count }} 条用例 · {{ artifact.operation_count }} 个 operation ·
                {{ artifact.file_count }} 个文件{{ artifact.parent_artifact_id ? " · AI 派生" : "" }}
              </span>
            </span>
            <span
              class="artifact-row__state"
              :data-ok="artifact.status === 'validated' ? '1' : '0'"
            >
              {{ artifact.status === "validated" ? "可下载" : "已拒绝" }}
            </span>
            <span class="artifact-row__time mono">{{ formatRelative(artifact.created_at) }}</span>
          </button>
        </div>
        <EmptyState
          v-else
          icon="layers"
          title="还没有自动化资产"
          reason="选择左侧接口规范并生成，第一版受控 pytest 项目会出现在这里。"
        />
      </div>
    </section>

    <!-- 执行记录 -->
    <section v-if="activeTab === 'runs'" class="workspace-grid workspace-grid--runs workspace__stage">
      <div class="panel">
        <header class="panel__head">
          <div>
            <h3>回收 JUnit</h3>
            <p>首版以 pytest XML 为准，未知 case_id 会保留为未匹配。</p>
          </div>
        </header>
        <div class="panel__body stack--tight">
          <label class="field">
            <span class="label">关联资产（可选）</span>
            <el-select v-model="selectedArtifactId" clearable placeholder="不关联资产" style="width: 100%">
              <el-option
                v-for="artifact in artifacts"
                :key="artifact.artifact_id"
                :label="`v${artifact.revision} · ${artifact.spec_title} · ${artifact.case_count} 条`"
                :value="artifact.artifact_id"
              />
            </el-select>
          </label>
          <input
            ref="junitInput"
            class="file-input"
            type="file"
            accept=".xml,application/xml,text/xml"
            aria-label="选择 JUnit XML"
            @change="chooseJunit"
          />
          <div v-if="junitFile" class="picked-file">
            <AppIcon name="file" :size="15" />
            <span>{{ junitFile.name }}</span>
            <span class="mono">{{ Math.ceil(junitFile.size / 1024) }} KB</span>
          </div>
          <el-button
            type="primary"
            :loading="busy === 'junit'"
            :disabled="!junitFile"
            data-testid="import-junit"
            @click="importJunit"
          >
            <AppIcon name="upload" :size="16" />
            导入执行结果
          </el-button>
          <p class="footnote">
            生成、导入和提醒确认都会写入本地结构化事件；不会记录凭据或完整请求体。
          </p>
        </div>

        <header class="panel__head panel__head--sub">
          <div>
            <h3>运行记录</h3>
            <p>按导入时间倒序。</p>
          </div>
          <button type="button" class="icon-btn" title="刷新运行记录" @click="refreshRuns">
            <AppIcon name="refresh" :size="16" />
          </button>
        </header>
        <div v-if="runs.length" class="run-list">
          <button
            v-for="run in runs"
            :key="run.run_id"
            type="button"
            class="run-row"
            :class="{ 'run-row--on': run.run_id === selectedRunId }"
            @click="openRun(run.run_id)"
          >
            <span class="run-row__rate mono" :data-tone="run.failed + run.errors ? 'fail' : 'pass'">
              {{ Math.round(run.pass_rate * 100) }}%
            </span>
            <span class="run-row__main">
              <strong>{{ run.source_file || run.run_id }}</strong>
              <span>
                {{ run.total }} 条 · 失败 {{ run.failed }} · 错误 {{ run.errors }} ·
                未匹配 {{ run.unmatched }}
              </span>
            </span>
            <span class="mono">{{ formatRelative(run.created_at) }}</span>
          </button>
        </div>
        <EmptyState
          v-else
          icon="play"
          title="还没有执行记录"
          reason="运行下载的 pytest 项目并指定 --junitxml，再把 XML 导入这里。"
        />
      </div>

      <div class="panel panel--detail">
        <template v-if="selectedRun">
          <header class="panel__head">
            <div>
              <h3>{{ selectedRun.source_file }}</h3>
              <p class="mono">{{ selectedRun.run_id }} · {{ formatDate(selectedRun.created_at) }}</p>
            </div>
            <span
              class="chip"
              :class="selectedRun.failed + selectedRun.errors ? 'chip--fail' : 'chip--pass'"
            >
              {{ selectedRun.failed + selectedRun.errors ? "需要跟进" : "全部通过" }}
            </span>
          </header>
          <div class="run-summary">
            <div>
              <span class="label">总数</span>
              <strong class="mono">{{ selectedRun.total }}</strong>
            </div>
            <div data-tone="pass">
              <span class="label">通过</span>
              <strong class="mono">{{ selectedRun.passed }}</strong>
            </div>
            <div data-tone="fail">
              <span class="label">失败</span>
              <strong class="mono">{{ selectedRun.failed }}</strong>
            </div>
            <div data-tone="warn">
              <span class="label">错误 / 跳过</span>
              <strong class="mono">{{ selectedRun.errors }} / {{ selectedRun.skipped }}</strong>
            </div>
            <div>
              <span class="label">耗时</span>
              <strong class="mono">{{ duration(selectedRun.duration_ms) }}</strong>
            </div>
            <div data-tone="warn">
              <span class="label">未匹配</span>
              <strong class="mono">{{ selectedRun.unmatched }}</strong>
            </div>
          </div>
          <div class="run-actions">
            <el-button
              type="primary"
              :loading="busy === 'follow-up'"
              data-testid="create-follow-up"
              @click="createFollowUp"
            >
              <AppIcon name="cases" :size="16" />
              创建跟进事项
            </el-button>
            <el-button :loading="busy === 'report'" @click="sendRunToReport">
              <AppIcon name="chart" :size="16" />
              送入报告工作台
            </el-button>
            <el-button data-testid="run-ai-drawer" @click="openAIDrawer(['failure_assertion'])">
              <AppIcon name="sparkle" :size="16" />
              AI 断言建议
            </el-button>
          </div>
          <ul v-if="selectedRun.warnings.length" class="notice-list">
            <li v-for="warning in selectedRun.warnings" :key="warning">{{ warning }}</li>
          </ul>
          <div v-if="failedResults.length" class="result-band">
            <h4>失败与错误</h4>
            <div v-for="result in failedResults" :key="`${result.name}-${result.case_id}`" class="result-row">
              <span class="chip chip--fail">{{ statusLabel(result.status) }}</span>
              <div>
                <strong>{{ result.name }}</strong>
                <p class="mono">{{ result.case_id || "未映射 case_id" }} · {{ result.operation_id || "未知 operation" }}</p>
                <p v-if="result.message" class="result-row__message">{{ result.message }}</p>
              </div>
            </div>
          </div>
          <div v-if="selectedRun.unmatched_cases.length" class="result-band">
            <h4>未匹配结果</h4>
            <div
              v-for="result in selectedRun.unmatched_cases"
              :key="`${result.name}-unmatched`"
              class="result-row"
            >
              <span class="chip chip--warn">{{ statusLabel(result.status) }}</span>
              <div>
                <strong>{{ result.name }}</strong>
                <p class="mono">{{ result.case_id || "缺少 case_id" }}</p>
              </div>
            </div>
          </div>
          <div class="result-band">
            <h4>结构化事件</h4>
            <div v-if="runEvents.length" class="event-list">
              <div v-for="event in runEvents" :key="event.event_id" class="event-row">
                <span class="mono">{{ event.created_at.slice(11, 19) }}</span>
                <strong>{{ event.action }}</strong>
                <span>{{ event.message || event.status }}</span>
              </div>
            </div>
            <p v-else class="muted">当前运行没有可显示的事件。</p>
          </div>
        </template>
        <EmptyState
          v-else
          icon="play"
          title="选择一条运行记录"
          reason="运行详情会显示失败、未匹配、耗时和结构化事件。"
        />
      </div>
    </section>

    <!-- 工作事项 -->
    <section v-if="activeTab === 'items'" class="items-layout workspace__stage">
      <div class="panel quick-panel">
        <header class="panel__head">
          <div>
            <h3>记一条</h3>
            <p>标题按 Enter 立即创建；有日期时自动成为任务。</p>
          </div>
          <AppIcon name="cases" :size="20" />
        </header>
        <div class="quick-form">
          <input
            v-model="quick.title"
            class="quick-input"
            type="text"
            placeholder="记下待办、决定或下一步…"
            aria-label="工作事项标题"
            data-testid="quick-title"
            @keydown.enter.prevent="quickCreate"
          />
          <textarea
            v-model="quick.body"
            class="quick-body"
            rows="2"
            placeholder="补充上下文（可选，支持 Markdown）"
            aria-label="工作事项正文"
          ></textarea>
          <div class="quick-row">
            <label>
              <span class="label">截止</span>
              <input v-model="quick.due_at" type="datetime-local" />
            </label>
            <label>
              <span class="label">提醒</span>
              <input v-model="quick.remind_at" type="datetime-local" />
            </label>
            <label>
              <span class="label">优先级</span>
              <select v-model="quick.priority">
                <option value="P0">P0</option>
                <option value="P1">P1</option>
                <option value="P2">P2</option>
                <option value="P3">P3</option>
              </select>
            </label>
            <label class="quick-tags">
              <span class="label">标签</span>
              <input v-model="quick.tags" type="text" placeholder="回归，发布" />
            </label>
          </div>
          <el-button
            type="primary"
            :loading="busy === 'quick'"
            data-testid="quick-create"
            @click="quickCreate"
          >
            <AppIcon name="check" :size="16" />
            记下来
          </el-button>
          <p class="footnote">提醒依赖页面打开时轮询；关闭页面后不承诺后台通知。</p>
        </div>
      </div>

      <div class="item-workbench">
        <div class="panel item-list-panel">
          <header class="panel__head">
            <div>
              <h3>{{ activeFilterLabel }}</h3>
              <p>{{ items.length }} 条可见事项</p>
            </div>
            <button type="button" class="icon-btn" title="刷新事项" @click="refreshItems">
              <AppIcon name="refresh" :size="16" />
            </button>
          </header>
          <div class="item-filters">
            <div class="view-tabs">
              <button
                v-for="view in ['today', 'overdue', 'inbox', 'upcoming', 'all', 'completed']"
                :key="view"
                type="button"
                :class="{ 'view-tabs__item--on': filters.view === view }"
                @click="applyView(view)"
              >
                {{ viewLabel(view) }}
              </button>
            </div>
            <div class="filter-row">
              <input
                v-model="filters.q"
                type="search"
                placeholder="搜索标题、正文或标签"
                aria-label="搜索工作事项"
                @keyup.enter="refreshItems"
              />
              <select v-model="filters.priority" aria-label="按优先级筛选" @change="refreshItems">
                <option value="">全部优先级</option>
                <option value="P0">P0</option>
                <option value="P1">P1</option>
                <option value="P2">P2</option>
                <option value="P3">P3</option>
              </select>
              <input
                v-model="filters.tag"
                type="text"
                placeholder="标签"
                aria-label="按标签筛选"
                @keyup.enter="refreshItems"
              />
              <button type="button" class="filter-btn" @click="refreshItems">筛选</button>
            </div>
          </div>
          <div v-if="items.length" class="item-list">
            <article
              v-for="item in items"
              :key="item.work_item_id"
              class="item-row"
              :class="{ 'item-row--on': selectedItem?.work_item_id === item.work_item_id }"
              @click="openItem(item)"
            >
              <button
                type="button"
                class="check-toggle"
                :title="item.status === 'done' ? '已完成' : '完成事项'"
                :aria-label="item.status === 'done' ? '已完成' : `完成 ${item.title}`"
                :disabled="item.status === 'done'"
                @click.stop="completeItem(item)"
              >
                <AppIcon v-if="item.status === 'done'" name="check" :size="14" />
              </button>
              <div class="item-row__main">
                <div class="item-row__title">
                  <span v-if="item.pinned" class="pin" title="置顶">PIN</span>
                  <strong>{{ item.title }}</strong>
                  <span class="priority mono">{{ item.priority }}</span>
                </div>
                <p v-if="item.body" class="item-row__body">{{ item.body }}</p>
                <div class="item-row__meta">
                  <span>{{ statusLabel(item.status) }}</span>
                  <span v-if="item.due_at">截止 {{ formatDate(item.due_at) }}</span>
                  <span v-if="item.remind_at">提醒 {{ formatDate(item.remind_at) }}</span>
                  <span v-for="tag in item.tags" :key="tag" class="tag">{{ tag }}</span>
                </div>
              </div>
              <AppIcon name="chevronRight" :size="15" />
            </article>
          </div>
          <EmptyState
            v-else
            icon="cases"
            title="这一栏是空的"
            reason="快速记一条，或切换视图查看其他事项。"
          />
        </div>

        <aside class="panel item-detail">
          <template v-if="selectedItem">
            <header class="panel__head">
              <div>
                <h3>事项详情</h3>
                <p class="mono">{{ selectedItem.work_item_id }}</p>
              </div>
              <span class="save-state" :data-state="saveState">{{ itemResultLabel }}</span>
            </header>
            <div class="item-detail__body">
              <label class="field">
                <span class="label">标题</span>
                <input v-model="editor.title" type="text" />
              </label>
              <div class="editor-switch">
                <button
                  type="button"
                  :class="{ 'editor-switch__item--on': !editor.preview }"
                  @click="editor.preview = false"
                >
                  编辑
                </button>
                <button
                  type="button"
                  :class="{ 'editor-switch__item--on': editor.preview }"
                  @click="editor.preview = true"
                >
                  预览
                </button>
              </div>
              <textarea
                v-if="!editor.preview"
                v-model="editor.body"
                class="markdown-editor"
                rows="12"
                placeholder="正文支持 Markdown"
              ></textarea>
              <div v-else class="markdown-preview">
                <MarkdownBody :source="editor.body || '还没有正文。'" />
              </div>
              <div class="detail-fields">
                <label>
                  <span class="label">状态</span>
                  <select v-model="editor.status">
                    <option value="inbox">收件箱</option>
                    <option value="todo">待办</option>
                    <option value="doing">进行中</option>
                    <option value="done">已完成</option>
                    <option value="archived">已归档</option>
                  </select>
                </label>
                <label>
                  <span class="label">优先级</span>
                  <select v-model="editor.priority">
                    <option value="P0">P0</option>
                    <option value="P1">P1</option>
                    <option value="P2">P2</option>
                    <option value="P3">P3</option>
                  </select>
                </label>
                <label>
                  <span class="label">截止</span>
                  <input v-model="editor.due_at" type="datetime-local" />
                </label>
                <label>
                  <span class="label">提醒</span>
                  <input v-model="editor.remind_at" type="datetime-local" />
                </label>
              </div>
              <label class="field">
                <span class="label">标签</span>
                <input v-model="editor.tags" type="text" placeholder="逗号分隔" />
              </label>
              <label class="check-field">
                <input v-model="editor.pinned" type="checkbox" />
                <span>置顶此事项</span>
              </label>
              <div v-if="selectedItem.links.length" class="linked-resources">
                <span class="label">关联资源</span>
                <button
                  v-for="link in selectedItem.links"
                  :key="`${link.resource_type}-${link.resource_id}`"
                  type="button"
                  @click="openLinkedItem(selectedItem)"
                >
                  <AppIcon name="route" :size="15" />
                  {{ link.label || link.resource_id }}
                </button>
              </div>
              <div class="item-actions">
                <el-button
                  type="primary"
                  :loading="itemBusy === 'save'"
                  data-testid="save-work-item"
                  @click="saveItem"
                >
                  保存
                </el-button>
                <el-button
                  :disabled="selectedItem.status === 'done'"
                  :loading="itemBusy === `complete:${selectedItem.work_item_id}`"
                  @click="completeItem(selectedItem)"
                >
                  完成
                </el-button>
                <el-button text @click="archiveItem(selectedItem)">归档</el-button>
                <el-button text type="danger" @click="deleteItem(selectedItem)">删除</el-button>
              </div>
            </div>
          </template>
          <EmptyState
            v-else
            icon="doc"
            title="选择一个事项"
            reason="标题、正文、日期、标签与关联资源都可以在这里检查后再保存。"
          />
        </aside>
      </div>
    </section>

    <AutomationAIDrawer
      v-model:open="aiDrawerOpen"
      :spec-id="aiDrawerSpecId"
      :artifact-id="aiDrawerArtifactId"
      :run-id="activeTab === 'runs' ? selectedRunId : ''"
      :kinds="aiDrawerKinds"
      :context-label="
        activeTab === 'runs'
          ? '基于当前失败运行生成断言建议，人工采纳后可派生新资产版本'
          : '建议、配方与脚本审查均在独立抽屉中处理，原资产版本保持不变'
      "
      @applied="handleAIApplied"
    />
  </div>
</template>

<style scoped>
.workspace {
  animation: drift-in var(--dur-slow) var(--ease) both;
}

.workspace__stage {
  min-height: 540px;
}

.ai-trigger {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 28px;
  padding: 0 9px;
  border: 1px solid var(--glacier-tint);
  border-radius: var(--radius-pill);
  background: var(--ice-0);
  color: var(--glacier-deep);
  font: inherit;
  font-size: var(--fs-xs);
  cursor: pointer;
}

.ai-trigger:hover {
  background: var(--glacier-wash);
}

.ai-trigger:disabled {
  border-color: var(--ice-3);
  color: var(--ink-3);
  cursor: default;
}

.command-band {
  display: grid;
  grid-template-columns: minmax(280px, 1fr) auto auto;
  align-items: center;
  gap: var(--s5);
  padding: var(--s5);
  border: 1px solid var(--ice-3);
  border-radius: var(--radius-lg);
  background:
    linear-gradient(112deg, var(--ice-0) 0%, var(--ice-0) 52%, var(--glacier-wash) 100%);
}

.command-band__intro h2 {
  margin: 3px 0 var(--s2);
  font-size: var(--fs-xl);
}

.command-band__intro p:last-child {
  max-width: 64ch;
  color: var(--ink-3);
  font-size: var(--fs-sm);
}

.command-band__metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(74px, auto));
  gap: var(--s3);
}

.command-band__metrics > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-left: var(--s3);
  border-left: 1px solid var(--ice-3);
}

.command-band__metrics strong {
  font-size: var(--fs-xl);
}

.command-band__metrics > div[data-alert="1"] strong {
  color: var(--fail);
}

.ghost-btn,
.icon-btn,
.filter-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 34px;
  padding: 0 10px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-0);
  color: var(--ink-2);
  font: inherit;
  font-size: var(--fs-xs);
  cursor: pointer;
}

.ghost-btn:hover,
.icon-btn:hover,
.filter-btn:hover {
  border-color: var(--glacier-tint);
  color: var(--glacier-deep);
}

.tabs {
  display: inline-flex;
  align-self: flex-start;
  gap: 3px;
  padding: 3px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-2);
}

.tabs button {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 34px;
  padding: 0 13px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--ink-3);
  font: inherit;
  font-size: var(--fs-sm);
  cursor: pointer;
}

.tabs button:hover,
.tabs .tabs__item--on {
  background: var(--ice-0);
  color: var(--ink-1);
  box-shadow: inset 0 0 0 1px var(--ice-3);
}

.tabs__badge {
  min-width: 18px;
  padding: 1px 5px;
  border-radius: var(--radius-pill);
  background: var(--fail-wash);
  color: var(--fail);
  font-size: 10px;
}

.workspace-grid {
  display: grid;
  grid-template-columns: minmax(300px, 0.82fr) minmax(460px, 1.4fr);
  gap: var(--gap-grid);
  align-items: start;
}

.workspace-grid--runs {
  grid-template-columns: minmax(330px, 0.75fr) minmax(520px, 1.45fr);
}

.panel {
  min-width: 0;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius-lg);
  background: var(--ice-0);
  overflow: hidden;
}

.panel__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s3);
  flex-wrap: wrap;
  padding: var(--s4) var(--s4) var(--s3);
  border-bottom: 1px solid var(--ice-3);
}

.panel__head--sub {
  margin-top: var(--s3);
}

.panel__head h3 {
  font-size: var(--fs-md);
}

.panel__head p {
  margin-top: 2px;
  color: var(--ink-3);
  font-size: var(--fs-xs);
}

.panel__body {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  padding: var(--s4);
}

.stack--tight {
  gap: var(--s3);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.spec-brief,
.picked-file {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--s3);
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-1);
  color: var(--ink-3);
  font-size: var(--fs-xs);
}

.picked-file {
  flex-direction: row;
  align-items: center;
  gap: var(--s2);
}

.picked-file span:last-child {
  margin-left: auto;
}

.file-input {
  width: 100%;
  padding: var(--s2);
  border: 1px dashed var(--ice-4);
  border-radius: var(--radius);
  background: var(--ice-1);
  color: var(--ink-2);
  font: inherit;
  font-size: var(--fs-xs);
}

.file-list {
  display: flex;
  flex-direction: column;
  gap: 1px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  overflow: hidden;
}

.file-row {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--s2);
  padding: 7px 9px;
  background: var(--ice-1);
  font-size: var(--fs-xs);
}

.file-row + .file-row {
  border-top: 1px solid var(--ice-3);
}

.file-row code {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-row span {
  color: var(--ink-3);
}

.change-summary {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin: 0;
  padding: var(--s2) var(--s3);
  list-style: none;
  border-left: 2px solid var(--pass);
  background: var(--pass-wash);
  color: var(--pass);
  font-size: 10.5px;
}

.change-summary li {
  display: flex;
  align-items: center;
  gap: 5px;
}

.issue-list,
.notice-list,
.event-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.issue-list li {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--s2);
  padding: var(--s2);
  border-left: 2px solid var(--fail);
  background: var(--fail-wash);
  color: var(--fail);
  font-size: var(--fs-xs);
}

.artifact-list,
.run-list {
  display: flex;
  flex-direction: column;
}

.artifact-row,
.run-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  align-items: center;
  gap: var(--s3);
  width: 100%;
  padding: 12px var(--s4);
  border: none;
  border-bottom: 1px solid var(--ice-3);
  background: transparent;
  color: var(--ink-2);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.run-row {
  grid-template-columns: 48px minmax(0, 1fr) auto;
}

.artifact-row:hover,
.run-row:hover,
.artifact-row--on,
.run-row--on {
  background: var(--glacier-wash);
}

.artifact-row--on,
.run-row--on {
  box-shadow: inset 2px 0 var(--glacier);
}

.artifact-row__mark {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--ice-4);
  border-radius: 50%;
  color: var(--glacier-deep);
  font-size: 11px;
}

.artifact-row__main,
.run-row__main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.artifact-row__main strong,
.run-row__main strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ink-1);
  font-size: var(--fs-sm);
}

.artifact-row__main span,
.run-row__main span,
.artifact-row__time {
  color: var(--ink-3);
  font-size: 10.5px;
}

.artifact-row__state {
  color: var(--fail);
  font-size: var(--fs-xs);
}

.artifact-row__state[data-ok="1"] {
  color: var(--pass);
}

.run-row__rate {
  display: grid;
  place-items: center;
  width: 44px;
  height: 34px;
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
}

.run-row__rate[data-tone="pass"] {
  background: var(--pass-wash);
  color: var(--pass);
}

.run-row__rate[data-tone="fail"] {
  background: var(--fail-wash);
  color: var(--fail);
}

.run-summary {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: var(--s3);
  padding: var(--s4);
  border-bottom: 1px solid var(--ice-3);
}

.run-summary div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.run-summary strong {
  font-size: var(--fs-lg);
}

.run-summary [data-tone="pass"] strong {
  color: var(--pass);
}

.run-summary [data-tone="fail"] strong {
  color: var(--fail);
}

.run-summary [data-tone="warn"] strong {
  color: var(--warn);
}

.run-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2);
  padding: var(--s4);
  border-bottom: 1px solid var(--ice-3);
}

.notice-list {
  margin: var(--s4);
  padding-left: var(--s5);
  list-style: disc;
  color: var(--warn);
  font-size: var(--fs-xs);
}

.result-band {
  padding: var(--s4);
  border-top: 1px solid var(--ice-3);
}

.result-band h4 {
  margin-bottom: var(--s3);
}

.result-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: var(--s3);
  padding: var(--s3) 0;
}

.result-row + .result-row {
  border-top: 1px solid var(--ice-3);
}

.result-row p {
  color: var(--ink-3);
  font-size: var(--fs-xs);
}

.result-row__message {
  margin-top: 4px;
  color: var(--fail) !important;
}

.event-row {
  display: grid;
  grid-template-columns: 70px 150px minmax(0, 1fr);
  gap: var(--s2);
  padding: 6px 0;
  font-size: var(--fs-xs);
  border-top: 1px solid var(--ice-3);
}

.event-row span {
  color: var(--ink-3);
}

.footnote {
  color: var(--ink-3);
  font-size: 10.5px;
  line-height: 1.55;
}

.items-layout {
  display: grid;
  gap: var(--gap-grid);
}

.quick-form {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  padding: var(--s4);
}

.quick-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--ice-4);
  border-radius: var(--radius);
  background: var(--ice-1);
  color: var(--ink-1);
  font: inherit;
  font-size: var(--fs-md);
}

.quick-body,
.markdown-editor,
.field input,
.detail-fields input,
.detail-fields select,
.quick-row input,
.quick-row select,
.filter-row input,
.filter-row select {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--ice-4);
  border-radius: var(--radius);
  background: var(--ice-1);
  color: var(--ink-1);
  font: inherit;
  font-size: var(--fs-sm);
}

.quick-body,
.markdown-editor {
  resize: vertical;
  font-family: var(--font-ui);
  line-height: 1.65;
}

.quick-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(130px, 1fr)) minmax(150px, 1fr);
  gap: var(--s3);
}

.quick-row label,
.detail-fields label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.item-workbench {
  display: grid;
  grid-template-columns: minmax(380px, 1fr) minmax(420px, 1fr);
  gap: var(--gap-grid);
  align-items: start;
}

.item-list-panel {
  min-width: 0;
}

.item-filters {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  border-bottom: 1px solid var(--ice-3);
}

.view-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
}

.view-tabs button,
.editor-switch button {
  min-height: 28px;
  padding: 0 9px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--ink-3);
  font: inherit;
  font-size: var(--fs-xs);
  cursor: pointer;
}

.view-tabs button:hover,
.view-tabs .view-tabs__item--on,
.editor-switch button:hover,
.editor-switch .editor-switch__item--on {
  border-color: var(--ice-3);
  background: var(--ice-1);
  color: var(--ink-1);
}

.filter-row {
  display: grid;
  grid-template-columns: minmax(140px, 1fr) 108px 100px auto;
  gap: var(--s2);
}

.item-list {
  display: flex;
  flex-direction: column;
}

.item-row {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) 16px;
  gap: var(--s3);
  align-items: start;
  padding: 12px var(--s4);
  border-bottom: 1px solid var(--ice-3);
  cursor: pointer;
}

.item-row:hover,
.item-row--on {
  background: var(--glacier-wash);
}

.item-row--on {
  box-shadow: inset 2px 0 var(--glacier);
}

.check-toggle {
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  margin-top: 2px;
  border: 1px solid var(--ice-5);
  border-radius: 50%;
  background: transparent;
  color: var(--pass);
  cursor: pointer;
}

.check-toggle:disabled {
  border-color: var(--pass);
  background: var(--pass-wash);
  cursor: default;
}

.item-row__main {
  min-width: 0;
}

.item-row__title {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.item-row__title strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-sm);
}

.pin,
.priority,
.tag {
  flex: none;
  padding: 1px 5px;
  border-radius: var(--radius-sm);
  background: var(--ice-2);
  color: var(--ink-3);
  font-size: 9px;
  letter-spacing: 0.05em;
}

.priority {
  margin-left: auto;
}

.item-row__body {
  margin-top: 2px;
  overflow: hidden;
  color: var(--ink-3);
  font-size: var(--fs-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-row__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 5px;
  color: var(--ink-3);
  font-size: 10.5px;
}

.item-detail__body {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  padding: var(--s4);
}

.save-state {
  color: var(--ink-3);
  font-size: var(--fs-xs);
}

.save-state[data-state="saving"] {
  color: var(--glacier);
}

.save-state[data-state="saved"] {
  color: var(--pass);
}

.save-state[data-state="failed"] {
  color: var(--fail);
}

.editor-switch {
  display: inline-flex;
  align-self: flex-start;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius-sm);
  background: var(--ice-2);
}

.markdown-preview {
  min-height: 220px;
  max-height: 420px;
  padding: var(--s3);
  overflow-y: auto;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-1);
}

.detail-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s3);
}

.check-field {
  display: flex;
  align-items: center;
  gap: var(--s2);
  font-size: var(--fs-sm);
}

.linked-resources {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2);
  padding: var(--s3);
  border: 1px solid var(--glacier-tint);
  border-radius: var(--radius);
  background: var(--glacier-wash);
}

.linked-resources .label {
  width: 100%;
}

.linked-resources button {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 8px;
  border: 1px solid var(--glacier-tint);
  border-radius: var(--radius-sm);
  background: var(--ice-0);
  color: var(--glacier-deep);
  font: inherit;
  font-size: var(--fs-xs);
  cursor: pointer;
}

.item-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2);
  padding-top: var(--s3);
  border-top: 1px solid var(--ice-3);
}

@media (max-width: 1250px) {
  .command-band {
    grid-template-columns: minmax(240px, 1fr) auto;
  }

  .command-band .ghost-btn {
    grid-column: 1 / -1;
    justify-self: start;
  }

  .workspace-grid,
  .workspace-grid--runs,
  .item-workbench {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 760px) {
  .command-band {
    grid-template-columns: minmax(0, 1fr);
    padding: var(--s4);
  }

  .command-band__metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
  }

  .tabs {
    width: 100%;
    overflow-x: auto;
  }

  .tabs button {
    flex: 1 0 auto;
    justify-content: center;
  }

  .run-summary {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .quick-row,
  .detail-fields {
    grid-template-columns: minmax(0, 1fr);
  }

  .filter-row {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  }

  .filter-row input:first-child {
    grid-column: 1 / -1;
  }

  .artifact-row {
    grid-template-columns: auto minmax(0, 1fr) auto;
  }

  .artifact-row__time {
    display: none;
  }

  .event-row {
    grid-template-columns: 64px minmax(0, 1fr);
  }

  .event-row span:last-child {
    grid-column: 1 / -1;
  }
}
</style>
