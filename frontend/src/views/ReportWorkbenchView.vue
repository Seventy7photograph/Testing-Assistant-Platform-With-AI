<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { api, saveBlob, streamAnalyze } from "@/api";
import type {
  Defect,
  ReportMetrics,
  ReportStatus,
  SampleDataset,
} from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorNote from "@/components/ErrorNote.vue";
import FieldHint from "@/components/FieldHint.vue";
import MarkdownBody from "@/components/MarkdownBody.vue";
import SectionCard from "@/components/SectionCard.vue";
import StatReadout from "@/components/StatReadout.vue";
import Tip from "@/components/Tip.vue";
import VerdictSeal from "@/components/VerdictSeal.vue";
import { useHealthStore } from "@/stores/health";
import { useNoticeStore } from "@/stores/notice";
import { formatDuration, formatPercent } from "@/utils/labels";

const router = useRouter();
const health = useHealthStore();
const notice = useNoticeStore();

const testData = ref("");
const instruction = ref("重点分析高优先级缺陷、版本风险，并给出回归建议。");
const model = ref("");
const useStream = ref(true);
const archive = ref(true);

const samples = ref<SampleDataset[]>([]);
const status = ref<ReportStatus | null>(null);

const liveMetrics = ref<ReportMetrics | null>(null);
const liveDefects = ref<Defect[]>([]);
const liveVersion = ref<string | null>(null);
const liveFormat = ref<"json" | "text" | "empty">("empty");
const liveWarnings = ref<string[]>([]);
const metricsLoading = ref(false);

const report = ref("");
const reportMeta = ref<{ model: string; provider: string; elapsed: number; createdAt: string } | null>(null);
const reportId = ref<string | null>(null);
const generating = ref(false);
const warnings = ref<string[]>([]);
const failure = ref<{ message: string; code: string } | null>(null);

const dataRevision = ref(0);
const metricsRevision = ref(-1);
let metricsTimer: number | undefined;
let controller: AbortController | null = null;
let lastPayload = "";

const PRESETS = [
  { label: "发版评估", text: "重点分析高优先级缺陷与本版本风险，给出是否可发版的判断依据。" },
  { label: "回归建议", text: "总结本轮失败用例的分布特征，给出下一轮回归的范围与优先级建议。" },
  { label: "缺陷复盘", text: "按模块归纳缺陷，指出缺陷密度最高的模块并分析可能的原因。" },
];

const stale = computed(() => liveMetrics.value !== null && metricsRevision.value !== dataRevision.value);

const formatNote = computed(() => {
  if (liveFormat.value === "empty") return { tone: "muted" as const, text: "等待送检数据。" };
  if (liveFormat.value === "json") {
    const version = liveVersion.value ? ` · 版本 ${liveVersion.value}` : "";
    return {
      tone: "pass" as const,
      text: `已识别结构化数据${version} · ${liveMetrics.value?.total ?? 0} 条用例`,
    };
  }
  return {
    tone: "warn" as const,
    text: "输入不是可识别的 JSON：无法计算确定性指标，将按原文交给模型分析。",
  };
});

const canGenerate = computed(() => testData.value.trim().length > 0 && !generating.value);

const llmNote = computed(() =>
  health.llmReady
    ? `生成阶段调用 ${health.llmLabel}；指标永远由服务端确定性计算，模型只做归纳与建议。`
    : "报告链路需要大模型才能生成正文。请在「大模型与阈值」中配置 API Key 后再试。",
);

const verdictReasons = computed(() => liveMetrics.value?.verdict_reasons ?? []);

const openP0 = computed(() => liveMetrics.value?.open_p0 ?? 0);

onMounted(async () => {
  try {
    const [sampleList, reportStatus] = await Promise.all([api.reportSamples(), api.reportStatus()]);
    samples.value = sampleList;
    status.value = reportStatus;
  } catch (err) {
    notice.error("报告模块状态没有取到", (err as Error).message);
  }
});

onBeforeUnmount(() => {
  window.clearTimeout(metricsTimer);
  controller?.abort();
});

watch(testData, () => {
  dataRevision.value += 1;
  window.clearTimeout(metricsTimer);
  metricsTimer = window.setTimeout(() => void refreshMetrics(), 320);
});

