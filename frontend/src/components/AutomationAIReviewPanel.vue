<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import { api, saveBlob } from "@/api";
import type {
  AutomationArtifact,
  AutomationAIFinding,
  AutomationAIKind,
  AutomationAIReview,
} from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import { useNoticeStore } from "@/stores/notice";

const props = withDefaults(
  defineProps<{
    specId: string;
    artifactId?: string;
    runId?: string;
    kinds?: AutomationAIKind[];
  }>(),
  {
    artifactId: "",
    runId: "",
    kinds: () => ["operation_gap", "fixture_recipe", "script_review"],
  },
);

const emit = defineEmits<{
  (e: "changed"): void;
  (e: "applied", artifact: AutomationArtifact): void;
}>();
const notice = useNoticeStore();
const reviews = ref<AutomationAIReview[]>([]);
const selectedReviewId = ref("");
const focus = ref("");
const busy = ref("");
const loading = ref(false);

const selectedReview = computed(
  () => reviews.value.find((item) => item.review_id === selectedReviewId.value) ?? reviews.value[0] ?? null,
);

const taskInfo: Record<
  AutomationAIKind,
  { label: string; icon: string; hint: string }
> = {
  operation_gap: {
    label: "补齐 operation",
    icon: "target",
    hint: "分析未覆盖接口",
  },
  failure_assertion: {
    label: "断言建议",
    icon: "bug",
    hint: "分析失败结果",
  },
  fixture_recipe: {
    label: "数据配方",
    icon: "layers",
    hint: "生成 fixture 与测试数据",
  },
  script_review: {
    label: "只读审查",
    icon: "eye",
    hint: "检查现有脚本",
  },
};

onMounted(load);
watch(
  () => [props.specId, props.artifactId, props.runId],
  () => void load(),
);

async function load() {
  if (!props.specId) return;
  loading.value = true;
  try {
    reviews.value = await api.automationAIReviews({
      specId: props.specId,
      artifactId: props.artifactId || undefined,
      runId: props.runId || undefined,
      limit: 30,
    });
    const compatible = reviews.value.filter((item) => props.kinds.includes(item.kind));
    reviews.value = compatible;
    if (!compatible.some((item) => item.review_id === selectedReviewId.value)) {
      selectedReviewId.value = compatible[0]?.review_id ?? "";
    }
  } catch {
    reviews.value = [];
  } finally {
    loading.value = false;
  }
}

async function requestReview(kind: AutomationAIKind) {
  if (!props.specId) {
    notice.warning("先选择一份接口规范。");
    return;
  }
  if ((kind === "script_review" || kind === "operation_gap") && !props.artifactId) {
    notice.warning("先选择一个自动化资产。");
    return;
  }
  if (kind === "failure_assertion" && !props.runId) {
    notice.warning("先选择一条执行记录。");
    return;
  }
  busy.value = kind;
  try {
    const review = await api.createAutomationAIReview({
      kind,
      spec_id: props.specId,
      artifact_id: props.artifactId || null,
      run_id: props.runId || null,
      focus: focus.value.trim(),
    });
    reviews.value = [review, ...reviews.value.filter((item) => item.review_id !== review.review_id)];
    selectedReviewId.value = review.review_id;
    if (review.status === "completed") {
      notice.success(
        `${taskInfo[kind].label}完成`,
        review.findings.length
          ? `${review.findings.length} 条建议待人工处理`
          : review.recipe
            ? "数据配方已生成"
            : "没有发现需要补充的项",
      );
    } else {
      notice.warning("建议未完成", review.meta.warnings[0] || "资产保持不变。");
    }
    emit("changed");
  } catch (err) {
    notice.error("建议生成失败", (err as Error).message);
  } finally {
    busy.value = "";
  }
}

async function decideFinding(
  review: AutomationAIReview,
  finding: AutomationAIFinding,
  disposition: "accepted" | "rejected",
) {
  busy.value = finding.finding_id;
  try {
    const updated = await api.decideAutomationAIFinding(
      review.review_id,
      finding.finding_id,
      disposition,
    );
    replaceReview(updated);
    notice.info(disposition === "accepted" ? "已采纳建议" : "已驳回建议");
  } catch (err) {
    notice.error("更新建议状态失败", (err as Error).message);
  } finally {
    busy.value = "";
  }
}

