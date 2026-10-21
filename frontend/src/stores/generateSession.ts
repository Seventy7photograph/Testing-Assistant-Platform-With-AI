import { defineStore } from "pinia";
import { ref } from "vue";

import type { DocumentSummary, GenerateResult } from "@/api";
import { DEFAULT_METHODS } from "@/utils/labels";

export interface SessionFailure {
  message: string;
  code: string;
}

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

  function start() {
    generating.value = true;
    startedAt.value = Date.now();
    failure.value = null;
  }

  function finish() {
    generating.value = false;
  }

  function resetResult() {
    result.value = null;
    failure.value = null;
    startedAt.value = null;
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
    start,
    finish,
    resetResult,
  };
});
