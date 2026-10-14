<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api, saveBlob } from "@/api";
import type {
  CoverageDimension,
  CoverageReport,
  ExportFormatInfo,
  RequirementDoc,
  TestCase,
  TestCaseSuite,
} from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import CaseTable from "@/components/CaseTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorNote from "@/components/ErrorNote.vue";
import FieldHint from "@/components/FieldHint.vue";
import MethodTag from "@/components/MethodTag.vue";
import SectionCard from "@/components/SectionCard.vue";
import StatReadout from "@/components/StatReadout.vue";
import Tip from "@/components/Tip.vue";
import ReviewFindings from "@/components/ReviewFindings.vue";
import WarningList from "@/components/WarningList.vue";
import { confirmAction } from "@/composables/useFeedback";
import { useNoticeStore } from "@/stores/notice";
import {
  FALLBACK_EXPORT_FORMATS,
  engineLabel,
  engineTitle,
  formatDuration,
  formatTime,
  methodLabel,
  percent,
  priorityRank,
} from "@/utils/labels";

interface CoverageRow {
  id: string;
  title: string;
  module: string;
  count: number;
  priority: string;
}

const route = useRoute();
const router = useRouter();
const notice = useNoticeStore();

const suiteId = computed(() => String(route.params.suiteId ?? ""));
const suite = ref<TestCaseSuite | null>(null);
const requirement = ref<RequirementDoc | null>(null);
const requirementMissing = ref(false);
const formats = ref<ExportFormatInfo[]>([]);

/** 导出格式同样收敛成「Excel 直出 + 其余进下拉」，避免一排按钮把卡片头撑宽。 */
const exportFormats = computed(() =>
  formats.value.length ? formats.value : FALLBACK_EXPORT_FORMATS,
);
const primaryFormat = computed(
  () => exportFormats.value.find((item) => item.name === "excel") ?? exportFormats.value[0],
);
const otherFormats = computed(() =>
  exportFormats.value.filter((item) => item.name !== primaryFormat.value?.name),
);
const coverageReport = ref<CoverageReport | null>(null);
const coverageOpen = ref<CoverageDimension | null>(null);
const loading = ref(true);
const error = ref("");
const exporting = ref("");

const priorityRows = computed(() => {
  const data = suite.value;
  if (!data) return [];
  return Object.entries(data.stats.by_priority)
    .sort((a, b) => priorityRank(a[0]) - priorityRank(b[0]))
    .map(([key, count]) => ({ key, count }));
});

const methodRows = computed(() => {
  const data = suite.value;
  if (!data) return [];
  return data.methods.map((method) => {
    const label = methodLabel(method);
    return {
      method,
      label,
      // 后端按「方法标签」计数，不是 by name
      generated: data.stats.by_method[label] ?? 0,
      covered: data.stats.by_covered_method[label] ?? 0,
    };
  });
});

const coverage = computed<CoverageRow[]>(() => {
  const data = suite.value;
  if (!data) return [];
  const items = requirement.value?.items ?? [];
  return items.map((item) => ({
    id: item.id,
    title: item.title,
    module: item.module,
    priority: item.priority,
    count: data.stats.requirement_coverage[item.id] ?? 0,
  }));
});

const uncovered = computed(() => coverage.value.filter((row) => row.count === 0));

const topModules = computed(() => {
  const data = suite.value;
  if (!data) return [];
  const tally = new Map<string, number>();
  data.cases.forEach((item) => {
    const module = item.module || "未归类";
    tally.set(module, (tally.get(module) ?? 0) + 1);
  });
  return Array.from(tally.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([key, count]) => ({ key, count }));
});

function casesOf(id: string): TestCase[] {
  return (suite.value?.cases ?? []).filter((item) => item.requirement_ids.includes(id));
}

/** 追溯矩阵里每行最多直出多少条用例编号，其余折叠为 +N。 */
const COVERAGE_PREVIEW = 8;

