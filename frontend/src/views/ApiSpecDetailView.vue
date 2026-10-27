<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api, saveBlob } from "@/api";
import type { ApiAssertion, ApiCaseSpec, ApiOperation, ApiSpec } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorNote from "@/components/ErrorNote.vue";
import SectionCard from "@/components/SectionCard.vue";
import StatReadout from "@/components/StatReadout.vue";
import WarningList from "@/components/WarningList.vue";
import { confirmAction } from "@/composables/useFeedback";
import { useNoticeStore } from "@/stores/notice";
import { formatBytes, formatDuration, formatTime } from "@/utils/labels";

const route = useRoute();
const router = useRouter();
const notice = useNoticeStore();

const specId = computed(() => String(route.params.specId ?? ""));
const spec = ref<ApiSpec | null>(null);
const operations = ref<ApiOperation[]>([]);
const cases = ref<ApiCaseSpec[]>([]);
const loading = ref(true);
const error = ref("");
const exporting = ref(false);
const reviewing = ref(false);
const reviewExpanded = ref(false);
let reviewPollTimer: number | undefined;
const keyword = ref("");
const selected = ref<ApiOperation | null>(null);
const viewportWidth = ref(typeof window === "undefined" ? 1440 : window.innerWidth);

const filteredOperations = computed(() => {
  const needle = keyword.value.trim().toLowerCase();
  if (!needle) return operations.value;
  return operations.value.filter((operation) =>
    `${operation.method} ${operation.path} ${operation.summary} ${operation.operation_id} ${operation.tags.join(" ")}`
      .toLowerCase()
      .includes(needle),
  );
});

const selectedCases = computed(() =>
  selected.value
    ? cases.value.filter((item) => item.operation_id === selected.value?.operation_id)
    : [],
);

const manualAssertions = computed(() =>
  cases.value.reduce(
    (sum, item) => sum + item.assertions.filter((assertion) => assertion.status === "manual").length,
    0,
  ),
);

const missingConstrainOps = computed(
  () => operations.value.filter((operation) => operation.warnings.length).length,
);
const reviewRunning = computed(
  () => reviewing.value || spec.value?.ai_review?.meta.status === "running",
);
const reviewCompleted = computed(
  () => spec.value?.ai_review?.meta.status === "completed" && spec.value.ai_review.meta.used,
);
const visibleReviewFindings = computed(() => {
  const findings = spec.value?.ai_review?.findings ?? [];
  return reviewExpanded.value ? findings : findings.slice(0, 3);
});

const serverLabel = computed(
  () => spec.value?.servers[0]?.url || "{{baseUrl}}（导出后在 Postman 环境中配置）",
);
const drawerSize = computed(() => (viewportWidth.value <= 900 ? "94vw" : "760px"));

function syncViewport(): void {
  viewportWidth.value = window.innerWidth;
}

onMounted(() => {
  syncViewport();
  window.addEventListener("resize", syncViewport);
  void load();
});

onUnmounted(() => {
  window.removeEventListener("resize", syncViewport);
  if (reviewPollTimer !== undefined) window.clearTimeout(reviewPollTimer);
});

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const [detail, operationItems, caseCollection] = await Promise.all([
      api.apiSpec(specId.value),
      api.apiOperations(specId.value),
      api.apiCases(specId.value),
    ]);
    spec.value = detail;
    operations.value = operationItems;
    cases.value = caseCollection.cases;
    if (detail.ai_review?.meta.status === "running") scheduleReviewPoll();
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    loading.value = false;
  }
}

function scheduleReviewPoll(): void {
  if (reviewPollTimer !== undefined) window.clearTimeout(reviewPollTimer);
  reviewPollTimer = window.setTimeout(async () => {
    try {
      const detail = await api.apiSpec(specId.value);
      if (!spec.value) return;
      spec.value = { ...spec.value, ai_review: detail.ai_review };
      if (detail.ai_review?.meta.status === "running") {
        scheduleReviewPoll();
      }
    } catch {
      if (spec.value?.ai_review?.meta.status === "running") scheduleReviewPoll();
    }
  }, 2000);
}

function caseCount(operationId: string): number {
  return cases.value.filter((item) => item.operation_id === operationId).length;
}