async function refreshMetrics(): Promise<void> {
  const payload = testData.value;
  if (payload === lastPayload) return;
  lastPayload = payload;
  const revision = dataRevision.value;

  if (!payload.trim()) {
    liveMetrics.value = null;
    liveDefects.value = [];
    liveVersion.value = null;
    liveFormat.value = "empty";
    liveWarnings.value = [];
    metricsRevision.value = revision;
    return;
  }

  metricsLoading.value = true;
  try {
    const result = await api.reportMetrics(payload);
    if (payload !== testData.value) return;
    liveMetrics.value = result.metrics;
    liveDefects.value = result.defects;
    liveVersion.value = result.version;
    liveFormat.value = result.source_format;
    liveWarnings.value = result.warnings;
    metricsRevision.value = revision;
  } catch (err) {
    liveWarnings.value = [(err as Error).message];
  } finally {
    metricsLoading.value = false;
  }
}

function applySample(id: string): void {
  const sample = samples.value.find((item) => item.id === id);
  if (!sample) return;
  testData.value = sample.content;
  notice.success(`已载入示例「${sample.name}」`, sample.description);
}

function clearAll(): void {
  testData.value = "";
  report.value = "";
  reportMeta.value = null;
  reportId.value = null;
  warnings.value = [];
  liveMetrics.value = null;
  liveDefects.value = [];
  failure.value = null;
  lastPayload = "";
  metricsRevision.value = -1;
}

function stop(): void {
  controller?.abort();
  controller = null;
  generating.value = false;
  notice.warning("已停止生成", "已生成的部分会保留在下方正文里。");
}

async function generate(): Promise<void> {
  if (!canGenerate.value) return;
  if (!health.llmReady) {
    notice.error("报告链路需要大模型", "当前未配置 API Key，请先前往「大模型与阈值」配置。", {
      label: "去配置",
      run: () => void router.push("/settings"),
    });
    return;
  }

  generating.value = true;
  report.value = "";
  reportMeta.value = null;
  reportId.value = null;
  warnings.value = [];
  failure.value = null;

  const payload = {
    test_data: testData.value,
    instruction: instruction.value,
    model: model.value.trim() || null,
    save: archive.value,
  };

  if (!useStream.value) {
    try {
      const result = await api.analyzeReport(payload);
      report.value = result.report;
      reportId.value = result.id;
      warnings.value = result.warnings;
      reportMeta.value = {
        model: result.model,
        provider: result.provider,
        elapsed: result.elapsed_ms,
        createdAt: result.created_at,
      };
      if (result.metrics) liveMetrics.value = result.metrics;
      notice.success("报告已生成", result.id ? "已写入本地存档。" : "未归档。");
    } catch (err) {
      failure.value = { message: (err as Error).message, code: "" };
    } finally {
      generating.value = false;
    }
    return;
  }

  controller = new AbortController();
  let buffer = "";
  await streamAnalyze(
    payload,
    {
      onMeta: (meta) => {
        reportMeta.value = {
          model: String(meta.model ?? ""),
          provider: String(meta.provider ?? ""),
          elapsed: 0,
          createdAt: String(meta.created_at ?? ""),
        };
        const list = meta.warnings;
        if (Array.isArray(list)) warnings.value = list.map(String);
      },
      onMetrics: (metrics) => {
        liveMetrics.value = metrics;
      },
      onDelta: (text) => {
        buffer += text;
        report.value = buffer;
      },
      onDone: (info) => {
        reportMeta.value = {
          model: String(info.model ?? ""),
          provider: String(info.provider ?? ""),
          elapsed: Number(info.elapsed_ms ?? 0),
          createdAt: String(info.created_at ?? ""),
        };
        reportId.value = info.id ? String(info.id) : null;
        if (Array.isArray(info.warnings)) warnings.value = info.warnings.map(String);
      },
      onError: (detail) => {
        failure.value = { message: detail, code: "" };
      },
    },
    controller.signal,
  );
  controller = null;
  generating.value = false;
}

async function download(format: string): Promise<void> {
  if (!reportId.value) return;
  try {
    const file = await api.exportReport(reportId.value, format);
    saveBlob(file.blob, file.filename || `测试报告.${format}`);
    notice.success("导出完成", file.filename || undefined);
  } catch (err) {
    notice.error("导出失败", (err as Error).message);
  }
}

