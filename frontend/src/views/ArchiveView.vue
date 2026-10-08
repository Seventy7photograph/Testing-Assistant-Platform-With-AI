<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { api, saveBlob } from "@/api";
import type { ReportDetail, ReportSummary, ReportStatus, TrendPoint } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorNote from "@/components/ErrorNote.vue";
import FieldHint from "@/components/FieldHint.vue";
import SectionCard from "@/components/SectionCard.vue";
import StatReadout from "@/components/StatReadout.vue";
import TrendChart from "@/components/TrendChart.vue";
import { confirmAction } from "@/composables/useFeedback";
import { useNoticeStore } from "@/stores/notice";
import {
  VERDICT_LABELS,
  formatPercent,
  formatRelative,
  verdictTone,
} from "@/utils/labels";

const router = useRouter();
const notice = useNoticeStore();

const PAGE_SIZE = 10;

const rows = ref<ReportSummary[]>([]);
const total = ref(0);
const page = ref(1);
const keyword = ref("");
const verdictFilter = ref("");
const loading = ref(true);
const error = ref("");

const trends = ref<TrendPoint[]>([]);
const status = ref<ReportStatus | null>(null);

const selected = ref<string[]>([]);
const batchDeleting = ref(false);
const compareOpen = ref(false);
const comparing = ref(false);
const compareLeft = ref<ReportDetail | null>(null);
const compareRight = ref<ReportDetail | null>(null);

const passLine = computed(() => status.value?.thresholds.pass_line ?? 0.95);
const latest = computed(() => trends.value[trends.value.length - 1] ?? null);
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)));

const verdictOptions = Object.entries(VERDICT_LABELS).map(([value, label]) => ({ value, label }));

const allPageSelected = computed(
  () => rows.value.length > 0 && rows.value.every((row) => selected.value.includes(row.id)),
);
const somePageSelected = computed(
  () => !allPageSelected.value && rows.value.some((row) => selected.value.includes(row.id)),
);

const compareRows = computed<CompareItem[]>(() => {
  const left = compareLeft.value?.metrics;
  const right = compareRight.value?.metrics;
  if (!left || !right) return [];
  const rate = (value: number) => formatPercent(value);
  const count = (value: number) => String(value);
  return [
    { label: "用例总数", left: count(left.total), right: count(right.total), delta: right.total - left.total, kind: "count" as const },
    { label: "通过率", left: rate(left.pass_rate), right: rate(right.pass_rate), delta: right.pass_rate - left.pass_rate, kind: "rate" as const },
    { label: "失败数", left: count(left.failed), right: count(right.failed), delta: right.failed - left.failed, kind: "count" as const, invert: true },
    { label: "阻塞数", left: count(left.blocked), right: count(right.blocked), delta: right.blocked - left.blocked, kind: "count" as const, invert: true },
    { label: "执行率", left: rate(left.execution_rate), right: rate(right.execution_rate), delta: right.execution_rate - left.execution_rate, kind: "rate" as const },
    { label: "有效通过率", left: rate(left.effective_pass_rate), right: rate(right.effective_pass_rate), delta: right.effective_pass_rate - left.effective_pass_rate, kind: "rate" as const },
    { label: "未关闭缺陷", left: count(left.defects_open), right: count(right.defects_open), delta: right.defects_open - left.defects_open, kind: "count" as const, invert: true },
    { label: "未关闭 P0", left: count(left.open_p0), right: count(right.open_p0), delta: right.open_p0 - left.open_p0, kind: "count" as const, invert: true },
    { label: "未关闭 P1", left: count(left.open_p1), right: count(right.open_p1), delta: right.open_p1 - left.open_p1, kind: "count" as const, invert: true },
  ];
});

/** 参与对比的某一轮缺少可解析指标时，对比表会是一张空壳——必须先说清楚原因。 */
const compareBlockedNames = computed(() => {
  const names: string[] = [];
  if (compareLeft.value && !compareLeft.value.metrics) {
    names.push(compareLeft.value.title || compareLeft.value.id);
  }
  if (compareRight.value && !compareRight.value.metrics) {
    names.push(compareRight.value.title || compareRight.value.id);
  }
  return names;
});

interface CompareItem {
  label: string;
  left: string;
  right: string;
  delta: number;
  kind: "count" | "rate";
  invert?: boolean;
}