function operationRequirementIds(operation: ApiOperation): string[] {
  return operation.requirement_ids.length
    ? operation.requirement_ids
    : Array.from(
        new Set(
          cases.value
            .filter((item) => item.operation_id === operation.operation_id)
            .flatMap((item) => item.requirement_ids),
        ),
      );
}

function requiredParamCount(operation: ApiOperation): number {
  return operation.parameters.filter((item) => item.required).length;
}

function responseCodes(operation: ApiOperation): string {
  return operation.responses.map((item) => item.status_code).join(" / ") || "—";
}

function openOperation(operation: ApiOperation): void {
  selected.value = operation;
}

async function backToOperation(): Promise<void> {
  const id = selected.value?.operation_id;
  selected.value = null;
  if (!id) return;
  await nextTick();
  document.querySelector(`[data-operation-id="${CSS.escape(id)}"]`)?.scrollIntoView({
    block: "center",
    behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
  });
}

async function exportPostman(): Promise<void> {
  if (!spec.value) return;
  exporting.value = true;
  try {
    const file = await api.exportApiPostman(spec.value.spec_id);
    saveBlob(
      file.blob,
      file.filename || `${spec.value.title}.postman_collection.json`,
    );
    notice.success("Postman Collection 已导出", file.filename || undefined);
  } catch (err) {
    notice.error("导出失败", (err as Error).message);
  } finally {
    exporting.value = false;
  }
}

async function reviewWithAi(): Promise<void> {
  if (!spec.value || reviewRunning.value || reviewCompleted.value) return;
  const calls = Math.min(6, Math.ceil(spec.value.stats.operations / 12));
  const confirmed = await confirmAction({
    title: "只读复核",
    message: `最多调用模型 ${calls} 次，只给出建议，不改写用例。`,
    confirmText: "开始复核",
  });
  if (!confirmed) return;
  reviewing.value = true;
  try {
    const result = await api.reviewApiSpec(spec.value.spec_id);
    spec.value = { ...spec.value, ai_review: result };
    if (reviewPollTimer !== undefined) window.clearTimeout(reviewPollTimer);
    if (result.meta.used) {
      notice.success(
        "只读复核完成",
        `${result.findings.length} 条只读建议 · 覆盖 ${result.meta.reviewed_operations} 个 operation`,
      );
    } else {
      notice.info("只读复核未完成", result.meta.warnings[0] || "确定性用例保持不变。");
    }
  } catch (err) {
    notice.error("只读复核失败", (err as Error).message);
  } finally {
    reviewing.value = false;
  }
}

function openReviewFinding(operationId: string): void {
  const operation = operations.value.find((item) => item.operation_id === operationId);
  if (operation) selected.value = operation;
}

async function remove(): Promise<void> {
  if (!spec.value) return;
  const confirmed = await confirmAction({
    title: "删除接口规范",
    message: `将删除「${spec.value.title}」及 ${spec.value.stats.cases} 条契约用例，删除后不可恢复。`,
    confirmText: "删除",
    danger: true,
  });
  if (!confirmed) return;
  try {
    await api.deleteApiSpec(spec.value.spec_id);
    notice.success("接口规范已删除");
    await router.push("/apis");
  } catch (err) {
    notice.error("删除失败", (err as Error).message);
  }
}

function categoryLabel(value: ApiCaseSpec["category"]): string {
  return {
    positive: "正向",
    negative: "异常",
    boundary: "边界",
    security: "安全",
    contract: "契约",
  }[value];
}

function assertionTone(assertion: ApiAssertion): string {
  return assertion.status === "manual" ? "chip--warn" : "chip--pass";
}

function expectedText(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "string") return value || '""';
  const rendered = JSON.stringify(value);
  return rendered === undefined ? "—" : rendered;
}
</script>