function canApplyReview(review: AutomationAIReview): boolean {
  if (review.status !== "completed" || review.applied_artifact_id || review.kind === "script_review") {
    return false;
  }
  if (review.kind === "fixture_recipe") return review.decision === "accepted";
  if (review.kind === "operation_gap") {
    return review.findings.some(
      (item) => item.disposition === "accepted" && item.proposed_case !== null,
    );
  }
  return review.findings.some(
    (item) => item.disposition === "accepted" && item.proposed_assertion !== null,
  );
}

async function applyReview(review: AutomationAIReview) {
  if (!canApplyReview(review)) return;
  busy.value = `apply:${review.review_id}`;
  try {
    const artifact = await api.applyAutomationAIReview(review.review_id);
    notice.success(
      `已生成 v${artifact.revision} 派生资产`,
      artifact.status === "validated"
        ? `静态门禁通过 · ${artifact.files.length} 个文件`
        : "静态门禁未通过，新版本禁止下载",
    );
    emit("applied", artifact);
    await load();
  } catch (err) {
    notice.error("应用建议失败", (err as Error).message);
  } finally {
    busy.value = "";
  }
}

async function decideRecipe(review: AutomationAIReview, decision: "accepted" | "rejected") {
  busy.value = `recipe:${review.review_id}`;
  try {
    const updated = await api.decideAutomationAIReview(review.review_id, decision);
    replaceReview(updated);
    notice.info(decision === "accepted" ? "已采纳配方建议" : "已驳回配方建议");
  } catch (err) {
    notice.error("更新配方状态失败", (err as Error).message);
  } finally {
    busy.value = "";
  }
}

async function downloadRecipe(review: AutomationAIReview) {
  busy.value = `download:${review.review_id}`;
  try {
    const file = await api.downloadAutomationAIRecipe(review.review_id);
    saveBlob(file.blob, file.filename || `${review.review_id}-fixture-recipe.json`);
  } catch (err) {
    notice.error("下载配方失败", (err as Error).message);
  } finally {
    busy.value = "";
  }
}

function replaceReview(updated: AutomationAIReview) {
  reviews.value = reviews.value.map((item) =>
    item.review_id === updated.review_id ? updated : item,
  );
  selectedReviewId.value = updated.review_id;
}