function printReport(): void {
  window.print();
}

const verdictPartial = computed(() => liveMetrics.value);
</script>

<template>
  <div class="bench">
    <!-- 送检 -->
    <div class="bench__intake">
      <SectionCard title="送检" sub="测试执行数据 → 确定性指标 → AI 报告" icon="chart">
        <div class="form">
          <div class="field">
            <span class="field__label">示例数据</span>
            <div class="samples">
              <button
                v-for="sample in samples"
                :key="sample.id"
                type="button"
                class="sample"
                :title="sample.description"
                @click="applySample(sample.id)"
              >
                <AppIcon name="layers" :size="13" />
                {{ sample.name }}
              </button>
              <span v-if="!samples.length" class="muted">加载中…</span>
            </div>
            <FieldHint>点击载入一套可跑通的样例数据，用来熟悉指标口径与报告结构。</FieldHint>
          </div>

          <label class="field">
            <span class="field__label">
              执行数据
              <Tip text="优先识别 JSON（含用例状态与缺陷清单）；非 JSON 时按原文分析，指标不可计算。" />
            </span>
            <el-input
              v-model="testData"
              type="textarea"
              :rows="10"
              resize="vertical"
              placeholder="粘贴 JSON 执行结果或测试记录文本"
            />
            <p class="format" :data-tone="formatNote.tone">
              <span class="format__dot" aria-hidden="true" />
              {{ formatNote.text }}
              <span v-if="stale" class="format__stale">· 输入已变动</span>
            </p>
          </label>

          <label class="field">
            <span class="field__label">分析要求（可选）</span>
            <el-input
              v-model="instruction"
              type="textarea"
              :rows="3"
              resize="vertical"
              placeholder="例如：重点分析高优先级缺陷与版本风险"
            />
            <div class="presets">
              <button v-for="preset in PRESETS" :key="preset.label" type="button" class="preset" @click="instruction = preset.text">
                {{ preset.label }}
              </button>
            </div>
          </label>

          <label class="field">
            <span class="field__label">
              模型覆盖（可选）
              <Tip text="留空使用「大模型与阈值」中的默认模型；仅在需要对比不同模型时填写。" />
            </span>
            <el-input v-model="model" placeholder="留空 = 使用默认模型" />
          </label>

          <div class="switches">
            <label class="switch"><el-switch v-model="useStream" /><span>流式输出</span></label>
            <label class="switch"><el-switch v-model="archive" /><span>写入存档</span></label>
          </div>
          <FieldHint :tone="health.llmReady ? 'muted' : 'warn'">{{ llmNote }}</FieldHint>

          <hr class="rule" />

          <div class="actions">
            <el-button v-if="!generating" type="primary" :disabled="!canGenerate" @click="generate">
              <AppIcon name="sparkle" :size="15" /> 生成报告
            </el-button>
            <el-button v-else type="danger" plain @click="stop">
              <AppIcon name="stop" :size="14" /> 停止
            </el-button>
            <el-button :disabled="generating" @click="clearAll">清空</el-button>
          </div>
        </div>
      </SectionCard>

      <SectionCard v-if="status" title="判定口径" sub="阈值可在「大模型与阈值」调整" icon="target" sunk>
        <ul class="crit">
          <li>
            <span>失败率上限</span>
            <span class="mono">{{ formatPercent(status.thresholds.fail_rate) }}</span>
          </li>
          <li>
            <span>阻塞率上限</span>
            <span class="mono">{{ formatPercent(status.thresholds.blocked_rate) }}</span>
          </li>
          <li>
            <span>执行率下限</span>
            <span class="mono">{{ formatPercent(status.thresholds.execution_floor) }}</span>
          </li>
          <li>
            <span>趋势判读线</span>
            <span class="mono">{{ formatPercent(status.thresholds.pass_line) }}</span>
          </li>
        </ul>
        <FieldHint>未关闭的 P0 直接判「不建议发版」；未标注状态的缺陷一律按未关闭计入。</FieldHint>
      </SectionCard>
    </div>

    <!-- 读数 -->
    <div class="bench__out">
      <ErrorNote
        v-if="failure"
        title="本次生成没有完成"
        :message="failure.message"
        recovery="确认已配置可用的大模型 API Key，或改用非流式重试。"
        @retry="generate"
      />

      <div class="grid grid--2">
        <SectionCard title="读数" :sub="liveVersion ? `版本 ${liveVersion}` : '实时计算，随输入更新'" icon="gauge">
          <div class="readouts">
            <StatReadout label="用例总数" :value="liveMetrics?.total ?? null" :pending="metricsLoading" hint="识别到的用例条目数" />
            <StatReadout
              label="通过率"
              :value="liveMetrics ? formatPercent(liveMetrics.pass_rate) : null"
              :pending="metricsLoading"
              :tone="liveMetrics && liveMetrics.pass_rate >= 0.95 ? 'pass' : 'warn'"
              hint="已通过 / 已执行"
            />
            <StatReadout
              label="失败"
              :value="liveMetrics?.failed ?? null"
              :pending="metricsLoading"
              :tone="liveMetrics && liveMetrics.failed > 0 ? 'fail' : 'default'"
              hint="本轮失败用例数"
            />
            <StatReadout
              label="阻塞"
              :value="liveMetrics?.blocked ?? null"
              :pending="metricsLoading"
              :tone="liveMetrics && liveMetrics.blocked > 0 ? 'warn' : 'default'"
              hint="因环境/依赖导致无法执行的用例数"
            />
            <StatReadout
              label="执行率"
              :value="liveMetrics ? formatPercent(liveMetrics.execution_rate) : null"
              :pending="metricsLoading"
              hint="已执行 / 用例总数"
            />
            <StatReadout
              label="未关闭缺陷"
              :value="liveMetrics?.defects_open ?? null"
              :pending="metricsLoading"
              :tone="openP0 > 0 ? 'fail' : 'default'"
              hint="含未标注状态的缺陷（宁严勿松）"
            />
          </div>
        </SectionCard>

        <SectionCard title="发版判定" sub="由服务端按阈值确定性计算" icon="seal">
          <div class="verdict">
            <VerdictSeal
              :verdict="verdictPartial?.verdict ?? 'unknown'"
              :label="verdictPartial?.verdict_label ?? '无法判定'"
              :pending="metricsLoading"
            />
            <div class="verdict__body">
              <p v-if="!verdictPartial" class="muted">输入可识别的结构化数据后，这里给出发版判定。</p>
              <template v-else>
                <p class="verdict__label">{{ verdictPartial.verdict_label }}</p>
                <ul v-if="verdictReasons.length" class="verdict__reasons">
                  <li v-for="reason in verdictReasons" :key="reason">
                    <AppIcon name="alert" :size="13" /><span>{{ reason }}</span>
                  </li>
                </ul>
                <p v-else class="muted">未触发任何拦截条件。</p>
              </template>
            </div>
          </div>

          <hr class="rule" />
          <div class="mini">
            <span class="chip chip--ghost">P0 未关闭 <b class="mono">{{ liveMetrics?.open_p0 ?? 0 }}</b></span>
            <span class="chip chip--ghost">P1 未关闭 <b class="mono">{{ liveMetrics?.open_p1 ?? 0 }}</b></span>
            <span class="chip chip--ghost">有效通过率 <b class="mono">{{ liveMetrics ? formatPercent(liveMetrics.effective_pass_rate) : "—" }}</b></span>
          </div>
        </SectionCard>
      </div>

      <SectionCard
        v-if="liveDefects.length"
        title="缺陷清单"
        :sub="`${liveDefects.length} 条 · ${liveDefects.filter((d) => d.status === 'open').length} 条未关闭`"
        icon="bug"
        flush
      >
        <el-table :data="liveDefects" size="small" :border="false" max-height="320">
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

      <SectionCard
        v-if="warnings.length || liveWarnings.length"
        title="提示"
        sub="这些说明会影响结论的可信度，请先核对"
        icon="alert"
      >
        <ul class="warns">
          <li v-for="item in [...warnings, ...liveWarnings]" :key="item">
            <AppIcon name="alert" :size="13" /><span>{{ item }}</span>
          </li>
        </ul>
      </SectionCard>

      <SectionCard
        v-if="report || generating"
        :title="reportMeta ? `${reportMeta.model} · ${formatDuration(reportMeta.elapsed)}` : '正在生成报告'"
        :sub="reportId ? `已归档 · ${reportId.slice(0, 12)}` : generating ? '流式输出中…' : '未归档'"
        icon="doc"
      >
        <template #actions>
          <template v-if="reportId">
            <el-button size="small" @click="download('md')">Markdown</el-button>
            <el-button size="small" @click="download('html')">HTML</el-button>
            <el-button size="small" @click="download('docx')">Word</el-button>
            <el-button size="small" @click="download('json')">JSON</el-button>
            <el-button size="small" @click="printReport"><AppIcon name="file" :size="14" /> 打印</el-button>
            <el-button size="small" type="primary" plain @click="router.push(`/report/archive/${reportId}`)">
              报告详情 <AppIcon name="chevronRight" :size="14" />
            </el-button>
          </template>
        </template>
        <MarkdownBody :source="report" :streaming="generating" />
      </SectionCard>

      <SectionCard v-else-if="!failure" title="还没有报告" icon="doc">
        <EmptyState
          icon="chart"
          title="载入示例数据，或粘贴执行结果"
          reason="平台先确定性算出通过率、执行率、缺陷分布与发版判定，再让模型归纳风险与建议；模型不会重算任何数字。"
          action-label="载入示例数据"
          @action="samples.length ? applySample(samples[0].id) : undefined"
        />
      </SectionCard>
    </div>
  </div>