<template>
  <div class="stack">
    <ErrorNote
      v-if="error"
      title="接口规范没有取到"
      :message="error"
      recovery="可能已被删除；回到接口资产列表确认，或检查后端是否已启动。"
      @retry="load"
    />

    <template v-if="spec">
      <SectionCard
        :title="spec.title || '未命名接口规范'"
        :sub="`OpenAPI ${spec.openapi_version} · ${spec.source_file} · 导入于 ${formatTime(spec.created_at)}`"
        icon="route"
      >
        <template #actions>
          <el-button size="small" @click="router.push('/apis')">返回列表</el-button>
          <el-button
            size="small"
            :loading="reviewRunning"
            :disabled="reviewRunning || reviewCompleted"
            :title="
              reviewCompleted
                ? '当前规范已完成只读复核'
                : reviewRunning
                  ? '只读复核任务正在执行'
                  : '只读复核，不改写用例'
            "
            @click="reviewWithAi"
          >
            <AppIcon name="sparkle" :size="14" />
            {{ reviewCompleted ? "已完成只读复核" : reviewRunning ? "只读复核中" : "只读复核" }}
          </el-button>
          <el-button size="small" :loading="exporting" @click="exportPostman">
            <AppIcon name="download" :size="14" /> Postman 2.1
          </el-button>
          <el-button size="small" @click="remove">
            <AppIcon name="trash" :size="17" /> 删除
          </el-button>
        </template>

        <div class="grid grid--4">
          <StatReadout label="Operations" :value="spec.stats.operations" tone="glacier" hint="OpenAPI paths 下可执行的 HTTP 操作" />
          <StatReadout label="契约用例" :value="spec.stats.cases" hint="正向 + 异常 + 边界 + 安全用例" />
          <StatReadout
            label="Schema 断言"
            :value="spec.stats.contract_assertions"
            :tone="manualAssertions ? 'warn' : 'pass'"
            :hint="manualAssertions ? `${manualAssertions} 条断言待人工补充` : '全部断言均可追溯到 schema'"
          />
          <StatReadout
            label="待补异常"
            :value="spec.stats.operation_gaps"
            :tone="spec.stats.operation_gaps ? 'warn' : 'pass'"
            hint="无法仅凭规范确定异常输入的 operation 数；不等同于接口缺陷。"
          />
        </div>

        <hr class="rule" />

        <div class="meta">
          <span class="chip chip--ghost mono">{{ spec.spec_id }}</span>
          <span class="chip chip--ghost">规范版本 {{ spec.version || "未标注" }}</span>
          <span class="chip chip--ghost">源文件 {{ formatBytes(spec.size_bytes) }}</span>
          <span class="chip" :class="spec.security_schemes.length ? 'chip--glacier' : 'chip--ghost'">
            安全方案 {{ spec.security_schemes.length }}
          </span>
          <span class="chip" :class="missingConstrainOps ? 'chip--warn' : 'chip--pass'">
            {{
              missingConstrainOps
                ? `${missingConstrainOps} 个 operation 需人工补异常`
                : "异常输入可确定性生成"
            }}
          </span>
        </div>

        <p v-if="spec.description" class="description pre">{{ spec.description }}</p>
        <p class="server mono">
          <span class="label">Server</span>
          {{ serverLabel }}
        </p>
        <WarningList :items="spec.warnings" />
      </SectionCard>

      <section class="strip">
        <div class="strip__cell">
          <p class="strip__k">Operations</p>
          <p class="strip__v mono">{{ filteredOperations.length }} / {{ operations.length }}</p>
        </div>
        <div class="spacer" />
        <div class="search">
          <AppIcon name="search" :size="15" />
          <input v-model="keyword" type="search" placeholder="方法 / 路径 / operationId / 标签" aria-label="搜索 operation" />
        </div>
        <el-button size="small" @click="load"><AppIcon name="refresh" :size="14" /> 刷新</el-button>
      </section>

      <SectionCard
        v-if="filteredOperations.length"
        title="Operations"
        :sub="`${spec.stats.positive_cases} 条正向 · ${spec.stats.negative_cases} 条异常/边界/安全`"
        icon="layers"
        flush
      >
        <el-table :data="filteredOperations" size="small" row-key="operation_id">
          <el-table-column label="Method" width="90">
            <template #default="{ row }">
              <span class="method mono" :data-method="row.method">{{ row.method }}</span>
            </template>
          </el-table-column>
          <el-table-column label="Path / operationId" min-width="250">
            <template #default="{ row }">
              <button
                type="button"
                class="path"
                :data-operation-id="row.operation_id"
                @click="openOperation(row)"
              >
                {{ row.path }}
              </button>
              <p class="sub mono">{{ row.operation_id }}<span v-if="row.summary"> · {{ row.summary }}</span></p>
            </template>
          </el-table-column>
          <el-table-column label="请求约束" width="122">
            <template #default="{ row }">
              <span class="mono muted">
                {{ requiredParamCount(row) }} 参数
                <template v-if="row.request_body"> · Body</template>
              </span>
            </template>
          </el-table-column>
          <el-table-column label="响应" min-width="126">
            <template #default="{ row }">
              <span class="codes mono">{{ responseCodes(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="需求追溯" width="130">
            <template #default="{ row }">
              <span v-if="operationRequirementIds(row).length" class="mono req">
                {{ operationRequirementIds(row).join(", ") }}
              </span>
              <span v-else class="muted">未标注</span>
            </template>
          </el-table-column>
          <el-table-column label="待补异常" width="92">
            <template #default="{ row }">
              <span class="chip" :class="row.warnings.length ? 'chip--warn' : 'chip--pass'">
                {{ row.warnings.length ? `${row.warnings.length} 条` : "无" }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="用例" width="86" align="right">
            <template #default="{ row }"><span class="mono num">{{ caseCount(row.operation_id) }}</span></template>
          </el-table-column>
          <el-table-column label="操作" width="98" align="right">
            <template #default="{ row }">
              <el-button size="small" text @click="openOperation(row)">查看用例</el-button>
            </template>
          </el-table-column>
        </el-table>
      </SectionCard>

      <SectionCard v-else title="没有匹配的 operation" icon="route">
        <EmptyState
          icon="route"
          title="换个关键词再试"
          reason="可以按 HTTP 方法、路径、operationId 或 OpenAPI tag 搜索。"
        />
      </SectionCard>

      <SectionCard
        v-if="spec.ai_review"
        title="只读复核建议"
        :sub="
          spec.ai_review.meta.status === 'running'
            ? '正在执行只读复核'
            : `${spec.ai_review.findings.length} 条建议 · 覆盖 ${spec.ai_review.meta.reviewed_operations} 个 operation · ${formatDuration(spec.ai_review.meta.elapsed_ms)}`
        "
        icon="sparkle"
      >
        <template #actions>
          <span class="chip chip--warn">只读，不改写确定性用例</span>
          <el-button
            v-if="spec.ai_review.findings.length > 3"
            size="small"
            text
            @click="reviewExpanded = !reviewExpanded"
          >
            {{ reviewExpanded ? "收起" : `展开全部 ${spec.ai_review.findings.length} 条` }}
            <AppIcon :name="reviewExpanded ? 'chevronDown' : 'chevronRight'" :size="13" />
          </el-button>
        </template>

        <div class="review-meta">
          <span class="chip chip--ghost mono">
            {{ spec.ai_review.meta.prompt_id }}@{{ spec.ai_review.meta.prompt_version }}
          </span>
          <span class="chip chip--ghost">{{ spec.ai_review.meta.model || spec.ai_review.meta.provider }}</span>
          <span class="chip chip--ghost mono">{{ spec.ai_review.meta.llm_calls }} 次调用</span>
          <span class="chip chip--ghost">{{ formatTime(spec.ai_review.created_at) }}</span>
          <span v-if="spec.ai_review.meta.status === 'running'" class="chip chip--glacier is-unfrozen">
            复核中
          </span>
        </div>

        <WarningList :items="spec.ai_review.meta.warnings" />

        <p v-if="spec.ai_review.meta.status === 'running'" class="review-running">
          处理中，完成后自动刷新。
        </p>
        <template v-else-if="spec.ai_review.findings.length">
          <ul class="review-list">
            <li
              v-for="finding in visibleReviewFindings"
              :key="`${finding.operation_id}-${finding.target}-${finding.issue}`"
            >
              <div class="review-head">
                <span class="chip" :class="finding.severity === 'warning' ? 'chip--warn' : 'chip--ghost'">
                  {{ finding.severity === "warning" ? "需关注" : "建议" }}
                </span>
                <button type="button" class="review-op mono" @click="openReviewFinding(finding.operation_id)">
                  {{ finding.operation_id }}
                </button>
                <span class="muted mono">{{ finding.target }}</span>
              </div>
              <p class="review-issue">{{ finding.issue }}</p>
              <p v-if="finding.suggestion" class="review-suggestion">{{ finding.suggestion }}</p>
              <p class="review-source mono">
                {{ finding.source_ref }}
                <template v-if="finding.uncertainty_reason"> · {{ finding.uncertainty_reason }}</template>
              </p>
            </li>
          </ul>
          <p v-if="spec.ai_review.findings.length > visibleReviewFindings.length" class="review-more muted">
            另有 {{ spec.ai_review.findings.length - visibleReviewFindings.length }} 条建议已收起。
          </p>
        </template>
        <p v-else class="muted">本次复核未发现需要人工补充的接口测试点。</p>
      </SectionCard>

      <el-drawer
        :model-value="Boolean(selected)"
        :size="drawerSize"
        direction="rtl"
        @close="selected = null"
      >
        <template #header>
          <div class="drawer-head">
            <span class="method mono" :data-method="selected?.method">{{ selected?.method }}</span>
            <span class="mono drawer-path">{{ selected?.path }}</span>
          </div>
        </template>

        <div v-if="selected" class="drawer">
          <section class="brief">
            <div class="brief__id">
              <span class="label">Operation</span>
              <span class="mono">{{ selected.operation_id }}</span>
            </div>
            <p v-if="selected.summary" class="brief__summary">{{ selected.summary }}</p>
            <p v-if="selected.description" class="brief__description pre">{{ selected.description }}</p>
            <div class="meta">
              <span class="chip chip--ghost mono">{{ selected.source_ref }}</span>
              <span v-for="requirement in operationRequirementIds(selected)" :key="requirement" class="chip chip--glacier mono">
                {{ requirement }}
              </span>
              <span class="chip" :class="selected.security.length ? 'chip--glacier' : 'chip--ghost'">
                {{ selected.security.length ? "需要鉴权" : "未声明鉴权" }}
              </span>
            </div>
            <button type="button" class="back-op" @click="backToOperation">
              <AppIcon name="target" :size="14" /> 回到来源 operation
            </button>
            <WarningList :items="selected.warnings" />
          </section>

          <section class="params">
            <h3>请求定义</h3>
            <div v-if="selected.parameters.length" class="param-list">
              <div v-for="parameter in selected.parameters" :key="`${parameter.location}-${parameter.name}`" class="param">
                <span class="chip">{{ parameter.location }}</span>
                <span class="mono param__name">{{ parameter.name }}</span>
                <span v-if="parameter.required" class="chip chip--warn">必填</span>
                <span class="muted param__schema">{{ JSON.stringify(parameter.schema) }}</span>
              </div>
            </div>
            <p v-else class="muted">operation 未声明请求参数。</p>
            <div v-if="selected.request_body" class="body-schema">
              <p class="label">Request body · {{ selected.request_body.required ? "必填" : "可选" }}</p>
              <p class="mono">{{ selected.request_body.content.map((item) => item.content_type).join(" / ") }}</p>
              <pre>{{ JSON.stringify(selected.request_body.content[0]?.schema ?? {}, null, 2) }}</pre>
            </div>
          </section>

          <section class="case-section">
            <div class="case-section__head">
              <h3>接口用例</h3>
              <span class="chip chip--ghost">{{ selectedCases.length }} 条</span>
            </div>

            <el-collapse v-if="selectedCases.length" accordion>
              <el-collapse-item
                v-for="item in selectedCases"
                :key="item.case_id"
                :name="item.case_id"
              >
                <template #title>
                  <div class="case-title">
                    <span class="chip chip--ghost mono">{{ item.case_id }}</span>
                    <span class="chip" :class="item.category === 'positive' ? 'chip--pass' : 'chip--warn'">
                      {{ categoryLabel(item.category) }}
                    </span>
                    <span class="case-title__text">{{ item.title }}</span>
                  </div>
                </template>

                <div class="case-body">
                  <div class="case-meta">
                    <span class="chip chip--ghost mono">{{ item.priority }}</span>
                    <span class="chip chip--ghost mono">{{ item.source_ref }}</span>
                    <span v-if="item.warnings.length" class="chip chip--warn">{{ item.warnings.length }} 条待补充</span>
                  </div>

                  <div v-if="item.preconditions.length" class="preconditions">
                    <p class="label">前置条件</p>
                    <ul>
                      <li v-for="precondition in item.preconditions" :key="precondition">{{ precondition }}</li>
                    </ul>
                  </div>

                  <div class="execution">
                    <p class="label">执行规格</p>
                    <p class="execution__line mono">
                      {{ item.execution.method }} {{ item.execution.url }}
                    </p>
                    <dl v-if="Object.keys(item.execution.query).length">
                      <dt>Query</dt>
                      <dd class="mono">{{ JSON.stringify(item.execution.query) }}</dd>
                    </dl>
                    <dl v-if="Object.keys(item.execution.headers).length">
                      <dt>Headers</dt>
                      <dd class="mono">{{ JSON.stringify(item.execution.headers) }}</dd>
                    </dl>
                    <pre v-if="item.execution.body !== null">{{ JSON.stringify(item.execution.body, null, 2) }}</pre>
                  </div>

                  <div class="assertions">
                    <div class="case-section__head">
                      <p class="label">契约断言</p>
                      <span class="chip" :class="item.assertions.some((a) => a.status === 'manual') ? 'chip--warn' : 'chip--pass'">
                        {{ item.assertions.length }} 条
                      </span>
                    </div>
                    <el-table :data="item.assertions" size="small">
                      <el-table-column label="状态" width="82">
                        <template #default="{ row }">
                          <span class="chip" :class="assertionTone(row)">
                            {{ row.status === "manual" ? "待补充" : "已定义" }}
                          </span>
                        </template>
                      </el-table-column>
                      <el-table-column label="目标" min-width="150">
                        <template #default="{ row }">
                          <span class="mono">{{ row.kind }}{{ row.path ? ` · ${row.path}` : "" }}</span>
                        </template>
                      </el-table-column>
                      <el-table-column label="操作符" width="84">
                        <template #default="{ row }"><span class="mono">{{ row.operator }}</span></template>
                      </el-table-column>
                      <el-table-column label="期望" min-width="120">
                        <template #default="{ row }">
                          <span class="mono">{{ expectedText(row.expected) }}</span>
                        </template>
                      </el-table-column>
                      <el-table-column label="来源" min-width="180">
                        <template #default="{ row }">
                          <span class="mono muted">{{ row.source_ref || "—" }}</span>
                        </template>
                      </el-table-column>
                    </el-table>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>
            <p v-else class="muted">该 operation 尚未生成用例。</p>
          </section>
        </div>
      </el-drawer>
    </template>

    <div v-else-if="loading" class="grid grid--2">
      <div v-for="n in 2" :key="n" class="card"><el-skeleton :rows="6" animated class="skel" /></div>
    </div>

    <SectionCard v-else title="接口规范不存在" icon="route">
      <EmptyState
        icon="route"
        title="这份接口规范已经不在了"
        reason="它可能已被删除，或链接里的编号不正确。"
        action-label="返回接口资产"
        @action="router.push('/apis')"
      />
    </SectionCard>
  </div>
</template>

<style scoped>
.meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: var(--s3);
}

.description {
  margin-top: var(--s3);
  font-size: var(--fs-sm);
  line-height: 1.7;
  color: var(--ink-2);
}

.review-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: var(--s3);
}

.review-list {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  margin: var(--s3) 0 0;
  padding: 0;
  list-style: none;
}

.review-list > li {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: var(--s3) 0;
  border-top: 1px solid var(--ice-3);
}

.review-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.review-op {
  padding: 0;
  border: none;
  background: transparent;
  color: var(--glacier-deep);
  font-size: var(--fs-xs);
  cursor: pointer;
}

.review-op:hover {
  text-decoration: underline;
}

.review-issue {
  font-size: var(--fs-sm);
  color: var(--ink-1);
}

.review-suggestion {
  font-size: var(--fs-xs);
  line-height: 1.7;
  color: var(--ink-2);
}

.review-source {
  font-size: 10.5px;
  color: var(--ink-3);
  overflow-wrap: anywhere;
}

.review-running,
.review-more {
  margin-top: var(--s3);
  font-size: var(--fs-xs);
}

.review-running {
  color: var(--glacier-deep);
}

.server {
  display: flex;
  align-items: baseline;
  gap: var(--s2);
  margin-top: var(--s3);
  font-size: var(--fs-xs);
  color: var(--ink-3);
  overflow-wrap: anywhere;
}

.strip {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--s4);
  padding: var(--s3) var(--s4);
  border: 1px solid var(--ice-3);
  border-radius: var(--radius-lg);
  background: var(--ice-0);
}

.strip__k {
  font-size: var(--fs-2xs);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  color: var(--ink-3);
}

.strip__v {
  font-size: var(--fs-lg);
  color: var(--ink-1);
}

.search {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  height: 30px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-1);
  color: var(--ink-3);
}