function deltaTone(item: CompareItem): string {
  if (Math.abs(item.delta) < (item.kind === "rate" ? 0.0005 : 0.5)) return "flat";
  const positive = item.delta > 0;
  const good = item.invert ? !positive : positive;
  return good ? "up" : "down";
}

function deltaText(item: CompareItem): string {
  if (Math.abs(item.delta) < (item.kind === "rate" ? 0.0005 : 0.5)) return "持平";
  const sign = item.delta > 0 ? "+" : "−";
  const value = Math.abs(item.delta);
  return item.kind === "rate" ? `${sign}${(value * 100).toFixed(1)}pt` : `${sign}${value}`;
}

onMounted(() => {
  void refresh();
});

async function refresh(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const [list, trendPoints, reportStatus] = await Promise.all([
      api.reports({
        limit: PAGE_SIZE,
        offset: (page.value - 1) * PAGE_SIZE,
        q: keyword.value.trim() || undefined,
        verdict: verdictFilter.value || undefined,
      }),
      api.trends(12),
      api.reportStatus(),
    ]);
    rows.value = list.items;
    total.value = list.total;
    trends.value = trendPoints;
    status.value = reportStatus;
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    loading.value = false;
  }
}

function search(): void {
  page.value = 1;
  void refresh();
}

function goPage(next: number): void {
  page.value = Math.min(Math.max(1, next), pageCount.value);
  void refresh();
}

function toggleSelect(row: ReportSummary): void {
  const index = selected.value.indexOf(row.id);
  if (index !== -1) selected.value.splice(index, 1);
  else selected.value.push(row.id);
}

function togglePageAll(value: boolean): void {
  const pageIds = rows.value.map((row) => row.id);
  if (value) {
    for (const id of pageIds) if (!selected.value.includes(id)) selected.value.push(id);
  } else {
    selected.value = selected.value.filter((id) => !pageIds.includes(id));
  }
}

function clearSelection(): void {
  selected.value = [];
}

async function removeSelected(): Promise<void> {
  const ids = [...selected.value];
  if (!ids.length) return;
  const confirmed = await confirmAction({
    title: `批量删除 ${ids.length} 份报告`,
    message: `将删除这 ${ids.length} 份报告（含正文、指标快照与原始输入）。删除后不可恢复。`,
    confirmText: `删除 ${ids.length} 份`,
    danger: true,
  });
  if (!confirmed) return;
  batchDeleting.value = true;
  try {
    const result = await api.batchDeleteReports(ids);
    if (result.missing.length) {
      notice.info(
        `已删除 ${result.deleted} 份报告`,
        `${result.missing.length} 份在服务端已不存在，已自动跳过。`,
      );
    } else {
      notice.success(`已删除 ${result.deleted} 份报告`);
    }
    clearSelection();
    if (rows.value.length === result.deleted && page.value > 1) page.value -= 1;
    await refresh();
  } catch (err) {
    notice.error("批量删除失败", (err as Error).message);
  } finally {
    batchDeleting.value = false;
  }
}

async function openCompare(): Promise<void> {
  if (selected.value.length < 2) return;
  comparing.value = true;
  compareLeft.value = null;
  compareRight.value = null;
  compareOpen.value = true;
  try {
    const [left, right] = await Promise.all([
      api.report(selected.value[0]),
      api.report(selected.value[1]),
    ]);
    compareLeft.value = left;
    compareRight.value = right;
  } catch (err) {
    notice.error("对比数据没有取到", (err as Error).message);
  } finally {
    comparing.value = false;
  }
}

async function download(row: ReportSummary, format: string): Promise<void> {
  try {
    const file = await api.exportReport(row.id, format);
    saveBlob(file.blob, file.filename || `测试报告.${format}`);
    notice.success("导出完成", file.filename || undefined);
  } catch (err) {
    notice.error("导出失败", (err as Error).message);
  }
}

async function remove(row: ReportSummary): Promise<void> {
  const confirmed = await confirmAction({
    title: "删除报告",
    message: `将删除「${row.title || row.id}」这份报告（含正文、指标快照与原始输入）。删除后不可恢复。`,
    confirmText: "删除",
    danger: true,
  });
  if (!confirmed) return;
  try {
    await api.deleteReport(row.id);
    notice.success("已删除报告");
    selected.value = selected.value.filter((id) => id !== row.id);
    if (rows.value.length === 1 && page.value > 1) page.value -= 1;
    await refresh();
  } catch (err) {
    notice.error("删除失败", (err as Error).message);
  }
}
</script>