function casesPreview(id: string): TestCase[] {
  return casesOf(id).slice(0, COVERAGE_PREVIEW);
}

function casesRest(id: string): TestCase[] {
  return casesOf(id).slice(COVERAGE_PREVIEW);
}

onMounted(() => {
  void load();
});

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  requirementMissing.value = false;
  try {
    const data = await api.suite(suiteId.value);
    suite.value = data;
    try {
      requirement.value = await api.requirement(data.doc_id);
    } catch {
      requirementMissing.value = true;
    }
    try {
      formats.value = await api.exportFormats();
    } catch {
      /* 导出按钮回退到 Excel / JSON */
    }
    try {
      coverageReport.value = await api.suiteCoverage(data.suite_id);
    } catch {
      // 源需求被删掉时算不出覆盖率：这里静默回退到卡片不渲染，
      // 页面顶部已有明确的「需求缺失」提示，不必重复打扰。
      coverageReport.value = null;
    }
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    loading.value = false;
  }
}

async function exportSuite(format: string): Promise<void> {
  if (!suite.value) return;
  exporting.value = format;
  try {
    const file = await api.exportSuite(suite.value.suite_id, format);
    saveBlob(file.blob, file.filename || `用例集.${format}`);
    notice.success("导出完成", file.filename || undefined);
  } catch (err) {
    notice.error("导出失败", (err as Error).message);
  } finally {
    exporting.value = "";
  }
}

async function remove(): Promise<void> {
  if (!suite.value) return;
  const confirmed = await confirmAction({
    title: "删除用例集",
    message: `将删除这份用例集（${suite.value.stats.total} 条）。删除后不可恢复，需求量与文档都会保留。`,
    confirmText: "删除",
    danger: true,
  });
  if (!confirmed) return;
  try {
    await api.deleteSuite(suite.value.suite_id);
    notice.success("已删除用例集");
    await router.push("/suites");
  } catch (err) {
    notice.error("删除失败", (err as Error).message);
  }
}
</script>

