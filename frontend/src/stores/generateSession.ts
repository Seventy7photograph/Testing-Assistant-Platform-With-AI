import { defineStore } from "pinia";
import { ref } from "vue";

import type { DocumentSummary, GenerateResult } from "@/api";
import { DEFAULT_METHODS } from "@/utils/labels";

export interface SessionFailure {
  message: string;
  code: string;
}

export type GeneratePhase = "idle" | "running" | "success" | "failed";

export const useGenerateSession = defineStore("generate-session", () => {
  const mode = ref<"text" | "upload">("text");
  const text = ref("");
  const title = ref("粘贴的需求文本");
  const docId = ref<string | null>(null);
  const docInfo = ref<DocumentSummary | null>(null);
  const uploading = ref(false);
  const methods = ref<string[]>([...DEFAULT_METHODS]);
  const maxItems = ref(8);
  const maxCases = ref(200);
  const initialisedFromServer = ref(false);
  const useLlm = ref(true);
  const useLlmInDesign = ref(false);
  const llmDesignMode = ref("scenario");
  const generating = ref(false);
  const result = ref<GenerateResult | null>(null);
  const failure = ref<SessionFailure | null>(null);
  const startedAt = ref<number | null>(null);
  const phase = ref<GeneratePhase>("idle");
  const lastCompletedSignature = ref<string | null>(null);
  const runToken = ref(0);

  function start() {
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
    return true;
  }

  function resetResult() {
    runToken.value += 1;
    result.value = null;
    failure.value = null;
    startedAt.value = null;
    phase.value = "idle";
    lastCompletedSignature.value = null;
  }

  return {
    mode,
    text,
    title,
    docId,
    docInfo,
    uploading,
    methods,
    maxItems,
    maxCases,
    initialisedFromServer,
    useLlm,
    useLlmInDesign,
    llmDesignMode,
    generating,
    result,
    failure,
    startedAt,
    phase,
    lastCompletedSignature,
    runToken,
    start,
    finish,
    resetResult,
  };
});