<template>
  <div class="stack">
    <ErrorNote
      v-if="error"
      title="报告存档没有取到"
      :message="error"
      recovery="确认后端已启动（python run.py），然后重试。"
      @retry="refresh"
    />

    <SectionCard title="通过率趋势" :sub="`最近 ${trends.length} 轮 · 判读线 ${formatPercent(passLine)}`" icon="chart">
      <template #actions>
        <div class="latest" v-if="latest">
          <span class="latest__k">最新一轮</span>
          <span class="latest__v mono">{{ formatPercent(latest.pass_rate) }}</span>
          <span class="chip" :class="`chip--${verdictTone(latest.verdict) === 'warn' ? 'warn' : verdictTone(latest.verdict)}`">
            {{ latest.verdict_label }}
          </span>
        </div>
      </template>
      <TrendChart v-if="trends.length >= 2" :points="trends" :pass-line="passLine" />
      <EmptyState
        v-else
        icon="chart"
        title="至少需要两轮报告才能画出趋势"
        reason="趋势曲线比较的是同一平台上多轮执行之间的通过率变化；先在报告工作台生成并归档两份报告。"
        action-label="去生成报告"
        @action="router.push('/report')"
      />
      <FieldHint v-if="trends.length >= 2">
        曲线只取最近若干轮；判读线跟随你配置的阈值，点悬停可看该轮的用例数与判定。
      </FieldHint>
    </SectionCard>

    <section class="strip">
      <div class="strip__stats">
        <StatReadout label="已归档报告" :value="total" hint="符合当前筛选条件的报告总数" tone="glacier" />
        <StatReadout
          v-if="latest"
          label="最新通过率"
          :value="formatPercent(latest.pass_rate)"
          :tone="latest.pass_rate >= passLine ? 'pass' : 'warn'"
          hint="最近一轮的通过率"
        />
        <StatReadout
          v-if="status"
          label="判定阈值·失败率"
          :value="formatPercent(status.thresholds.fail_rate)"
          hint="失败率超过该值即判「不建议发版」"
        />
      </div>

      <div class="strip__tools">
        <div class="search">
          <AppIcon name="search" :size="15" />
          <input v-model="keyword" type="search" placeholder="按标题 / 版本搜索" aria-label="搜索报告" @keyup.enter="search" />
        </div>
        <el-select v-model="verdictFilter" placeholder="全部判定" clearable style="width: 148px" @change="search">
          <el-option v-for="item in verdictOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-button @click="search"><AppIcon name="refresh" :size="14" /> 查询</el-button>
        <template v-if="selected.length">
          <span class="sel mono">已选 {{ selected.length }}</span>
          <el-button text @click="clearSelection">取消选择</el-button>
          <el-button
            type="danger"
            plain
            :loading="batchDeleting"
            title="删除所有勾选的报告（含正文、指标快照与原始输入），不可恢复"
            @click="removeSelected"
          >
            <AppIcon name="trash" :size="16" /> 批量删除
          </el-button>
        </template>
        <el-button
          type="primary"
          plain
          :disabled="selected.length < 2"
          :title="
            selected.length < 2
              ? '至少勾选两份报告才能对比'
              : '取勾选顺序里的前两份进行对比'
          "
          @click="openCompare"
        >
          对比两轮
          <span v-if="selected.length === 2" class="mono">（2/2）</span>
          <span v-else-if="selected.length > 2" class="mono">（取前 2 轮）</span>
        </el-button>
      </div>
    </section>

    <SectionCard v-if="rows.length || loading" title="报告列表" :sub="`第 ${page} / ${pageCount} 页`" icon="archive" flush>
      <el-table v-loading="loading" :data="rows" size="small" row-key="id">
        <el-table-column width="44">
          <template #header>
            <el-checkbox
              :model-value="allPageSelected"
              :indeterminate="somePageSelected"
              :disabled="!rows.length"
              aria-label="选择本页全部报告"
              @change="(value: boolean) => togglePageAll(value)"
            />
          </template>
          <template #default="{ row }">
            <el-checkbox
              :model-value="selected.includes(row.id)"
              :aria-label="`选择 ${row.title || row.id}`"
              @change="toggleSelect(row)"
            />
          </template>
        </el-table-column>
        <el-table-column label="报告" min-width="200">
          <template #default="{ row }">
            <button type="button" class="title" @click="router.push(`/report/archive/${row.id}`)">
              {{ row.title || "未命名报告" }}
            </button>
            <p class="sub clamp-2">{{ row.excerpt }}</p>
          </template>
        </el-table-column>
        <el-table-column label="判定" width="112">
          <template #default="{ row }">
            <span class="chip" :class="`chip--${verdictTone(row.verdict) === 'warn' ? 'warn' : verdictTone(row.verdict)}`">
              {{ row.verdict_label }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="通过率" width="92" align="right">
          <template #default="{ row }"><span class="mono num">{{ formatPercent(row.pass_rate) }}</span></template>
        </el-table-column>
        <el-table-column label="用例" width="76" align="right">
          <template #default="{ row }"><span class="mono num muted">{{ row.total ?? "—" }}</span></template>
        </el-table-column>
        <el-table-column label="失败" width="72" align="right">
          <template #default="{ row }">
            <span class="mono num" :class="{ 'is-fail': (row.failed ?? 0) > 0 }">{{ row.failed ?? "—" }}</span>
          </template>
        </el-table-column>
        <el-table-column label="模型" width="118">
          <template #default="{ row }">
            <span class="mono muted" :title="row.provider ? `${row.provider} · ${row.model}` : row.model">
              {{ row.model }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="生成时间" width="110">
          <template #default="{ row }"><span class="muted">{{ formatRelative(row.created_at) }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="268" align="right">
          <template #default="{ row }">
            <el-button size="small" text @click="router.push(`/report/archive/${row.id}`)">详情</el-button>
            <el-button size="small" text @click="download(row, 'md')">Markdown</el-button>
            <el-button size="small" text @click="download(row, 'docx')">Word</el-button>
            <el-button size="small" text @click="remove(row)"><AppIcon name="trash" :size="17" /></el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="pageCount > 1" class="pager">
        <el-button size="small" :disabled="page <= 1" @click="goPage(page - 1)">上一页</el-button>
        <span class="pager__text mono">{{ page }} / {{ pageCount }}</span>
        <el-button size="small" :disabled="page >= pageCount" @click="goPage(page + 1)">下一页</el-button>
      </div>
    </SectionCard>

    <SectionCard v-else title="还没有归档的报告" icon="archive">
      <EmptyState
        icon="archive"
        title="生成并归档第一份报告后，这里会记录每一轮"
        reason="每份报告都保留正文、指标快照与原始输入；勾选两轮即可对比通过率、缺陷与判定差异。"
        action-label="去报告工作台"
        @action="router.push('/report')"
      />
    </SectionCard>

    <el-drawer v-model="compareOpen" size="680px" direction="rtl">
      <template #header>
        <div class="dhead">
          <AppIcon name="layers" :size="18" />
          <span class="dhead__title">两轮对比</span>
        </div>
      </template>
      <div v-if="comparing" class="cmp__loading"><el-skeleton :rows="6" animated /></div>
      <EmptyState
        v-else-if="compareBlockedNames.length"
        icon="alert"
        title="这两轮里有一轮没有可对比的指标"
        :reason="
          `「${compareBlockedNames.join('」「')}」没有解析出用例统计字段，指标为空，因此无法参与对比。` +
          '请改选两轮数据完整的报告，或先在工作台用可识别的结构化数据（含 total_cases / passed / failed 等字段）重新生成后再对比。'
        "
      />
      <div v-else-if="compareLeft && compareRight" class="cmp">
        <div class="cmp__head">
          <div class="cmp__side">
            <span class="chip chip--ghost">左侧 · 较早</span>
            <p class="cmp__title">{{ compareLeft.title || compareLeft.id }}</p>
            <p class="cmp__meta mono">{{ formatRelative(compareLeft.created_at) }} · {{ compareLeft.model }}</p>
          </div>
          <div class="cmp__side cmp__side--right">
            <span class="chip chip--glacier">右侧 · 较新</span>
            <p class="cmp__title">{{ compareRight.title || compareRight.id }}</p>
            <p class="cmp__meta mono">{{ formatRelative(compareRight.created_at) }} · {{ compareRight.model }}</p>
          </div>
        </div>

        <ul class="cmp__list">
          <li v-for="item in compareRows" :key="item.label">
            <span class="cmp__k">{{ item.label }}</span>
            <span class="cmp__v mono">{{ item.left }}</span>
            <span class="cmp__v cmp__v--right mono">{{ item.right }}</span>
            <span class="cmp__delta" :data-tone="deltaTone(item)">{{ deltaText(item) }}</span>
          </li>
        </ul>

        <hr class="rule" />
        <div class="cmp__verdict">
          <span class="cmp__k">发版判定</span>
          <span class="chip" :class="`chip--${verdictTone(compareLeft.verdict) === 'warn' ? 'warn' : verdictTone(compareLeft.verdict)}`">
            {{ compareLeft.verdict_label }}
          </span>
          <AppIcon name="chevronRight" :size="14" />
          <span class="chip" :class="`chip--${verdictTone(compareRight.verdict) === 'warn' ? 'warn' : verdictTone(compareRight.verdict)}`">
            {{ compareRight.verdict_label }}
          </span>
        </div>
        <FieldHint>左侧固定为勾选顺序里的第一项、右侧为第二项；正值代表右侧比左侧更高。</FieldHint>
      </div>
      <EmptyState
        v-else
        icon="layers"
        title="对比数据没有准备好"
        reason="需要先勾选两份报告，再点击「对比两轮」。"
      />
    </el-drawer>
  </div>
</template>


<style scoped>
.strip {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--s4) var(--s5);
  padding: var(--s4) var(--s5);
  border: 1px solid var(--ice-3);
  border-radius: var(--radius-lg);
  background: var(--ice-0);
}

/* 指标块与工具条是两组东西：勾选后多出按钮时，工具条换行而不是把指标挤瘪。 */
.strip__stats {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--s4) var(--s5);
  min-width: 0;
}