<template>
  <div class="stack">
    <ErrorNote
      v-if="error"
      title="用例集没有取到"
      :message="error"
      recovery="可能已被删除；回到用例集列表确认，或检查后端是否已启动。"
      @retry="load"
    />

    <template v-if="suite">
      <SectionCard
        :title="suite.doc_title || '未命名用例集'"
        :sub="`${suite.revision ? `第 ${suite.revision} 版 · ` : ''}${suite.cases.length} 条 · ${suite.methods.map(methodLabel).join(' / ')} · 生成于 ${formatTime(suite.created_at)}`"
        icon="cases"
      >
        <template #actions>
          <el-button size="small" @click="router.push('/suites')">返回列表</el-button>
          <el-button
            v-if="primaryFormat"
            size="small"
            :loading="exporting === primaryFormat.name"
            @click="exportSuite(primaryFormat.name)"
          >
            <AppIcon name="download" :size="14" /> {{ primaryFormat.label }}
          </el-button>
          <el-dropdown v-if="otherFormats.length" trigger="click" @command="exportSuite">
            <el-button size="small">
              更多格式
              <AppIcon name="chevronDown" :size="13" />
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-for="fmt in otherFormats" :key="fmt.name" :command="fmt.name">
                  {{ fmt.label }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button size="small" @click="remove"><AppIcon name="trash" :size="17" /> 删除</el-button>
        </template>

        <div class="grid grid--4">
          <StatReadout label="用例总数" :value="suite.stats.total" tone="glacier" hint="去重排序后的最终条目数" />
          <StatReadout label="去重合并" :value="suite.stats.duplicate_removed" hint="精确指纹 + 跨方法语义合并掉的条数" />
          <StatReadout
            label="需求覆盖"
            :value="coverage.length ? `${coverage.length - uncovered.length}/${coverage.length}` : '—'"
            :tone="uncovered.length ? 'warn' : 'pass'"
            hint="至少被一条用例覆盖的需求数 / 需求总数"
          />
          <StatReadout
            label="生成耗时"
            :value="formatDuration(suite.generation_meta.elapsed_ms)"
            hint="服务端从解析到编号排序的总耗时"
          />
        </div>

        <hr class="rule" />

        <div class="meta">
          <span class="chip chip--ghost mono">{{ suite.suite_id.slice(0, 18) }}</span>
          <span
            class="chip"
            :class="suite.generation_meta.llm_used ? 'chip--glacier' : 'chip--ghost'"
            :title="engineTitle(suite.generation_meta)"
          >
            生成：{{ engineLabel(suite.generation_meta) }}
          </span>
          <span
            class="chip"
            :class="suite.parse_meta.llm_used ? 'chip--glacier' : 'chip--ghost'"
            :title="engineTitle(suite.parse_meta)"
          >
            解析：{{ engineLabel(suite.parse_meta) }}
          </span>
          <button
            type="button"
            class="sourcelink mono"
            :title="`打开「${suite.doc_title || suite.doc_id}」的结构化需求`"
            @click="router.push(`/documents/${suite.doc_id}/requirement`)"
          >
            <AppIcon name="doc" :size="13" />
            {{ suite.doc_title || suite.doc_id.slice(0, 12) }}
          </button>
        </div>

        <WarningList :items="suite.generation_meta.warnings" />

        <ReviewFindings :findings="suite.generation_meta.review_findings" />
      </SectionCard>

      <SectionCard
        v-if="coverageReport"
        title="覆盖率分析"
        sub="相对源需求的字段 / 边界 / 规则三维覆盖与缺口清单"
        icon="target"
      >
        <template #actions>
          <span class="chip" :class="coverageReport.overall_ratio >= 0.8 ? 'chip--pass' : 'chip--warn'">
            综合 {{ Math.round(coverageReport.overall_ratio * 100) }}%
          </span>
        </template>

        <FieldHint>{{ coverageReport.summary }}</FieldHint>

        <div class="grid grid--3 covs">
          <div v-for="dim in coverageReport.dimensions" :key="dim.key" class="cov">
            <p class="cov__head">
              <span class="cov__label">{{ dim.label }}</span>
              <span class="mono cov__ratio">
                {{ dim.total ? `${dim.covered}/${dim.total}` : "—" }}
              </span>
            </p>
            <div class="cov__bar" :data-tone="dim.ratio >= 0.8 ? 'pass' : dim.ratio >= 0.5 ? 'warn' : 'fail'">
              <span class="cov__fill" :style="{ width: `${Math.round((dim.ratio || 0) * 100)}%` }" />
            </div>
            <p class="cov__note">{{ dim.note || `缺口 ${dim.gaps.length} 项` }}</p>
            <el-button v-if="dim.gaps.length" size="small" text @click="coverageOpen = dim">
              查看缺口（{{ dim.gaps.length }}）
            </el-button>
          </div>
        </div>
      </SectionCard>

      <div class="grid grid--2">
        <SectionCard title="方法分布" sub="按生成方法与覆盖方法两口径计数" icon="chart">
          <el-table :data="methodRows" size="small" :border="false">
            <el-table-column label="方法" min-width="130">
              <template #default="{ row }"><MethodTag :method="row.method" /></template>
            </el-table-column>
            <el-table-column label="生成" width="88" align="right">
              <template #default="{ row }"><span class="mono num">{{ row.generated }}</span></template>
            </el-table-column>
            <el-table-column label="覆盖" width="88" align="right">
              <template #default="{ row }">
                <Tip :text="`合并用例按它覆盖到的全部方法重新计数，避免跨方法合并后被少算。`">
                  <span class="mono num">{{ row.covered }}</span>
                </Tip>
              </template>
            </el-table-column>
          </el-table>
          <FieldHint>
            两列口径不同：左边是「这条用例由哪种方法生成」，右边是「这条用例覆盖了哪些方法」。合并后两者会有差异。
          </FieldHint>
        </SectionCard>

        <SectionCard title="分布" sub="优先级与模块 Top 8" icon="layers">
          <div class="dist">
            <div class="dist__col">
              <p class="label">优先级</p>
              <ul class="dist__list">
                <li v-for="row in priorityRows" :key="row.key">
                  <span class="mono">{{ row.key }}</span>
                  <span class="dist__bar"><i :style="{ width: percent(row.count, suite.stats.total) }" /></span>
                  <span class="mono num">{{ row.count }}</span>
                </li>
              </ul>
            </div>
            <div class="dist__col">
              <p class="label">模块</p>
              <ul class="dist__list">
                <li v-for="row in topModules" :key="row.key">
                  <span class="dist__name">{{ row.key }}</span>
                  <span class="dist__bar"><i :style="{ width: percent(row.count, suite.stats.total) }" /></span>
                  <span class="mono num">{{ row.count }}</span>
                </li>
              </ul>
            </div>
          </div>
        </SectionCard>
      </div>

      <SectionCard
        v-if="coverage.length"
        title="需求追溯矩阵"
        :sub="uncovered.length ? `${uncovered.length} 条需求暂无用例覆盖` : '每条需求都被覆盖'"
        icon="target"
      >
        <template #actions>
          <span class="chip" :class="uncovered.length ? 'chip--warn' : 'chip--pass'">
            {{ uncovered.length ? `${uncovered.length} 条缺口` : "无缺口" }}
          </span>
        </template>
        <el-table :data="coverage" size="small" :border="false">
          <el-table-column label="需求" width="96">
            <template #default="{ row }"><span class="mono">{{ row.id }}</span></template>
          </el-table-column>
          <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
          <el-table-column prop="module" label="模块" width="120" show-overflow-tooltip />
          <el-table-column label="用例数" width="96" align="right">
            <template #default="{ row }">
              <span class="mono num" :class="{ 'is-gap': row.count === 0 }">{{ row.count }}</span>
            </template>
          </el-table-column>
          <el-table-column label="覆盖用例" min-width="300">
            <template #default="{ row }">
              <div v-if="row.count" class="ids">
                <span v-for="item in casesPreview(row.id)" :key="item.case_id" class="ids__item mono">
                  {{ item.case_id }}
                </span>
                <Tip
                  v-if="casesRest(row.id).length"
                  :text="`其余 ${casesRest(row.id).length} 条：${casesRest(row.id).map((c) => c.case_id).join('、')}`"
                >
                  <span class="ids__item ids__item--more mono">+{{ casesRest(row.id).length }}</span>
                </Tip>
              </div>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
        </el-table>
      </SectionCard>

      <SectionCard v-else-if="requirementMissing" title="需求追溯矩阵" icon="target" sunk>
        <EmptyState
          icon="doc"
          title="找不到对应的结构化需求"
          reason="这份用例集的源需求可能已被删除，或从未解析。用例明细与统计不受影响，仍可正常导出。"
          action-label="前往文档与需求"
          @action="router.push('/documents')"
        />
      </SectionCard>

      <SectionCard title="用例明细" :sub="`${suite.cases.length} 条`" icon="cases" flush>
        <template #actions>
          <el-button size="small" @click="router.push(`/generate`)">
            <AppIcon name="sparkle" :size="14" /> 再生成一份
          </el-button>
        </template>
        <CaseTable :suite="suite" />
      </SectionCard>

      <el-drawer
        :model-value="Boolean(coverageOpen)"
        size="520px"
        direction="rtl"
        @close="coverageOpen = null"
      >
        <template #header>
          <div class="ghead">
            <AppIcon name="target" :size="18" />
            <span>{{ coverageOpen?.label }}缺口（{{ coverageOpen?.gaps.length }} 项）</span>
          </div>
        </template>
        <div class="gaps">
          <p class="gaps__hint">
            缺口按「需求条目 + 具体目标」定位；补齐后重新生成用例即可，覆盖率会同步刷新。
          </p>
          <ul class="gaps__list">
            <li v-for="(gap, index) in coverageOpen?.gaps ?? []" :key="`${gap.requirement_id}-${index}`">
              <p class="gaps__target">{{ gap.target }}</p>
              <p class="gaps__meta mono">{{ gap.requirement_id }} · {{ gap.requirement_title }}</p>
              <p v-if="gap.detail" class="gaps__detail">{{ gap.detail }}</p>
            </li>
          </ul>
        </div>
      </el-drawer>
    </template>

    <div v-else-if="loading" class="grid grid--2">
      <div v-for="n in 2" :key="n" class="card"><el-skeleton :rows="6" animated class="skel" /></div>
    </div>

    <SectionCard v-else title="用例集不存在" icon="cases">
      <EmptyState
        icon="cases"
        title="这份用例集已经不在了"
        reason="它可能已被删除，或链接里的编号不正确。"
        action-label="返回用例集列表"
        @action="router.push('/suites')"
      />
    </SectionCard>
  </div>
</template>

<style scoped>
.covs {
  margin-top: var(--s3);
}

.cov {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.cov__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--s2);
}