.search input {
  width: 250px;
  border: none;
  outline: none;
  background: transparent;
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--ink-1);
}

.method {
  display: inline-flex;
  justify-content: center;
  min-width: 48px;
  padding: 2px 8px;
  border: 1px solid var(--ice-4);
  border-radius: var(--radius-sm);
  font-size: var(--fs-2xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--glacier-deep);
  background: var(--glacier-wash);
}

.method[data-method="POST"] {
  color: var(--pass);
  background: var(--pass-wash);
}

.method[data-method="DELETE"] {
  color: var(--fail);
  background: var(--fail-wash);
}

.method[data-method="PATCH"],
.method[data-method="PUT"] {
  color: var(--warn);
  background: var(--warn-wash);
}

.path {
  border: none;
  background: transparent;
  padding: 0;
  font-family: var(--font-data);
  font-size: var(--fs-sm);
  color: var(--glacier-deep);
  cursor: pointer;
}

.path:hover {
  text-decoration: underline;
}

.sub,
.codes {
  font-size: 10.5px;
  color: var(--ink-3);
}

.req {
  font-size: var(--fs-2xs);
  color: var(--glacier-deep);
}

.drawer-head {
  display: flex;
  align-items: center;
  gap: var(--s2);
  min-width: 0;
}

.drawer-path {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ink-1);
}

