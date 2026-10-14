<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { api, saveBlob } from "@/api";
import type { TestCaseSuiteSummary } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorNote from "@/components/ErrorNote.vue";
import MethodTag from "@/components/MethodTag.vue";
import SectionCard from "@/components/SectionCard.vue";
import { confirmAction } from "@/composables/useFeedback";
import { useHealthStore } from "@/stores/health";
import { useNoticeStore } from "@/stores/notice";
import { engineLabel, engineTitle, formatRelative, methodLabel } from "@/utils/labels";

const router = useRouter();
const notice = useNoticeStore();
const health = useHealthStore();

const suites = ref<TestCaseSuiteSummary[]>([]);
const loading = ref(true);
const error = ref("");
const keyword = ref("");
const exporting = ref("");

/**
 * 导出格式名以后端注册表为准（Excel 的 name 是 `excel`，不是文件后缀 `xlsx`）。
 * 从能力清单里取而不是写死字面量：后端哪天改名，这里跟着走，不会 404。
 */
const excelFormat = computed(
  () =>
    health.exportFormats.find((item) => item.name === "excel") ?? {
      name: "excel",
      label: "Excel",
      media_type: "",
      extension: "xlsx",
    },
);

const tableRef = ref<{ clearSelection: () => void } | null>(null);
const checked = ref<TestCaseSuiteSummary[]>([]);
const batchDeleting = ref(false);

const rows = computed(() => {
  const needle = keyword.value.trim().toLowerCase();
  if (!needle) return suites.value;
  return suites.value.filter((suite) =>
    `${suite.doc_title} ${suite.suite_id} ${suite.doc_id} ${engineLabel(suite.generation_meta)} ${suite.methods.map(methodLabel).join(" ")}`
      .toLowerCase()
      .includes(needle),
  );
});

const totals = computed(() => ({
  suites: suites.value.length,
  cases: suites.value.reduce((sum, item) => sum + item.stats.total, 0),
  dedup: suites.value.reduce((sum, item) => sum + item.stats.duplicate_removed, 0),
}));

function openRequirement(suite: TestCaseSuiteSummary): void {
  void router.push(`/documents/${suite.doc_id}/requirement`);
}

onMounted(() => {
  void load();
});

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    suites.value = await api.suites(50);
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    loading.value = false;
  }
}

async function exportSuite(suite: TestCaseSuiteSummary, format: string): Promise<void> {
  exporting.value = `${suite.suite_id}:${format}`;
  try {
    const file = await api.exportSuite(suite.suite_id, format);
    const extension = health.exportFormats.find((item) => item.name === format)?.extension || format;
    saveBlob(file.blob, file.filename || `用例集.${extension}`);
    notice.success("导出完成", file.filename || undefined);
  } catch (err) {
    notice.error("导出失败", (err as Error).message);
  } finally {
    exporting.value = "";
  }
}

async function remove(suite: TestCaseSuiteSummary): Promise<void> {
  const confirmed = await confirmAction({
    title: "删除用例集",
    message: `将删除「${suite.doc_title || suite.suite_id}」这份用例集（${suite.stats.total} 条）。删除后不可恢复，需求量与文档都会保留。`,
    confirmText: "删除",
    danger: true,
  });
  if (!confirmed) return;
  try {
    await api.deleteSuite(suite.suite_id);
    notice.success("已删除用例集");
    await load();
  } catch (err) {
    notice.error("删除失败", (err as Error).message);
  }
}

function onSelectionChange(rows: TestCaseSuiteSummary[]): void {
  checked.value = rows;
}

function clearSelection(): void {
  tableRef.value?.clearSelection();
  checked.value = [];
}

async function removeSelected(): Promise<void> {
  const ids = checked.value.map((row) => row.suite_id);
  if (!ids.length) return;
  const cases = checked.value.reduce((sum, row) => sum + row.stats.total, 0);
  const confirmed = await confirmAction({
    title: `批量删除 ${ids.length} 份用例集`,
    message: `将删除这 ${ids.length} 份用例集（共 ${cases} 条用例）。删除后不可恢复，需求量与文档都会保留。`,
    confirmText: `删除 ${ids.length} 份`,
    danger: true,
  });
  if (!confirmed) return;
  batchDeleting.value = true;
  try {
    const result = await api.batchDeleteSuites(ids);
    if (result.missing.length) {
      notice.info(
        `已删除 ${result.deleted} 份用例集`,
        `${result.missing.length} 份在服务端已不存在，已自动跳过。`,
      );
    } else {
      notice.success(`已删除 ${result.deleted} 份用例集`);
    }
    clearSelection();
    await load();
  } catch (err) {
    notice.error("批量删除失败", (err as Error).message);
  } finally {
    batchDeleting.value = false;
  }
}
</script>

