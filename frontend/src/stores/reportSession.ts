import { defineStore } from "pinia";
import { ref } from "vue";

import type { Defect, ReportMetrics } from "@/api";

export interface ReportMeta {
  model: string;
  provider: string;
  elapsed: number;
  createdAt: string;
}

export const useReportSession = defineStore("report-session", () => {
  const testData = ref("");
  const instruction = ref("重点分析高优先级缺陷、版本风险，并给出回归建议。");
  const model = ref("");
  const useStream = ref(true);
  const archive = ref(true);
  const generating = ref(false);
  const report = ref("");
  const reportMeta = ref<ReportMeta | null>(null);
  const reportId = ref<string | null>(null);
  const warnings = ref<string[]>([]);
  const failure = ref<{ message: string; code: string } | null>(null);
  const liveMetrics = ref<ReportMetrics | null>(null);
  const liveDefects = ref<Defect[]>([]);
  const liveVersion = ref<string | null>(null);
  const liveFormat = ref<"json" | "text" | "empty">("empty");
  const liveWarnings = ref<string[]>([]);
  const startedAt = ref<number | null>(null);

  function start() {
    generating.value = true;
    startedAt.value = Date.now();
    failure.value = null;
  }

  function finish() {
    generating.value = false;
  }

  return {
    testData,
    instruction,
    model,
    useStream,
    archive,
    generating,
    report,
    reportMeta,
    reportId,
    warnings,
    failure,
    liveMetrics,
    liveDefects,
    liveVersion,
    liveFormat,
    liveWarnings,
    startedAt,
    start,
    finish,
  };
});
