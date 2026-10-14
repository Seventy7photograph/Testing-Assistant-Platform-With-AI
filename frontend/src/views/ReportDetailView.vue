<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api, saveBlob } from "@/api";
import type { ReportDetail } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorNote from "@/components/ErrorNote.vue";
import FieldHint from "@/components/FieldHint.vue";
import MarkdownBody from "@/components/MarkdownBody.vue";
import SectionCard from "@/components/SectionCard.vue";
import WarningList from "@/components/WarningList.vue";
import StatReadout from "@/components/StatReadout.vue";
import Tip from "@/components/Tip.vue";
import VerdictSeal from "@/components/VerdictSeal.vue";
import { confirmAction } from "@/composables/useFeedback";
import { useNoticeStore } from "@/stores/notice";
import { formatDuration, formatPercent, formatTime } from "@/utils/labels";

const route = useRoute();
const router = useRouter();
const notice = useNoticeStore();

const reportId = computed(() => String(route.params.reportId ?? ""));
const detail = ref<ReportDetail | null>(null);
const loading = ref(true);
const error = ref("");
const showSource = ref(false);

const metrics = computed(() => detail.value?.metrics ?? null);

onMounted(() => {
  void load();
});

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    detail.value = await api.report(reportId.value);
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    loading.value = false;
  }
}

async function download(format: string): Promise<void> {
  if (!detail.value) return;
  try {
    const file = await api.exportReport(detail.value.id, format);
    saveBlob(file.blob, file.filename || `测试报告.${format}`);
    notice.success("导出完成", file.filename || undefined);
  } catch (err) {
    notice.error("导出失败", (err as Error).message);
  }
}

async function remove(): Promise<void> {
  if (!detail.value) return;
  const confirmed = await confirmAction({
    title: "删除报告",
    message: `将删除「${detail.value.title || detail.value.id}」这份报告（含正文、指标快照与原始输入）。删除后不可恢复。`,
    confirmText: "删除",
    danger: true,
  });
  if (!confirmed) return;
  try {
    await api.deleteReport(detail.value.id);
    notice.success("已删除报告");
    await router.push("/report/archive");
  } catch (err) {
    notice.error("删除失败", (err as Error).message);
  }
}

function printReport(): void {
  window.print();
}
</script>

