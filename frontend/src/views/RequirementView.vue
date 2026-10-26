<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import type { FieldConstraint, RequirementDoc, TestCaseSuiteSummary } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorNote from "@/components/ErrorNote.vue";
import FieldHint from "@/components/FieldHint.vue";
import MethodTag from "@/components/MethodTag.vue";
import PriorityMark from "@/components/PriorityMark.vue";
import SectionCard from "@/components/SectionCard.vue";
import StatReadout from "@/components/StatReadout.vue";
import Tip from "@/components/Tip.vue";
import WarningList from "@/components/WarningList.vue";
import { confirmAction } from "@/composables/useFeedback";
import { useHealthStore } from "@/stores/health";
import { useNoticeStore } from "@/stores/notice";
import {
  DEFAULT_METHODS,
  METHOD_NOTES,
  claimStatusLabel,
  dataTypeLabel,
  engineLabel,
  engineTitle,
  formatDuration,
  formatRelative,
  methodOrderIndex,
  requirementTypeLabel,
} from "@/utils/labels";

const route = useRoute();
const router = useRouter();
const health = useHealthStore();
const notice = useNoticeStore();

const docId = computed(() => String(route.params.docId ?? ""));
const requirement = ref<RequirementDoc | null>(null);
const loading = ref(true);
const error = ref("");

const methods = ref<string[]>([...DEFAULT_METHODS]);
const useLlmInDesign = ref(false);
const generating = ref(false);
const expanded = ref<string[]>([]);

// 反向追溯：这条需求一共生成过哪些用例集。
// 需求页只放一个「生成」按钮，就等于「只出不进」——生成过的结果再也回不到这里。
const suites = ref<TestCaseSuiteSummary[]>([]);
const suitesLoading = ref(false);

/** 方法清单以服务端能力清单为准（store 已缓存 /health）。 */
const methodList = computed(() =>
  [...health.methods]
    .sort((left, right) => methodOrderIndex(left.name) - methodOrderIndex(right.name))
    .map((item) => ({ ...item, note: METHOD_NOTES[item.name] ?? "" })),
);

const fieldsOf = computed<FieldConstraint[]>(() =>
  (requirement.value?.items ?? []).flatMap((item) => item.fields),
);

const counts = computed(() => ({
  items: requirement.value?.items.length ?? 0,
  fields: fieldsOf.value.length,
  rules: (requirement.value?.items ?? []).reduce((sum, item) => sum + item.business_rules.length, 0),
  exceptions: (requirement.value?.items ?? []).reduce((sum, item) => sum + item.exceptions.length, 0),
}));

const trustCounts = computed(() => {
  const tally = { verified: 0, inferred: 0, rejected: 0 };
  for (const item of requirement.value?.items ?? []) {
    tally[item.claim_status] += 1;
    for (const field of item.fields) tally[field.claim_status] += 1;
  }
  return tally;
});

const canGenerate = computed(() => generating.value === false && methods.value.length > 0);

onMounted(() => {
  void load();
});

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    requirement.value = await api.requirement(docId.value);
    expanded.value = requirement.value.items.slice(0, 1).map((item) => item.id);
    void loadSuites();
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    loading.value = false;
  }
}

/** 列出这条需求已生成的用例集；取不到就当成「还没有」，不阻塞整页。 */
async function loadSuites(): Promise<void> {
  suitesLoading.value = true;
  try {
    suites.value = await api.suites(20, docId.value);
  } catch {
    suites.value = [];
  } finally {
    suitesLoading.value = false;
  }
}

function toggleMethod(name: string): void {
  const index = methods.value.indexOf(name);
  if (index === -1) methods.value.push(name);
  else methods.value.splice(index, 1);
}

function toggleItem(id: string): void {
  const index = expanded.value.indexOf(id);
  if (index === -1) expanded.value.push(id);
  else expanded.value.splice(index, 1);
}

function constraintText(field: FieldConstraint): string {
  const parts: string[] = [];
  if (field.enum_values.length) parts.push(field.enum_values.join(" / "));
  else {
    if (field.min_value !== null || field.max_value !== null) {
      const min = field.min_value ?? "";
      const max = field.max_value ?? "";
      parts.push(field.min_value === null ? `≤ ${max}` : field.max_value === null ? `≥ ${min}` : `${min}–${max}`);
    }
    if (field.min_length !== null || field.max_length !== null) {
      const min = field.min_length ?? "";
      const max = field.max_length ?? "";
      parts.push(field.min_length === null ? `≤${max} 位` : field.max_length === null ? `≥${min} 位` : `${min}–${max} 位`);
    }
  }
  if (field.pattern) parts.push(`/${field.pattern}/`);
  if (field.unit) parts.push(field.unit);
  return parts.length ? parts.join(" · ") : "—";
}