<template>
  <div class="stack">
    <ErrorNote
      v-if="error"
      title="用例集列表没有取到"
      :message="error"
      recovery="确认后端已启动（python run.py），然后重试。"
      @retry="load"
    />

    <section class="strip">
      <div class="strip__cell">
        <p class="strip__k">用例集</p>
        <p class="strip__v mono">{{ totals.suites }}</p>
      </div>
      <div class="strip__cell">
        <p class="strip__k">用例总数</p>
        <p class="strip__v mono">{{ totals.cases }}</p>
      </div>
      <div class="strip__cell">
        <p class="strip__k">累计去重</p>
        <p class="strip__v mono">{{ totals.dedup }}</p>
      </div>
      <div class="spacer" />
      <div class="search">
        <AppIcon name="search" :size="15" />
        <input v-model="keyword" type="search" placeholder="按标题 / 编号 / 方法搜索" aria-label="搜索用例集" />
      </div>
      <span v-if="checked.length" class="sel mono">已选 {{ checked.length }}</span>
      <el-button v-if="checked.length" size="small" text @click="clearSelection">取消选择</el-button>
      <el-button
        v-if="checked.length"
        size="small"
        type="danger"
        plain
        :loading="batchDeleting"
        @click="removeSelected"
      >
        <AppIcon name="trash" :size="16" /> 批量删除
      </el-button>
      <el-button size="small" @click="load"><AppIcon name="refresh" :size="14" /> 刷新</el-button>
    </section>

    <SectionCard
      v-if="rows.length || loading"
      title="用例集"
      :sub="`${rows.length} / ${suites.length} 份`"
      icon="cases"
      flush
    >
      <el-table
        ref="tableRef"
        v-loading="loading"
        :data="rows"
        size="small"
        row-key="suite_id"
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="42" />
        <el-table-column label="用例集" min-width="180">
          <template #default="{ row }">
            <button type="button" class="title" @click="router.push(`/suites/${row.suite_id}`)">
              {{ row.doc_title || "未命名" }}
            </button>
            <span v-if="row.revision" class="rev mono" :title="`同一需求下的第 ${row.revision} 版`">
              第 {{ row.revision }} 版
            </span>
            <p class="sub mono">{{ row.suite_id.slice(0, 18) }}</p>
          </template>
        </el-table-column>
        <el-table-column label="来源需求" width="140">
          <template #default="{ row }">
            <button
              type="button"
              class="sourcereq mono"
              :title="`打开「${row.doc_title || row.doc_id}」的结构化需求`"
              @click="openRequirement(row)"
            >
              {{ row.doc_id }}
            </button>
          </template>
        </el-table-column>
        <el-table-column label="设计方法" min-width="150">
          <template #default="{ row }">
            <span class="tags">
              <MethodTag v-for="method in row.methods" :key="method" :method="method" />
            </span>
          </template>
        </el-table-column>
        <el-table-column label="用例" width="96" align="right">
          <template #default="{ row }">
            <span class="mono num">{{ row.stats.total }}</span>
            <p v-if="row.stats.duplicate_removed" class="dup mono">去重 -{{ row.stats.duplicate_removed }}</p>
          </template>
        </el-table-column>
        <el-table-column label="生成引擎" width="146">
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
        <el-table-column label="生成时间" width="100">
          <template #default="{ row }"><span class="muted">{{ formatRelative(row.created_at) }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="284" align="right">
          <template #default="{ row }">
            <el-button size="small" text @click="router.push(`/suites/${row.suite_id}`)">查看</el-button>
            <el-button
              size="small"
              text
              :loading="exporting === `${row.suite_id}:${excelFormat.name}`"
              @click="exportSuite(row, excelFormat.name)"
            >
              导出 Excel
            </el-button>
            <el-button size="small" text @click="exportSuite(row, 'json')">JSON</el-button>
            <el-button size="small" text @click="remove(row)"><AppIcon name="trash" :size="17" /></el-button>
          </template>
        </el-table-column>
      </el-table>
    </SectionCard>

    <SectionCard v-else title="还没有用例集" icon="cases">
      <EmptyState
        icon="cases"
        title="生成第一份用例集后，这里会记录每一次产出"
        reason="每一份用例集都保留生成时间、设计方法、去重条数与引擎策略，可随时回看、导出或删除。"
        action-label="去生成用例"
        @action="router.push('/generate')"
      />
    </SectionCard>
  </div>
</template>

<style scoped>
.strip {
  display: flex;
  align-items: center;
  gap: var(--s5);
  padding: var(--s3) var(--s4);
  border: 1px solid var(--ice-3);
  border-radius: var(--radius-lg);
  background: var(--ice-0);
}

.strip__cell {
  min-width: 84px;
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
  border: none;
  outline: none;
  background: transparent;
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--ink-1);
  width: 220px;
}

.sel {
  font-size: var(--fs-xs);
  color: var(--glacier-deep);
  white-space: nowrap;
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
  font-size: 10.5px;
  color: var(--ink-3);
}

.rev {
  display: inline-block;
  margin-bottom: 2px;
  padding: 1px 6px;
  border: 1px solid var(--ice-3);
  border-radius: 999px;
  font-size: var(--fs-2xs);
  color: var(--ink-2);
}

.sourcereq {
  border: none;
  background: transparent;
  padding: 0;
  font-size: var(--fs-xs);
  color: var(--glacier-deep);
  cursor: pointer;
}

.sourcereq:hover {
  text-decoration: underline;
}

.dup {
  margin-top: 2px;
  font-size: 10.5px;
  color: var(--ink-3);
}

.tags {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
}
</style>