</template>

<style scoped>
.bench {
  display: grid;
  grid-template-columns: minmax(320px, 396px) minmax(0, 1fr);
  align-items: start;
  gap: var(--gap-grid);
}

.bench__intake {
  position: sticky;
  top: calc(var(--topbar-h) + var(--s4));
  display: flex;
  flex-direction: column;
  gap: var(--gap-stack);
}

.bench__out {
  display: flex;
  flex-direction: column;
  gap: var(--gap-stack);
  min-width: 0;
}

@media (max-width: 1080px) {
  .bench {
    grid-template-columns: minmax(0, 1fr);
  }

  .bench__intake {
    position: static;
  }
}

.form {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field__label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: var(--fs-xs);
  font-weight: 600;
  letter-spacing: 0.03em;
  color: var(--ink-2);
}

.samples {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.sample,
.preset {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius-pill);
  background: var(--ice-1);
  color: var(--ink-2);
  font: inherit;
  font-size: var(--fs-xs);
  cursor: pointer;
  transition: border-color var(--dur-fast) var(--ease), background-color var(--dur-fast) var(--ease);
}

.sample:hover,
.preset:hover {
  border-color: var(--glacier-tint);
  background: var(--glacier-wash);
  color: var(--glacier-deep);
}

.presets {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.format {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-xs);
  color: var(--ink-3);
}

