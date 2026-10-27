<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { api, saveBlob } from "@/api";
import type { ApiSpecSummary } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorNote from "@/components/ErrorNote.vue";
import SectionCard from "@/components/SectionCard.vue";
import { confirmAction } from "@/composables/useFeedback";
import { useActionSession } from "@/stores/actionSession";
import { useNoticeStore } from "@/stores/notice";
import { formatBytes, formatRelative } from "@/utils/labels";

const router = useRouter();
const notice = useNoticeStore();
const actions = useActionSession();

const specs = ref<ApiSpecSummary[]>([]);
const loading = ref(true);
const importing = computed(() => actions.isRunning("api-spec.import"));
const exporting = ref("");
const error = ref("");
const keyword = ref("");
const fileInput = ref<HTMLInputElement | null>(null);
let viewAlive = true;

const rows = computed(() => {
  const needle = keyword.value.trim().toLowerCase();
  if (!needle) return specs.value;
  return specs.value.filter((item) =>
    `${item.title} ${item.version} ${item.openapi_version} ${item.source_file} ${item.spec_id}`
      .toLowerCase()
      .includes(needle),
  );
});

const totals = computed(() => ({
  specs: specs.value.length,
  operations: specs.value.reduce((sum, item) => sum + item.stats.operations, 0),
  cases: specs.value.reduce((sum, item) => sum + item.stats.cases, 0),
  gaps: specs.value.reduce((sum, item) => sum + item.stats.operation_gaps, 0),
}));

onMounted(() => {
  void load();
});

onBeforeUnmount(() => {
  viewAlive = false;
});

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    specs.value = await api.apiSpecs(100);
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    loading.value = false;
  }
}

function chooseFile(): void {
  fileInput.value?.click();
}

async function onFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  if (!/\.(json|ya?ml)$/i.test(file.name)) {
    notice.error("文件格式不支持", "请选择 OpenAPI 3 的 .json、.yaml 或 .yml 文件。");
    return;
  }
  if (!actions.begin("api-spec.import", file.name)) return;
  try {
    const result = await api.importApiSpec(file);
    notice.success(
      "OpenAPI 已导入",
      `${result.spec.stats.operations} 个 operation · ${result.spec.stats.cases} 条接口用例`,
    );
    if (viewAlive) {
      await load();
      await router.push(`/apis/${result.spec.spec_id}`);
    }
  } catch (err) {
    notice.error("导入失败", (err as Error).message);
  } finally {
    actions.end("api-spec.import");
  }
}

async function exportPostman(spec: ApiSpecSummary): Promise<void> {
  exporting.value = spec.spec_id;
  try {
    const file = await api.exportApiPostman(spec.spec_id);
    saveBlob(file.blob, file.filename || `${spec.title}.postman_collection.json`);
    notice.success("Postman Collection 已导出", file.filename || undefined);
  } catch (err) {
    notice.error("导出失败", (err as Error).message);
  } finally {
    exporting.value = "";
  }
}

async function remove(spec: ApiSpecSummary): Promise<void> {
  const confirmed = await confirmAction({
    title: "删除接口规范",
    message: `将删除「${spec.title}」及由它生成的 ${spec.stats.cases} 条接口用例。源文件和用例均不可恢复。`,
    confirmText: "删除",
    danger: true,
  });
  if (!confirmed) return;
  try {
    await api.deleteApiSpec(spec.spec_id);
    notice.success("接口规范已删除");
    await load();
  } catch (err) {
    notice.error("删除失败", (err as Error).message);
  }
}
</script>