function formatTime(value: string): string {
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

function statusLabel(status: AutomationAIReview["status"]): string {
  return { running: "生成中", completed: "待审查", failed: "失败" }[status];
}

function dispositionLabel(value: AutomationAIFinding["disposition"]): string {
  return { pending: "待决定", accepted: "已采纳", rejected: "已驳回" }[value];
}
</script>

<template>
  <section class="ai-review" aria-label="自动化建议">
    <div class="ai-review__tasks">
      <button
        v-for="kind in kinds"
        :key="kind"
        type="button"
        class="ai-task"
        :disabled="Boolean(busy)"
        @click="requestReview(kind)"
      >
        <AppIcon :name="taskInfo[kind].icon" :size="16" />
        <span>{{ taskInfo[kind].label }}</span>
        <small>{{ busy === kind ? "生成中…" : taskInfo[kind].hint }}</small>
      </button>
    </div>
    <label class="ai-review__focus">
      <span class="label">关注点（可选）</span>
      <input
        v-model="focus"
        type="text"
        maxlength="500"
        placeholder="例如：幂等、重复创建、错误响应结构"
      />
    </label>

    <div v-if="reviews.length" class="ai-review__body">
      <aside class="review-list">
        <button
          v-for="review in reviews"
          :key="review.review_id"
          type="button"
          class="review-item"
          :class="{ 'review-item--on': selectedReview?.review_id === review.review_id }"
          @click="selectedReviewId = review.review_id"
        >
          <span class="mono">{{ taskInfo[review.kind].label }}</span>
          <strong>{{ review.summary }}</strong>
          <small>
            {{ statusLabel(review.status) }} · {{ formatTime(review.created_at) }}
          </small>
        </button>
      </aside>

      <div v-if="selectedReview" class="review-detail">
        <div class="review-meta">
          <span
            class="chip"
            :class="{
              'chip--warn': selectedReview.status === 'failed',
              'chip--pass': selectedReview.status === 'completed',
            }"
          >
            {{ statusLabel(selectedReview.status) }}
          </span>
          <span class="chip chip--ghost mono">
            {{ selectedReview.meta.prompt_id }}@{{ selectedReview.meta.prompt_version }}
          </span>
          <span class="chip chip--ghost">
            {{ selectedReview.meta.model || "未调用模型" }} · {{ selectedReview.meta.llm_calls }} 次
          </span>
          <span class="spacer" />
          <span class="mono muted">{{ selectedReview.meta.elapsed_ms }} ms</span>
        </div>

        <p class="review-summary">{{ selectedReview.summary }}</p>

        <ul v-if="selectedReview.meta.warnings.length" class="review-warnings">
          <li v-for="warning in selectedReview.meta.warnings" :key="warning">{{ warning }}</li>
        </ul>

        <div v-if="selectedReview.findings.length" class="finding-list">
          <article
            v-for="finding in selectedReview.findings"
            :key="finding.finding_id"
            class="finding"
            :data-severity="finding.severity"
          >
            <div class="finding__head">
              <span class="chip" :class="finding.severity === 'warning' ? 'chip--warn' : 'chip--ghost'">
                {{ finding.severity === "warning" ? "需关注" : "建议" }}
              </span>
              <span v-if="finding.operation_id" class="chip chip--glacier mono">
                {{ finding.operation_id }}
              </span>
              <span class="spacer" />
              <span class="finding__state" :data-state="finding.disposition">
                {{ dispositionLabel(finding.disposition) }}
              </span>
            </div>
            <h5>{{ finding.target || finding.issue }}</h5>
            <p>{{ finding.issue }}</p>
            <p v-if="finding.suggestion" class="finding__suggestion">
              <strong>建议</strong>{{ finding.suggestion }}
            </p>
            <p v-if="finding.rationale" class="finding__rationale">
              <strong>依据</strong>{{ finding.rationale }}
            </p>
            <div v-if="finding.proposed_assertion" class="assertion">
              <span class="label">待人工断言提案</span>
              <code>
                {{ finding.proposed_assertion.kind }}
                {{ finding.proposed_assertion.path }}
                {{ finding.proposed_assertion.operator }}
                {{ finding.proposed_assertion.expected }}
              </code>
              <p>{{ finding.proposed_assertion.description }}</p>
            </div>
            <div v-if="finding.proposed_case" class="case-proposal">
              <span class="label">待人工 case 提案</span>
              <strong>{{ finding.proposed_case.title }}</strong>
              <p>
                {{ finding.proposed_case.operation_id }} ·
                {{ finding.proposed_case.category }} ·
                {{ finding.proposed_case.priority }}
              </p>
              <code v-for="assertion in finding.proposed_case.assertions" :key="`${assertion.kind}-${assertion.path}-${assertion.operator}`">
                {{ assertion.kind }} {{ assertion.path }} {{ assertion.operator }} {{ assertion.expected }}
              </code>
              <span v-if="!finding.proposed_case.assertions.length" class="muted">
                继承 base case 的既有断言
              </span>
            </div>
            <div class="finding__foot">
              <code>{{ finding.source_ref }}</code>
              <div class="spacer" />
              <button
                type="button"
                class="text-btn"
                :disabled="Boolean(busy) || finding.disposition === 'rejected' || Boolean(selectedReview.applied_artifact_id)"
                @click="decideFinding(selectedReview, finding, 'rejected')"
              >
                驳回
              </button>
              <button
                type="button"
                class="text-btn text-btn--primary"
                :disabled="Boolean(busy) || finding.disposition === 'accepted' || Boolean(selectedReview.applied_artifact_id)"
                @click="decideFinding(selectedReview, finding, 'accepted')"
              >
                采纳
              </button>
            </div>
          </article>
        </div>

        <div v-if="selectedReview.recipe" class="recipe">
          <div class="recipe__head">
            <div>
              <span class="label">FIXTURE / TEST DATA RECIPE</span>
              <h5>{{ selectedReview.recipe.summary }}</h5>
            </div>
            <span class="finding__state" :data-state="selectedReview.decision">
              {{ selectedReview.decision === "pending" ? "待决定" : selectedReview.decision === "accepted" ? "已采纳" : "已驳回" }}
            </span>
          </div>
          <div class="recipe__grid">
            <div>
              <h6>环境变量</h6>
              <ul>
                <li v-for="item in selectedReview.recipe.environment_variables" :key="item.name">
                  <code>{{ item.name }}</code>
                  <span>{{ item.description }}</span>
                  <span v-if="item.secret" class="chip chip--warn">secret</span>
                </li>
              </ul>
            </div>
            <div>
              <h6>Fixtures</h6>
              <ul>
                <li v-for="item in selectedReview.recipe.fixtures" :key="item.name">
                  <strong>{{ item.name }}</strong>
                  <span>{{ item.purpose }}</span>
                </li>
              </ul>
            </div>
            <div>
              <h6>测试数据</h6>
              <ul>
                <li v-for="(item, index) in selectedReview.recipe.test_data" :key="`${item.case_id}-${index}`">
                  <code>{{ item.case_id || "通用" }}</code>
                  <span>{{ item.title }}</span>
                </li>
              </ul>
            </div>
          </div>
          <ul v-if="selectedReview.recipe.execution_notes.length" class="recipe__notes">
            <li v-for="note in selectedReview.recipe.execution_notes" :key="note">{{ note }}</li>
          </ul>
          <div class="recipe__actions">
            <button
              type="button"
              class="text-btn"
              :disabled="Boolean(busy)"
              @click="downloadRecipe(selectedReview)"
            >
              <AppIcon name="download" :size="14" />
              下载 JSON
            </button>
            <div class="spacer" />
            <button
              type="button"
              class="text-btn"
              :disabled="Boolean(busy) || selectedReview.decision === 'rejected' || Boolean(selectedReview.applied_artifact_id)"
              @click="decideRecipe(selectedReview, 'rejected')"
            >
              驳回
            </button>
            <button
              type="button"
              class="text-btn text-btn--primary"
              :disabled="Boolean(busy) || selectedReview.decision === 'accepted' || Boolean(selectedReview.applied_artifact_id)"
              @click="decideRecipe(selectedReview, 'accepted')"
            >
              采纳配方
            </button>
          </div>
        </div>

        <div v-if="selectedReview.kind !== 'script_review'" class="apply-bar">
          <div>
            <strong>
              {{
                selectedReview.applied_artifact_id
                  ? "已生成派生版本"
                  : "生成派生版本"
              }}
            </strong>
            <span>
              {{
                selectedReview.applied_artifact_id
                  ? selectedReview.applied_artifact_id
                  : "原版本不变"
              }}
            </span>
          </div>
          <div class="spacer" />
          <button
            type="button"
            class="apply-btn"
            :disabled="Boolean(busy) || !canApplyReview(selectedReview)"
            @click="applyReview(selectedReview)"
          >
            <AppIcon name="sparkle" :size="15" />
            {{ busy === `apply:${selectedReview.review_id}` ? "生成中…" : "应用并生成新版本" }}
          </button>
        </div>

        <p
          v-if="selectedReview.status === 'completed' && !selectedReview.findings.length && !selectedReview.recipe"
          class="review-empty"
        >
          {{ selectedReview.summary || "当前没有需要人工补充的建议。" }}
        </p>
      </div>
    </div>

    <p v-else-if="!loading" class="review-empty">
      暂无建议。
    </p>
  </section>