.format__dot {
  width: 6px;
  height: 6px;
  border-radius: 2px;
  background: var(--ice-5);
}

.format[data-tone="pass"] {
  color: var(--pass);
}

.format[data-tone="pass"] .format__dot {
  background: var(--pass);
}

.format[data-tone="warn"] {
  color: var(--warn);
}

.format[data-tone="warn"] .format__dot {
  background: var(--warn);
}

.format__stale {
  color: var(--ink-3);
}

.switches {
  display: flex;
  gap: var(--s4);
}

.switch {
  display: inline-flex;
  align-items: center;
  gap: var(--s2);
  font-size: var(--fs-sm);
  color: var(--ink-2);
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.readouts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s4);
}

@media (max-width: 700px) {
  .readouts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.verdict {
  display: flex;
  align-items: center;
  gap: var(--s5);
}

.verdict__body {
  min-width: 0;
}

.verdict__label {
  font-size: var(--fs-lg);
  font-weight: 600;
  letter-spacing: -0.01em;
}

.verdict__reasons {
  list-style: none;
  margin: var(--s2) 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.verdict__reasons li {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: var(--fs-xs);
  line-height: 1.6;
  color: var(--fail);
}

.mini {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: var(--s3);
}

.mini b {
  font-weight: 600;
  color: var(--ink-1);
}

.warns {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.warns li {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: var(--fs-xs);
  line-height: 1.6;
  color: var(--warn);
}

.crit {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.crit li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--fs-sm);
  color: var(--ink-2);
}

.crit li .mono {
  color: var(--ink-1);
}
</style>