<template>
  <div class="stack">
    <ErrorNote
      v-if="error"
      title="接口资产没有取到"
      :message="error"
      recovery="确认后端已启动，然后刷新重试。"
      @retry="load"
    />

    <section class="strip">
      <div class="strip__cell">
        <p class="strip__k">规范</p>
        <p class="strip__v mono">{{ totals.specs }}</p>
      </div>
      <div class="strip__cell">
        <p class="strip__k">Operations</p>
        <p class="strip__v mono">{{ totals.operations }}</p>
      </div>
      <div class="strip__cell">
        <p class="strip__k">契约用例</p>
        <p class="strip__v mono">{{ totals.cases }}</p>
      </div>
      <div class="strip__cell">
        <p class="strip__k">待补充</p>
        <p class="strip__v mono" :class="{ 'is-warn': totals.gaps }">{{ totals.gaps }}</p>
      </div>
      <div class="spacer" />
      <div class="search">
        <AppIcon name="search" :size="15" />
        <input v-model="keyword" type="search" placeholder="标题 / 版本 / 文件" aria-label="搜索接口规范" />
      </div>
      <el-button size="small" @click="load"><AppIcon name="refresh" :size="14" /> 刷新</el-button>
      <el-button type="primary" size="small" :loading="importing" @click="chooseFile">
        <AppIcon name="upload" :size="14" /> 导入 OpenAPI
      </el-button>
      <input
        ref="fileInput"
        class="file"
        type="file"
        accept=".json,.yaml,.yml,application/json,application/yaml,text/yaml"
        @change="onFile"
      />
    </section>

    <SectionCard
      v-if="rows.length || loading"
      title="接口规范"
      :sub="`${rows.length} / ${specs.length} 份 · OpenAPI 3`"
      icon="route"
      flush
    >
      <el-table v-loading="loading" :data="rows" size="small" row-key="spec_id">
        <el-table-column label="规范" min-width="230">
          <template #default="{ row }">
            <button type="button" class="title" @click="router.push(`/apis/${row.spec_id}`)">
              {{ row.title || "未命名接口规范" }}
            </button>
            <p class="sub mono">
              {{ row.source_file }} · {{ row.openapi_version }}
              <span v-if="row.version"> · v{{ row.version }}</span>
            </p>
          </template>
        </el-table-column>
        <el-table-column label="Operations" width="112" align="right">
          <template #default="{ row }"><span class="mono num">{{ row.stats.operations }}</span></template>
        </el-table-column>
        <el-table-column label="用例" width="88" align="right">
          <template #default="{ row }"><span class="mono num">{{ row.stats.cases }}</span></template>
        </el-table-column>
        <el-table-column label="契约断言" width="112" align="right">
          <template #default="{ row }">
            <span class="mono num">{{ row.stats.contract_assertions }}</span>
          </template>
        </el-table-column>
        <el-table-column label="缺口" width="96">
          <template #default="{ row }">
            <span class="chip" :class="row.stats.operation_gaps ? 'chip--warn' : 'chip--pass'">
              {{ row.stats.operation_gaps ? `${row.stats.operation_gaps} 处` : "无" }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="118">
          <template #default="{ row }">
            <span class="muted mono">{{ formatBytes(row.size_bytes) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="导入时间" width="104">
          <template #default="{ row }">
            <span class="muted">{{ formatRelative(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="248" align="right">
          <template #default="{ row }">
            <el-button size="small" text @click="router.push(`/apis/${row.spec_id}`)">查看</el-button>
            <el-button
              size="small"
              text
              :loading="exporting === row.spec_id"
              @click="exportPostman(row)"
            >
              Postman
            </el-button>
            <el-button size="small" text @click="remove(row)">
              <AppIcon name="trash" :size="17" />
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </SectionCard>

    <SectionCard v-else title="还没有接口规范" icon="route">
      <EmptyState
        icon="route"
        title="暂无接口规范"
        reason="支持 JSON / YAML；缺失约束会标为待补充。"
        action-label="导入 OpenAPI"
        @action="chooseFile"
      />
    </SectionCard>
  </div>
</template>

<style scoped>
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

.strip__cell {
  min-width: 76px;
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

.strip__v.is-warn {
  color: var(--warn);
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
  width: 190px;
  border: none;
  outline: none;
  background: transparent;
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--ink-1);
}

.file {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
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
  color: var(--ink-3);
}

@media (max-width: 900px) {
  .search {
    width: 100%;
  }

  .search input {
    flex: 1;
    width: auto;
  }
}
</style>