</template>

<style scoped>
.ai-review {
  min-width: 0;
  padding: var(--s4);
  border-top: 1px solid var(--ice-3);
  background: color-mix(in srgb, var(--ice-1) 72%, var(--ice-0));
}

.review-meta,
.finding__head,
.finding__foot,
.recipe__head,
.recipe__actions {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
}

.ai-review__tasks {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2);
}

.ai-task {
  display: grid;
  grid-template-columns: auto auto;
  align-items: center;
  gap: 2px 7px;
  padding: 7px 10px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-0);
  color: var(--ink-2);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.ai-task:hover {
  border-color: var(--glacier-tint);
  color: var(--glacier-deep);
}

.ai-task small {
  grid-column: 2;
  color: var(--ink-3);
  font-size: 9.5px;
}

.ai-task:disabled {
  opacity: 0.65;
  cursor: wait;
}

.ai-review__focus {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: var(--s3);
}

.ai-review__focus input {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--ice-4);
  border-radius: var(--radius);
  background: var(--ice-0);
  color: var(--ink-1);
  font: inherit;
  font-size: var(--fs-sm);
}

.ai-review__body {
  display: grid;
  grid-template-columns: minmax(150px, 0.38fr) minmax(0, 1fr);
  gap: var(--s3);
  margin-top: var(--s4);
  padding-top: var(--s4);
  border-top: 1px solid var(--ice-3);
}

.review-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.review-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  padding: 8px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--ink-2);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.review-item:hover,
.review-item--on {
  border-color: var(--ice-3);
  background: var(--ice-0);
}

.review-item span,
.review-item small {
  color: var(--ink-3);
  font-size: 9.5px;
}

.review-item strong {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  font-size: var(--fs-xs);
  font-weight: 500;
}

.review-detail {
  min-width: 0;
}

.review-summary {
  margin: var(--s3) 0;
  font-size: var(--fs-sm);
  color: var(--ink-1);
}

.review-warnings,
.recipe__notes {
  margin: 0 0 var(--s3);
  padding-left: var(--s4);
  color: var(--warn);
  font-size: var(--fs-xs);
}