.cov__label {
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--ink-2);
}

.cov__ratio {
  font-size: var(--fs-xs);
  color: var(--ink-1);
}

.cov__bar {
  position: relative;
  height: 6px;
  border-radius: 999px;
  background: var(--ice-2);
  overflow: hidden;
}

.cov__fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--glacier);
}

.cov__bar[data-tone="warn"] .cov__fill {
  background: var(--warn);
}

.cov__bar[data-tone="fail"] .cov__fill {
  background: var(--fail);
}

.cov__note {
  font-size: var(--fs-2xs);
  line-height: 1.6;
  color: var(--ink-3);
}

.ghead {
  display: flex;
  align-items: center;
  gap: var(--s2);
  color: var(--ink-1);
}

.gaps {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}

.gaps__hint {
  font-size: var(--fs-2xs);
  line-height: 1.7;
  color: var(--ink-3);
}

.gaps__list {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.gaps__target {
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--ink-1);
}

.gaps__meta {
  font-size: 10.5px;
  color: var(--ink-3);
}

.gaps__detail {
  font-size: var(--fs-2xs);
  color: var(--ink-2);
}

.meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: var(--s3);
}

.sourcelink {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 9px;
  border: 1px solid var(--ice-3);
  border-radius: 999px;
  background: var(--ice-1);
  font-size: var(--fs-xs);
  color: var(--glacier-deep);
  cursor: pointer;
}