.strip__tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: var(--s3);
  margin-left: auto;
  min-width: 0;
}

.search {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  height: 32px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-1);
  color: var(--ink-3);
}

.search input {
  border: none;
  outline: none;
  background: transparent;
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--ink-1);
  width: 200px;
}

.sel {
  font-size: var(--fs-xs);
  color: var(--glacier-deep);
  white-space: nowrap;
}

.latest {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.latest__k {
  font-size: var(--fs-2xs);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  color: var(--ink-3);
}

.latest__v {
  font-size: var(--fs-md);
  color: var(--ink-1);
}

.title {
  border: none;
  background: transparent;
  padding: 0;
  font: inherit;
  font-size: var(--fs-sm);
  font-weight: 500;
  color: var(--glacier-deep);
  cursor: pointer;
}

.title:hover {
  text-decoration: underline;
}

.sub {
  margin-top: 2px;
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--ink-3);
}

.is-fail {
  color: var(--fail);
}

.pager {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--s3);
  padding: var(--s3) var(--s4);
  border-top: 1px solid var(--ice-3);
}

.pager__text {
  font-size: var(--fs-xs);
  color: var(--ink-3);
}

.dhead {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.dhead__title {
  font-size: var(--fs-base);
  font-weight: 600;
}

.cmp {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

.cmp__head {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s4);
}

.cmp__side {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--s3);
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-1);
}

.cmp__side--right {
  background: var(--glacier-wash);
  border-color: var(--glacier-tint);
}

.cmp__title {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--ink-1);
}

.cmp__meta {
  font-size: 10.5px;
  color: var(--ink-3);
}

.cmp__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.cmp__list li {
  display: grid;
  grid-template-columns: 1fr 84px 84px 74px;
  align-items: center;
  gap: var(--s2);
  padding: 8px 0;
  border-bottom: 1px solid var(--ice-3);
  font-size: var(--fs-sm);
}

.cmp__k {
  color: var(--ink-2);
}

.cmp__v {
  text-align: right;
  color: var(--ink-1);
}

.cmp__v--right {
  font-weight: 600;
}

.cmp__delta {
  text-align: right;
  font-family: var(--font-data);
  font-size: var(--fs-xs);
  color: var(--ink-3);
}

.cmp__delta[data-tone="up"] {
  color: var(--pass);
}

.cmp__delta[data-tone="down"] {
  color: var(--fail);
}

.cmp__verdict {
  display: flex;
  align-items: center;
  gap: var(--s3);
}

.cmp__loading {
  padding: var(--s4);
}
</style>




