<script setup lang="ts">
import { computed, ref, watch } from "vue";

import type { TestCase, TestCaseSuite } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import MethodTag from "@/components/MethodTag.vue";
import PriorityMark from "@/components/PriorityMark.vue";
import Tip from "@/components/Tip.vue";
import { useNoticeStore } from "@/stores/notice";
import {
  CASE_SOURCE_LABELS,
  METHOD_ORDER,
  claimStatusLabel,
  methodLabel,
} from "@/utils/labels";

const props = defineProps<{ suite: TestCaseSuite }>();

const notice = useNoticeStore();
const keyword = ref("");
const methodFilter = ref("");
const priorityFilter = ref("");
const expanded = ref<string[]>([]);
/**
 * 分页：一次生成几百条用例是常态（示例需求就能到 200+，六种方法全开可到 500+），
 * 全部铺在一页里既没人读得完、也让页面变得极长。默认每页 50 条。
 */
const page = ref(1);
const pageSize = ref(50);

const methodOptions = computed(() => {
  const counts = new Map<string, number>();
  props.suite.cases.forEach((item) =>
    counts.set(item.design_method, (counts.get(item.design_method) ?? 0) + 1),
  );
  return METHOD_ORDER.filter((method) => counts.has(method)).map((method) => ({
    value: method,
    label: methodLabel(method),
    count: counts.get(method) ?? 0,
  }));
});

const EXPORT_FIELDS = [
  "用例编号",
  "所属模块",
  "用例标题",
  "设计方法",
  "用例类型",
  "优先级",
  "关联需求",
  "前置条件",
  "测试步骤",
  "预期结果",
  "测试数据",
  "标签",
  "备注",
  "来源",
  "覆盖方法",
] as const;

function exportRecord(row: TestCase): Record<(typeof EXPORT_FIELDS)[number], string> {
  const covered = (row.covered_methods.length ? row.covered_methods : [row.design_method])
    .map(methodLabel)
    .join("、");
  return {
    用例编号: row.case_id,
    所属模块: row.module,
    用例标题: row.title,
    设计方法: methodLabel(row.design_method),
    用例类型: row.case_type,
    优先级: row.priority,
    关联需求: row.requirement_ids.join("、"),
    前置条件: row.preconditions.join("\n"),
    测试步骤: row.steps
      .map((step) => `${step.no}. ${step.action}${step.expected ? ` -> ${step.expected}` : ""}`)
      .join("\n"),
    预期结果: row.expected_result,
    测试数据: Object.entries(row.test_data)
      .map(([key, value]) => `${key} = ${value || "(空)"}`)
      .join("\n"),
    标签: row.tags.join("、"),
    备注: row.remarks,
    来源: CASE_SOURCE_LABELS[row.source] ?? row.source,
    覆盖方法: covered,
  };
}

const rows = computed(() => {
  const needle = keyword.value.trim().toLowerCase();
  return props.suite.cases.filter((item) => {
    if (methodFilter.value && item.design_method !== methodFilter.value) return false;
    if (priorityFilter.value && item.priority !== priorityFilter.value) return false;
    if (!needle) return true;
    const haystack = `${item.case_id} ${item.title} ${item.module} ${item.expected_result}`.toLowerCase();
    return haystack.includes(needle);
  });
});

const pagedRows = computed(() =>
  pageSize.value > 0
    ? rows.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value)
    : rows.value,
);

// 筛选条件一变行集合就变了：停在一个已经不存在的页码上会看到空表。
watch([rows, pageSize], () => {
  const maxPage = pageSize.value > 0 ? Math.max(1, Math.ceil(rows.value.length / pageSize.value)) : 1;
  if (page.value > maxPage) page.value = maxPage;
});

function toggle(row: TestCase) {
  const index = expanded.value.indexOf(row.case_id);
  if (index === -1) expanded.value.push(row.case_id);
  else expanded.value.splice(index, 1);
}

async function copyRow(row: TestCase) {
  const record = exportRecord(row);
  const lines = [
    ...EXPORT_FIELDS.map((key) => `${key}：${record[key] || "—"}`),
    `可信状态：${claimStatusLabel(row.claim_status)}`,
    `证据：${row.evidence_quotes.join("；") || "—"}`,
    `不确定性：${row.uncertainty_reason || "—"}`,
  ];
  try {
    await navigator.clipboard.writeText(lines.join("\n"));
    notice.success("已复制到剪贴板", `${row.case_id} 的 15 个导出字段与可信状态`);
  } catch {
    notice.error("复制失败", "浏览器拒绝了剪贴板访问，请手动选中表格内容复制。");
  }
}