.sourcelink:hover {
  border-color: var(--glacier);
}

.dist {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s4);
}

@media (max-width: 760px) {
  .dist {
    grid-template-columns: minmax(0, 1fr);
  }
}

.dist__col {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.dist__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.dist__list li {
  display: grid;
  grid-template-columns: 76px 1fr 34px;
  align-items: center;
  gap: var(--s2);
  font-size: var(--fs-xs);
  color: var(--ink-2);
}

.dist__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dist__bar {
  height: 5px;
  border-radius: 3px;
  background: var(--ice-2);
  overflow: hidden;
}

.dist__bar i {
  display: block;
  height: 100%;
  border-radius: 3px;
  background: var(--glacier);
  transition: width var(--dur-slow) var(--ease);
}

.dist__list li:last-child .num,
.dist__list li .num {
  text-align: right;
  color: var(--ink-1);
}

.is-gap {
  color: var(--warn);
}

.ids {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 6px;
  font-size: 10.5px;
  color: var(--ink-2);
}

.ids__item {
  padding: 1px 6px;
  border: 1px solid var(--ice-3);
  border-radius: 4px;
  background: var(--ice-1);
  white-space: nowrap;
}

.ids__item--more {
  color: var(--glacier-deep);
  border-color: var(--glacier-tint);
  background: var(--glacier-wash);
  cursor: help;
}

.skel {
  padding: var(--s5);
}
</style>