async function generate(): Promise<void> {
  if (!canGenerate.value || !requirement.value) return;
  if (useLlmInDesign.value && health.llmReady) {
    const confirmed = await confirmAction({
      title: "确认在生成阶段使用大模型",
      message:
        "生成阶段会让大模型参与用例设计与去重合并，覆盖更自然但耗时更长。失败时自动回退规则引擎并在结果标注。",
      confirmText: "开始生成",
    });
    if (!confirmed) return;
  }
  generating.value = true;
  try {
    const suite = await api.generateFromRequirement(docId.value, methods.value, useLlmInDesign.value);
    notice.success("用例集已生成", `共 ${suite.stats.total} 条`);
    await router.push(`/suites/${suite.suite_id}`);
  } catch (err) {
    notice.error("生成失败", (err as Error).message);
  } finally {
    generating.value = false;
  }
}
</script>

<template>
  <div class="stack">
    <ErrorNote
      v-if="error"
      title="结构化需求没有取到"
      :message="error"
      recovery="回到「文档与需求」重新解析这份文档，或确认后端已启动。"
      @retry="load"
    />

    <template v-if="requirement">
      <SectionCard
        :title="requirement.title"
        :sub="`${requirement.source_file} · 解析于 ${formatRelative(requirement.created_at)}`"
        icon="doc"
      >
        <template #actions>
          <el-button size="small" @click="router.push('/documents')">返回文档库</el-button>
          <el-button size="small" type="primary" :loading="generating" :disabled="!canGenerate" @click="generate">
            <AppIcon v-if="!generating" name="sparkle" :size="14" />
            生成用例集
          </el-button>
        </template>

        <div class="grid grid--4">
          <StatReadout label="需求条目" :value="counts.items" tone="glacier" hint="解析出的结构化需求条目数" />
          <StatReadout label="字段" :value="counts.fields" hint="所有需求的字段约束合计" />
          <StatReadout label="业务规则" :value="counts.rules" hint="抽取到的业务规则条数" />
          <StatReadout label="异常分支" :value="counts.exceptions" hint="抽取到的异常与备选流程条数" />
        </div>

        <hr class="rule" />

        <div class="meta">
          <span class="chip" :class="requirement.parse_meta.llm_used ? 'chip--glacier' : 'chip--ghost'">
            解析：{{ requirement.parse_meta.llm_used ? "大模型" : "规则引擎" }}
          </span>
          <span class="chip chip--ghost mono">{{ requirement.parse_meta.provider }} · {{ requirement.parse_meta.model }}</span>
          <span class="chip chip--ghost mono">{{ formatDuration(requirement.parse_meta.elapsed_ms) }}</span>
          <span v-if="requirement.parse_meta.attempts > 1" class="chip chip--ghost mono">
            尝试 {{ requirement.parse_meta.attempts }} 次
          </span>
          <span v-if="requirement.parse_meta.prompt_id" class="chip chip--ghost mono">
            {{ requirement.parse_meta.prompt_id }}@{{ requirement.parse_meta.prompt_version }}
          </span>
          <span class="chip chip--pass">原文已核验 {{ trustCounts.verified }}</span>
          <span v-if="trustCounts.inferred" class="chip chip--warn">推断待复核 {{ trustCounts.inferred }}</span>
          <span v-if="trustCounts.rejected" class="chip chip--fail">已拒绝 {{ trustCounts.rejected }}</span>
          <Tip
            v-if="requirement.parse_meta.fallback_used"
            :text="`降级原因：${requirement.parse_meta.fallback_reason || '未说明'}`"
          >
            <span class="chip chip--warn">已降级为规则引擎</span>
          </Tip>
        </div>

        <WarningList :items="requirement.parse_meta.warnings" />

        <p v-if="requirement.summary" class="summary">{{ requirement.summary }}</p>
      </SectionCard>

      <SectionCard title="生成设置" sub="选择设计方法，再生成这条需求对应的用例集" icon="sliders">
        <div class="methods">
          <template v-for="item in methodList" :key="item.name">
            <button
              v-if="item.implemented"
              type="button"
              class="method"
              :class="{ 'method--on': methods.includes(item.name) }"
              :aria-pressed="methods.includes(item.name)"
              :title="item.note"
              @click="toggleMethod(item.name)"
            >
              <span class="method__box" aria-hidden="true">
                <AppIcon v-if="methods.includes(item.name)" name="check" :size="12" />
              </span>
              {{ item.label }}
            </button>
            <Tip v-else :key="item.name" :text="`${item.label}尚未实现：当前调用会返回 501。`">
              <span class="method method--off">{{ item.label }} · 未实现</span>
            </Tip>
          </template>
        </div>

        <div class="row row--wrap">
          <label class="switch">
            <el-switch v-model="useLlmInDesign" />
            <span>生成阶段使用大模型增强</span>
          </label>
          <FieldHint :tone="health.llmReady ? 'muted' : 'warn'">
            {{
              health.llmReady
                ? "关闭时全程走规则引擎，结果完全确定、可离线复现。"
                : "当前未配置大模型，此开关不生效，将全程走规则引擎。"
            }}
          </FieldHint>
        </div>
      </SectionCard>

      <SectionCard
        title="已生成的用例集"
        :sub="suites.length ? `这条需求累计生成 ${suites.length} 份用例集` : '这条需求的每一次生成都会记在这里'"
        icon="cases"
        flush
      >
        <template #actions>
          <el-button size="small" text :loading="suitesLoading" @click="loadSuites">
            <AppIcon name="refresh" :size="14" /> 刷新
          </el-button>
        </template>
        <el-table v-if="suites.length" :data="suites" size="small" :border="false">
          <el-table-column label="用例集" min-width="182" show-overflow-tooltip>
            <template #default="{ row }">
              <button type="button" class="suiteLink" @click="router.push(`/suites/${row.suite_id}`)">
                {{ row.doc_title || "未命名用例集" }}
              </button>
              <span v-if="row.revision" class="rev mono">第 {{ row.revision }} 版</span>
              <p class="suiteSub mono">{{ row.suite_id.slice(0, 18) }}</p>
            </template>
          </el-table-column>
          <el-table-column label="设计方法" min-width="168">
            <template #default="{ row }">
              <span class="suiteTags">
                <MethodTag v-for="method in row.methods" :key="method" :method="method" />
              </span>
            </template>
          </el-table-column>
          <el-table-column label="用例" width="86" align="right">
            <template #default="{ row }"><span class="mono num">{{ row.stats.total }}</span></template>
          </el-table-column>
          <el-table-column label="生成引擎" width="150">
            <template #default="{ row }">
              <span
                class="chip"
                :class="row.generation_meta.llm_used ? 'chip--glacier' : 'chip--ghost'"
                :title="engineTitle(row.generation_meta)"
              >
                {{ engineLabel(row.generation_meta) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="生成时间" width="112">
            <template #default="{ row }">
              <span class="muted">{{ formatRelative(row.created_at) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" align="right">
            <template #default="{ row }">
              <el-button size="small" text @click="router.push(`/suites/${row.suite_id}`)">查看</el-button>
            </template>
          </el-table-column>
        </el-table>
        <EmptyState
          v-else
          icon="cases"
          title="这条需求还没有生成过用例集"
          reason="在上方「生成设置」里选好设计方法，点「生成用例集」即可。生成记录会出现在这里，随时可以回看、导出或对比。"
        />
      </SectionCard>

      <SectionCard :title="`需求清单`" :sub="`${counts.items} 条`" icon="cases">
        <ul class="reqs">
          <li v-for="item in requirement.items" :key="item.id" class="req" :data-open="expanded.includes(item.id)">
            <button type="button" class="req__head" :aria-expanded="expanded.includes(item.id)" @click="toggleItem(item.id)">
              <AppIcon name="chevronRight" :size="15" class="req__caret" />
              <span class="req__id mono">{{ item.id }}</span>
              <span class="req__title">{{ item.title }}</span>
              <span class="chip chip--ghost">{{ item.module }}</span>
              <span class="chip chip--ghost">{{ requirementTypeLabel(item.requirement_type) }}</span>
              <PriorityMark :priority="item.priority" />
              <span
                class="chip"
                :class="item.claim_status === 'verified' ? 'chip--pass' : item.claim_status === 'inferred' ? 'chip--warn' : 'chip--fail'"
              >
                {{ claimStatusLabel(item.claim_status) }}
              </span>
            </button>

            <div v-if="expanded.includes(item.id)" class="req__body">
              <p v-if="item.description" class="req__desc">{{ item.description }}</p>

              <div v-if="item.fields.length" class="block">
                <p class="label">字段与约束</p>
                <el-table :data="item.fields" size="small" :border="false">
                  <el-table-column label="字段" min-width="150">
                    <template #default="{ row }">
                      <span class="mono">{{ row.name }}</span>
                      <span class="muted"> · {{ row.label }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="类型" width="92">
                    <template #default="{ row }">{{ dataTypeLabel(row.data_type) }}</template>
                  </el-table-column>
                  <el-table-column label="必填" width="72">
                    <template #default="{ row }">{{ row.required ? "是" : "否" }}</template>
                  </el-table-column>
                  <el-table-column label="约束" min-width="200">
                    <template #default="{ row }"><span class="mono">{{ constraintText(row) }}</span></template>
                  </el-table-column>
                  <el-table-column prop="description" label="说明" min-width="180" />
                  <el-table-column label="可信状态" width="132">
                    <template #default="{ row }">
                      <span
                        class="chip"
                        :class="row.claim_status === 'verified' ? 'chip--pass' : row.claim_status === 'inferred' ? 'chip--warn' : 'chip--fail'"
                        :title="row.uncertainty_reason"
                      >
                        {{ claimStatusLabel(row.claim_status) }}
                      </span>
                    </template>
                  </el-table-column>
                </el-table>
              </div>

              <div class="split">
                <div v-if="item.business_rules.length" class="block">
                  <p class="label">业务规则</p>
                  <ul class="bullets"><li v-for="rule in item.business_rules" :key="rule">{{ rule }}</li></ul>
                </div>
                <div v-if="item.preconditions.length" class="block">
                  <p class="label">前置条件</p>
                  <ul class="bullets"><li v-for="pre in item.preconditions" :key="pre">{{ pre }}</li></ul>
                </div>
              </div>

              <div class="split">
                <div v-if="item.main_flow.length" class="block">
                  <p class="label">主流程</p>
                  <ol class="steps"><li v-for="(step, i) in item.main_flow" :key="i">{{ step }}</li></ol>
                </div>
                <div v-if="item.alternative_flows.length" class="block">
                  <p class="label">备选流程</p>
                  <ol class="steps"><li v-for="(step, i) in item.alternative_flows" :key="i">{{ step }}</li></ol>
                </div>
              </div>

              <div class="split">
                <div v-if="item.exceptions.length" class="block">
                  <p class="label">异常</p>
                  <ul class="bullets bullets--fail"><li v-for="exc in item.exceptions" :key="exc">{{ exc }}</li></ul>
                </div>
                <div v-if="item.acceptance_criteria.length" class="block">
                  <p class="label">验收标准</p>
                  <ul class="bullets bullets--pass"><li v-for="ac in item.acceptance_criteria" :key="ac">{{ ac }}</li></ul>
                </div>
              </div>

              <Tip v-if="item.source_ref" :text="item.source_ref" :marked="false">
                <span class="req__ref mono">来源：{{ item.source_ref.slice(0, 60) }}</span>
              </Tip>
              <div v-if="item.evidence_quotes.length || item.uncertainty_reason" class="evidence">
                <p class="label">原文证据与不确定性</p>
                <ul v-if="item.evidence_quotes.length" class="bullets">
                  <li v-for="quote in item.evidence_quotes" :key="quote">“{{ quote }}”</li>
                </ul>
                <p v-if="item.uncertainty_reason" class="evidence__uncertain">{{ item.uncertainty_reason }}</p>
              </div>
            </div>
          </li>
        </ul>
      </SectionCard>
    </template>

    <div v-else-if="loading" class="grid grid--3">
      <div v-for="n in 3" :key="n" class="card"><el-skeleton :rows="5" animated class="skel" /></div>
    </div>

    <SectionCard v-else title="没有结构化需求" icon="doc">
      <EmptyState
        icon="doc"
        title="这份文档还没有解析结果"
        reason="结构化需求由「文档与需求」页发起解析后生成；没有解析结果就没有可生成用例的输入。"
        action-label="前往文档与需求"
        @action="router.push('/documents')"
      />
    </SectionCard>
  </div>
</template>

<style scoped>
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: var(--s3);
}

.summary {
  margin-top: var(--s3);
  font-size: var(--fs-sm);
  line-height: 1.75;
  color: var(--ink-2);
  max-width: 78ch;
}

.methods {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2);
  margin-bottom: var(--s4);
}

.method {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius-pill);
  background: var(--ice-0);
  color: var(--ink-2);
  font: inherit;
  font-size: var(--fs-sm);
  cursor: pointer;
  transition: border-color var(--dur-fast) var(--ease), background-color var(--dur-fast) var(--ease);
}

.method:hover {
  border-color: var(--glacier-tint);
  background: var(--glacier-wash);
}

.method--on {
  border-color: var(--glacier);
  background: var(--glacier-wash);
  color: var(--glacier-deep);
}

.method--off {
  opacity: 0.7;
  cursor: not-allowed;
  border-style: dashed;
}

.method__box {
  display: grid;
  place-items: center;
  width: 15px;
  height: 15px;
  border: 1px solid var(--ice-5);
  border-radius: 4px;
  color: var(--ice-0);
  background: var(--ice-0);
}

.method--on .method__box {
  background: var(--glacier);
  border-color: var(--glacier);
}

.switch {
  display: inline-flex;
  align-items: center;
  gap: var(--s2);
  font-size: var(--fs-sm);
  color: var(--ink-2);
}

.reqs {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.req {
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  overflow: hidden;
  transition: border-color var(--dur-fast) var(--ease);
}

.req[data-open="true"] {
  border-color: var(--glacier-tint);
}

.req__head {
  display: flex;
  align-items: center;
  gap: var(--s2);
  width: 100%;
  padding: 10px var(--s3);
  border: none;
  background: var(--ice-0);
  color: var(--ink-1);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease);
}

.req__head:hover {
  background: var(--glacier-wash);
}

.req__caret {
  flex: none;
  color: var(--ink-3);
  transition: transform var(--dur) var(--ease);
}

.req[data-open="true"] .req__caret {
  transform: rotate(90deg);
  color: var(--glacier-deep);
}

.req__id {
  font-size: var(--fs-xs);
  color: var(--glacier-deep);
}

.req__title {
  font-size: var(--fs-sm);
  font-weight: 500;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.req__body {
  padding: var(--s3) var(--s4) var(--s4);
  border-top: 1px solid var(--ice-3);
  background: var(--ice-1);
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}

.req__desc {
  font-size: var(--fs-sm);
  line-height: 1.75;
  color: var(--ink-2);
  max-width: 80ch;
}

.block {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.split {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s4);
}

@media (max-width: 900px) {
  .split {
    grid-template-columns: minmax(0, 1fr);
  }
}

.bullets,
.steps {
  margin: 0;
  padding-left: 1.2em;
  font-size: var(--fs-sm);
  line-height: 1.7;
  color: var(--ink-2);
}

.bullets--fail li::marker {
  color: var(--fail);
}

.bullets--pass li::marker {
  color: var(--pass);
}

.steps li::marker {
  color: var(--glacier);
  font-family: var(--font-data);
  font-size: var(--fs-xs);
}

.req__ref {
  font-size: 10.5px;
  color: var(--ink-3);
  word-break: break-all;
}

.evidence {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--s3);
  border-left: 2px solid var(--glacier);
  background: var(--glacier-wash);
}

.evidence__uncertain {
  font-size: var(--fs-xs);
  line-height: 1.6;
  color: var(--warn);
}

.suiteLink {
  border: none;
  background: transparent;
  padding: 0;
  font: inherit;
  font-size: var(--fs-sm);
  font-weight: 500;
  color: var(--glacier-deep);
  cursor: pointer;
}

.suiteLink:hover {
  text-decoration: underline;
}

.suiteSub {
  font-size: 10.5px;
  color: var(--ink-3);
}

.rev {
  display: inline-block;
  margin: 0 0 2px 6px;
  padding: 1px 6px;
  border: 1px solid var(--ice-3);
  border-radius: 999px;
  font-size: var(--fs-2xs);
  color: var(--ink-2);
}

.suiteTags {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
}

.skel {
  padding: var(--s5);
}
</style>