function copyAll() {
  const header = EXPORT_FIELDS.join("\t");
  const body = rows.value.map((row) => {
    const record = exportRecord(row);
    return EXPORT_FIELDS.map((key) => record[key].replaceAll("\n", "；")).join("\t");
  });
  void navigator.clipboard
    .writeText([header, ...body].join("\n"))
    .then(() => notice.success("已复制当前筛选结果", `共 ${rows.value.length} 条，可直接粘贴进 Excel。`))
    .catch(() => notice.error("复制失败", "浏览器拒绝了剪贴板访问。"));
}

defineExpose({ filtered: rows });
</script>

<template>
  <div class="cases">
    <div class="cases__bar">
      <div class="cases__search">
        <AppIcon name="search" :size="15" />
        <input
          v-model="keyword"
          type="search"
          placeholder="搜索编号 / 标题 / 模块 / 预期结果"
          aria-label="搜索用例"
        />
      </div>

      <el-select v-model="methodFilter" placeholder="全部方法" size="small" style="width: 148px" clearable>
        <el-option
          v-for="item in methodOptions"
          :key="item.value"
          :label="`${item.label} · ${item.count}`"
          :value="item.value"
        />
      </el-select>

      <el-select v-model="priorityFilter" placeholder="全部优先级" size="small" style="width: 132px" clearable>
        <el-option v-for="item in ['P0', 'P1', 'P2', 'P3']" :key="item" :label="item" :value="item" />
      </el-select>

      <span class="cases__count mono">{{ rows.length }} / {{ suite.cases.length }}</span>
      <div class="spacer" />
      <el-button size="small" @click="copyAll">
          <AppIcon name="copy" :size="16" />
        复制筛选结果
      </el-button>
    </div>

    <el-table
      :data="pagedRows"
      row-key="case_id"
      size="small"
      :default-sort="{ prop: 'case_id', order: 'ascending' }"
      @row-click="toggle"
    >
      <el-table-column type="expand" width="34">
        <template #default="{ row }">
          <div class="detail">
            <div class="detail__col">
              <p class="label">前置条件</p>
              <ul v-if="row.preconditions.length" class="detail__list">
                <li v-for="item in row.preconditions" :key="item">{{ item }}</li>
              </ul>
              <p v-else class="detail__none">无前置条件。</p>

              <p class="label detail__gap">测试数据</p>
              <ul v-if="Object.keys(row.test_data).length" class="detail__list mono">
                <li v-for="(value, key) in row.test_data" :key="key">
                  {{ key }} = <strong>{{ value || "(空)" }}</strong>
                </li>
              </ul>
              <p v-else class="detail__none">该用例不依赖具体测试数据。</p>
            </div>

            <div class="detail__col">
              <p class="label">操作步骤</p>
              <ol v-if="row.steps.length" class="detail__steps">
                <li v-for="step in row.steps" :key="step.no">
                  <span>{{ step.action }}</span>
                  <span v-if="step.expected" class="detail__expect">预期：{{ step.expected }}</span>
                </li>
              </ol>
              <p v-else class="detail__none">该用例没有展开步骤（见预期结果）。</p>

              <p class="label detail__gap">追溯</p>
              <div class="detail__trace">
                <span v-for="req in row.requirement_ids" :key="req" class="stamp mono">{{ req }}</span>
                <span v-if="!row.requirement_ids.length" class="detail__none">未关联需求条目。</span>
              </div>

              <p class="label detail__gap">
                覆盖方法
                <Tip text="去重合并后，这条用例可能同时覆盖多种设计方法：深色是生成它的方法，浅色是被同时覆盖的方法。" />
              </p>
              <div class="detail__trace">
                <MethodTag
                  v-for="method in row.covered_methods.length ? row.covered_methods : [row.design_method]"
                  :key="method"
                  :method="method"
                  :muted="method !== row.design_method"
                />
              </div>

              <p class="label detail__gap">标签 / 来源 / 可信状态</p>
              <div class="detail__tags">
                <span v-for="tag in row.tags" :key="tag" class="tag mono">{{ tag }}</span>
                <span v-if="!row.tags.length" class="detail__none">无标签。</span>
              </div>
              <p class="detail__meta">
                来源：{{ CASE_SOURCE_LABELS[row.source] ?? row.source }} ·
                可信状态：{{ claimStatusLabel(row.claim_status) }}
              </p>
              <p v-if="row.uncertainty_reason" class="detail__uncertain">
                不确定性：{{ row.uncertainty_reason }}
              </p>
            </div>

            <div class="detail__full">
              <p class="label">备注与原文证据</p>
              <p class="detail__remark">{{ row.remarks || "—" }}</p>
              <ul v-if="row.evidence_quotes.length" class="detail__list evidence">
                <li v-for="quote in row.evidence_quotes" :key="quote">“{{ quote }}”</li>
              </ul>
              <p v-else class="detail__none">未记录可核验的原文证据；该内容应按可信状态人工复核。</p>
            </div>
          </div>
        </template>
      </el-table-column>

      <el-table-column prop="case_id" label="编号" width="112" sortable>
        <template #default="{ row }">
          <span class="mono cases__id">{{ row.case_id }}</span>
        </template>
      </el-table-column>

      <el-table-column prop="title" label="用例标题" min-width="236" show-overflow-tooltip />

      <el-table-column prop="module" label="所属模块" width="120" show-overflow-tooltip />

      <el-table-column label="设计方法" width="110">
        <template #default="{ row }"><MethodTag :method="row.design_method" /></template>
      </el-table-column>

      <el-table-column prop="case_type" label="类型" width="72" />

      <el-table-column label="优先级" width="92" sortable prop="priority">
        <template #default="{ row }"><PriorityMark :priority="row.priority" /></template>
      </el-table-column>


      <el-table-column prop="expected_result" label="预期结果" min-width="200" show-overflow-tooltip />

      <el-table-column label="" width="52" fixed="right">
        <template #default="{ row }">
          <button type="button" class="cases__copy" title="复制这条用例" @click.stop="copyRow(row)">
            <AppIcon name="copy" :size="17" />
          </button>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="pageSize > 0 && rows.length > pageSize" class="cases__pager">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :page-sizes="[20, 50, 100, 200]"
        :total="rows.length"
        size="small"
        layout="total, sizes, prev, pager, next"
        background
      />
    </div>
  </div>
