import { defineStore } from "pinia";
import { ref, shallowRef } from "vue";

import type { Defect, ReportMetrics } from "@/api";

export interface ReportMeta {
  model: string;
  provider: string;
  elapsed: number;
  createdAt: string;
}

export type ReportPhase = "idle" | "running" | "success" | "failed";

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
  const phase = ref<ReportPhase>("idle");
  const lastCompletedSignature = ref<string | null>(null);
  const controller = shallowRef<AbortController | null>(null);
  const runToken = ref(0);

  function start() {
    controller.value?.abort();
    controller.value = new AbortController();
    runToken.value += 1;
    generating.value = true;
    startedAt.value = Date.now();
    failure.value = null;
    phase.value = "running";
    lastCompletedSignature.value = null;
    return runToken.value;
  }

  function finish(token: number, success = false, signature = "") {
    if (token !== runToken.value) return false;
    generating.value = false;
    phase.value = success ? "success" : failure.value ? "failed" : "idle";
    if (success) lastCompletedSignature.value = signature;
    controller.value = null;
    return true;
  }

  function cancel() {
    controller.value?.abort();
    controller.value = null;
    runToken.value += 1;
    generating.value = false;
    startedAt.value = null;
    phase.value = "idle";
  }

  function reset() {
    controller.value?.abort();
    controller.value = null;
    runToken.value += 1;
    generating.value = false;
    report.value = "";
    reportMeta.value = null;
    reportId.value = null;
    warnings.value = [];
    failure.value = null;
    liveMetrics.value = null;
    liveDefects.value = [];
    liveVersion.value = null;
    liveFormat.value = "empty";
    liveWarnings.value = [];
    startedAt.value = null;
    phase.value = "idle";
    lastCompletedSignature.value = null;
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
    phase,
    lastCompletedSignature,
    controller,
    runToken,
    start,
    finish,
    cancel,
    reset,
  };
});