.finding-list {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.finding {
  padding: var(--s3);
  border: 1px solid var(--ice-3);
  border-radius: var(--radius-sm);
  background: var(--ice-0);
}

.finding[data-severity="warning"] {
  border-color: var(--warn-line);
  background: var(--warn-wash);
}

.finding h5,
.recipe h5 {
  margin: 7px 0 4px;
  font-size: var(--fs-sm);
}

.finding p,
.recipe p {
  font-size: var(--fs-xs);
  line-height: 1.65;
}

.finding__suggestion,
.finding__rationale {
  margin-top: 5px;
  color: var(--ink-2);
}

.finding__suggestion strong,
.finding__rationale strong {
  margin-right: 6px;
  color: var(--ink-3);
  font-size: 9.5px;
  letter-spacing: 0.06em;
}

.finding__state {
  color: var(--ink-3);
  font-size: 10px;
}

.finding__state[data-state="accepted"] {
  color: var(--pass);
}

.finding__state[data-state="rejected"] {
  color: var(--fail);
}

.assertion {
  margin-top: var(--s3);
  padding: var(--s2);
  border-left: 2px solid var(--glacier);
  background: var(--glacier-wash);
}

.case-proposal {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: var(--s3);
  padding: var(--s2);
  border-left: 2px solid var(--pass);
  background: var(--pass-wash);
}

.case-proposal strong {
  font-size: var(--fs-sm);
}

.case-proposal p,
.case-proposal code {
  font-size: 10.5px;
}

.case-proposal code {
  overflow-wrap: anywhere;
}

.assertion code {
  display: block;
  margin-top: 3px;
  font-size: 10.5px;
  overflow-wrap: anywhere;
}

.finding__foot {
  margin-top: var(--s3);
  padding-top: var(--s2);
  border-top: 1px solid var(--ice-3);
}

.finding__foot code {
  max-width: 60%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ink-3);
  font-size: 9.5px;
}

.text-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 6px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--ink-3);
  font: inherit;
  font-size: var(--fs-xs);
  cursor: pointer;
}

.text-btn:hover {
  border-color: var(--ice-3);
  background: var(--ice-1);
}

.text-btn--primary {
  color: var(--glacier-deep);
}

.text-btn:disabled {
  opacity: 0.5;
  cursor: default;
}

.recipe {
  margin-top: var(--s3);
  padding: var(--s3);
  border: 1px solid var(--glacier-tint);
  border-radius: var(--radius);
  background: var(--ice-0);
}

.recipe__head {
  justify-content: space-between;
}

.recipe__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s3);
  margin-top: var(--s3);
}

.recipe__grid > div {
  min-width: 0;
  padding-left: var(--s2);
  border-left: 1px solid var(--ice-3);
}

.recipe h6 {
  margin-bottom: 5px;
  font-size: var(--fs-xs);
}

.recipe ul {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.recipe li {
  display: flex;
  flex-direction: column;
  gap: 1px;
  font-size: 10.5px;
  color: var(--ink-3);
}

.recipe code {
  color: var(--ink-1);
}

.recipe__notes {
  margin-top: var(--s3);
}

.recipe__actions {
  margin-top: var(--s3);
  padding-top: var(--s3);
  border-top: 1px solid var(--ice-3);
}

.apply-bar {
  display: flex;
  align-items: center;
  gap: var(--s3);
  flex-wrap: wrap;
  margin-top: var(--s3);
  padding: var(--s3);
  border: 1px solid var(--glacier-tint);
  border-radius: var(--radius);
  background: var(--glacier-wash);
}

.apply-bar > div:first-child {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.apply-bar strong {
  font-size: var(--fs-sm);
}

.apply-bar span {
  color: var(--ink-3);
  font-size: 10.5px;
}

.apply-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 7px 11px;
  border: 1px solid var(--glacier);
  border-radius: var(--radius);
  background: var(--glacier);
  color: var(--on-mass);
  font: inherit;
  font-size: var(--fs-xs);
  cursor: pointer;
}

.apply-btn:disabled {
  border-color: var(--ice-4);
  background: var(--ice-2);
  color: var(--ink-3);
  cursor: default;
}

.review-empty {
  margin-top: var(--s3);
  padding: var(--s3);
  border: 1px dashed var(--ice-4);
  border-radius: var(--radius-sm);
  color: var(--ink-3);
  font-size: var(--fs-xs);
}

@media (max-width: 900px) {
  .ai-review__body,
  .recipe__grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .review-list {
    max-height: 190px;
    overflow-y: auto;
  }
}
</style>