</template>

<style scoped>
.cases__pager {
  display: flex;
  justify-content: flex-end;
  padding: var(--s3) var(--s4);
  border-top: 1px solid var(--ice-3);
  overflow-x: auto;
}

.cases__bar {
  display: flex;
  align-items: center;
  gap: var(--s2);
  padding: var(--s3) var(--s4);
  border-bottom: 1px solid var(--ice-3);
  flex-wrap: wrap;
}

.cases__search {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-1);
  color: var(--ink-3);
  flex: 1 1 220px;
  max-width: 320px;
}

.cases__search:focus-within {
  border-color: var(--glacier);
  background: var(--ice-0);
}

.cases__search input {
  flex: 1 1 auto;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  font: inherit;
  font-size: var(--fs-xs);
  color: var(--ink-1);
}

.cases__count {
  font-size: var(--fs-xs);
  color: var(--ink-3);
}

.cases__id {
  font-size: var(--fs-xs);
  color: var(--glacier-deep);
}


.cases__copy {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
}

.cases__copy:hover {
  background: var(--glacier-wash);
  border-color: var(--glacier-tint);
  color: var(--glacier-deep);
}

.detail {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr);
  gap: var(--s5);
  padding: var(--s4) var(--s5);
  background: var(--ice-1);
  border-top: 1px solid var(--ice-3);
  border-bottom: 1px solid var(--ice-3);
}

.detail__col {
  min-width: 0;
}

.detail__gap {
  margin-top: var(--s4);
  display: block;
}

.detail__list,
.detail__steps {
  margin: var(--s2) 0 0;
  padding-left: 1.2em;
  font-size: var(--fs-sm);
  color: var(--ink-2);
  line-height: 1.7;
}

.detail__steps li {
  margin-bottom: 6px;
}

.detail__expect {
  display: block;
  color: var(--ink-3);
  font-size: var(--fs-xs);
}

.detail__none {
  margin-top: var(--s2);
  font-size: var(--fs-xs);
  color: var(--ink-3);
}

.detail__trace {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: var(--s2);
}

.detail__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: var(--s2);
}

.tag {
  padding: 1px 7px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius-pill);
  background: var(--ice-0);
  font-size: 10.5px;
  color: var(--ink-2);
}

.detail__meta,
.detail__uncertain,
.detail__remark {
  margin-top: 5px;
  font-size: var(--fs-xs);
  line-height: 1.65;
  color: var(--ink-2);
  overflow-wrap: anywhere;
}

.detail__uncertain {
  color: var(--warn);
}

.detail__full {
  grid-column: 1 / -1;
  padding-top: var(--s3);
  border-top: 1px dashed var(--ice-4);
}

.evidence li {
  color: var(--ink-2);
}

@media (max-width: 900px) {
  .detail {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>