<template>
  <div class="stack">
    <ErrorNote
      v-if="error"
      title="报告详情没有取到"
      :message="error"
      recovery="可能已被删除；回到报告存档确认，或检查后端是否已启动。"
      @retry="load"
    />

    <template v-if="detail">
      <SectionCard
        :title="detail.title || '未命名报告'"
        :sub="`${detail.model} · ${detail.provider} · ${formatTime(detail.created_at)}`"
        icon="doc"
      >
        <template #actions>
          <el-button size="small" @click="router.push('/report/archive')">返回存档</el-button>
          <el-button size="small" @click="download('md')">Markdown</el-button>
          <el-button size="small" @click="download('html')">HTML</el-button>
          <el-button size="small" @click="download('docx')">Word</el-button>
          <el-button size="small" @click="download('json')">JSON</el-button>
          <el-button size="small" @click="printReport"><AppIcon name="file" :size="14" /> 打印</el-button>
          <el-button size="small" @click="remove"><AppIcon name="trash" :size="17" /> 删除</el-button>
        </template>

        <div v-if="metrics" class="top">
          <VerdictSeal :verdict="metrics.verdict" :label="metrics.verdict_label" />
          <div class="top__grid">
            <StatReadout label="用例总数" :value="metrics.total" tone="glacier" hint="识别到的用例条目数" />
            <StatReadout
              label="通过率"
              :value="formatPercent(metrics.pass_rate)"
              :tone="metrics.pass_rate >= 0.95 ? 'pass' : 'warn'"
              hint="已通过 / 已执行"
            />
            <StatReadout label="失败" :value="metrics.failed" :tone="metrics.failed > 0 ? 'fail' : 'default'" hint="本轮失败用例数" />
            <StatReadout label="阻塞" :value="metrics.blocked" :tone="metrics.blocked > 0 ? 'warn' : 'default'" hint="无法执行的用例数" />
            <StatReadout label="执行率" :value="formatPercent(metrics.execution_rate)" hint="已执行 / 用例总数" />
            <StatReadout label="未关闭缺陷" :value="metrics.defects_open" :tone="metrics.open_p0 > 0 ? 'fail' : 'default'" hint="含未标注状态的缺陷" />
            <StatReadout label="生成耗时" :value="formatDuration(detail.elapsed_ms)" hint="模型生成正文的耗时" />
            <StatReadout
              v-if="detail.version"
              label="版本"
              :value="detail.version"
              hint="从执行数据中识别到的版本号"
            />
          </div>
        </div>

        <ul v-if="metrics?.verdict_reasons.length" class="reasons">
          <li v-for="reason in metrics.verdict_reasons" :key="reason">
            <AppIcon name="alert" :size="13" /><span>{{ reason }}</span>
          </li>
        </ul>

        <div class="meta">
          <span class="chip" :class="`chip--${metrics?.verdict === 'pass' ? 'pass' : metrics?.verdict === 'reject' ? 'fail' : 'warn'}`">
            {{ metrics?.verdict_label ?? "无法判定" }}
          </span>
          <Tip :text="`报告编号：${detail.id}`">
            <span class="chip chip--ghost mono">{{ detail.id.slice(0, 12) }}</span>
          </Tip>
        </div>
      </SectionCard>

      <SectionCard v-if="detail.defects.length" title="缺陷清单" :sub="`${detail.defects.length} 条`" icon="bug" flush>
        <el-table :data="detail.defects" size="small" :border="false" max-height="360">
          <el-table-column prop="id" label="编号" width="120">
            <template #default="{ row }"><span class="mono">{{ row.id || "—" }}</span></template>
          </el-table-column>
          <el-table-column label="标题" min-width="240">
            <template #default="{ row }">{{ row.title || "—" }}</template>
          </el-table-column>
          <el-table-column prop="module" label="模块" width="140" />
          <el-table-column label="优先级" width="92">
            <template #default="{ row }"><span class="mono">{{ row.priority || "—" }}</span></template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <span class="chip" :class="row.status === 'open' ? 'chip--fail' : 'chip--pass'">
                {{ row.status === "open" ? "未关闭" : "已关闭" }}
              </span>
            </template>
          </el-table-column>
        </el-table>
      </SectionCard>

      <SectionCard title="报告正文" :sub="detail.instruction ? `分析要求：${detail.instruction}` : undefined" icon="chart">
        <MarkdownBody :source="detail.report" />
      </SectionCard>

      <SectionCard v-if="detail.warnings.length" title="生成时的提示" icon="alert">
        <WarningList :items="detail.warnings" />
      </SectionCard>

      <SectionCard title="原始执行数据" sub="报告只做归纳，不修改输入" icon="file">
        <template #actions>
          <el-button size="small" @click="showSource = !showSource">
            {{ showSource ? "收起" : "展开" }}
          </el-button>
        </template>
        <pre v-if="showSource" class="source pre">{{ detail.source_data }}</pre>
        <FieldHint v-else>
          原文 {{ detail.source_data.length }} 字。展开可核对报告里的每个数字是否来自这份输入。
        </FieldHint>
      </SectionCard>
    </template>

    <div v-else-if="loading" class="grid grid--2">
      <div v-for="n in 2" :key="n" class="card"><el-skeleton :rows="6" animated class="skel" /></div>
    </div>

    <SectionCard v-else title="报告不存在" icon="doc">
      <EmptyState
        icon="archive"
        title="这份报告已经不在了"
        reason="它可能已被删除，或链接里的编号不正确。"
        action-label="返回报告存档"
        @action="router.push('/report/archive')"
      />
    </SectionCard>
  </div>
</template>

<style scoped>
.top {
  display: flex;
  align-items: center;
  gap: var(--s5);
}

.top__grid {
  flex: 1 1 auto;
  min-width: 0;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s4);
}

@media (max-width: 1100px) {
  .top {
    flex-direction: column;
    align-items: flex-start;
  }

  .top__grid {
    width: 100%;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 700px) {
  .top__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.reasons,
.reasons li,
.warns li {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: var(--fs-xs);
  line-height: 1.6;
}

.reasons li {
  color: var(--fail);
}

.warns li {
  color: var(--warn);
}

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: var(--s3);
}

.source {
  max-height: 60vh;
  overflow: auto;
  padding: var(--s3);
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-1);
  font-size: var(--fs-xs);
  line-height: 1.7;
  color: var(--ink-2);
}

.skel {
  padding: var(--s5);
}
</style>