.drawer {
  display: flex;
  flex-direction: column;
  gap: var(--s5);
}

.brief,
.params,
.case-section {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}

.brief__id {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.brief__summary {
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--ink-1);
}

.brief__description {
  font-size: var(--fs-sm);
  color: var(--ink-2);
}

.back-op {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 0;
  border: none;
  background: transparent;
  color: var(--glacier-deep);
  font: inherit;
  font-size: var(--fs-xs);
  cursor: pointer;
}

.back-op:hover {
  text-decoration: underline;
}

.param-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.param {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 6px 0;
  border-bottom: 1px solid var(--ice-3);
}

.param__name {
  font-size: var(--fs-sm);
  color: var(--ink-1);
}

.param__schema {
  flex: 1 1 220px;
  font-size: 10.5px;
  overflow-wrap: anywhere;
}

.body-schema {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.body-schema pre,
.execution pre {
  max-height: 260px;
  overflow: auto;
  margin: 0;
  padding: var(--s3);
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-1);
  font-family: var(--font-data);
  font-size: 11px;
  line-height: 1.55;
  color: var(--ink-2);
}

.case-section__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
}

.case-title {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  padding-right: var(--s3);
}

.case-title__text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-xs);
  color: var(--ink-2);
}

.case-body {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

.case-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.preconditions ul {
  margin: 4px 0 0;
  padding-left: 18px;
  font-size: var(--fs-xs);
  color: var(--ink-2);
}

.execution {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.execution__line {
  font-size: var(--fs-xs);
  color: var(--ink-1);
  overflow-wrap: anywhere;
}

.execution dl {
  display: grid;
  grid-template-columns: 68px 1fr;
  gap: var(--s2);
  margin: 0;
  font-size: var(--fs-xs);
}

.execution dt {
  color: var(--ink-3);
}

.execution dd {
  margin: 0;
  color: var(--ink-2);
  overflow-wrap: anywhere;
}

.assertions {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.skel {
  padding: var(--s5);
}

@media (max-width: 900px) {
  .search {
    width: 100%;
  }

  .search input {
    flex: 1;
    width: auto;
  }

  .case-title {
    flex-wrap: wrap;
  }

  .case-title__text {
    width: 100%;
    white-space: normal;
  }
}
</style>
