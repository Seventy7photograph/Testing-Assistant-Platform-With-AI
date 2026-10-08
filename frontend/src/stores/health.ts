import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { api } from "@/api";
import type { HealthInfo, LLMConfigInfo } from "@/api";

/**
 * 平台运行状态：能力清单 + 大模型配置。
 * 侧栏脚注、顶部导航的运行芯片、各页的降级提示都读这里，避免重复请求。
 */
export const useHealthStore = defineStore("health", () => {
  const info = ref<HealthInfo | null>(null);
  const llmConfig = ref<LLMConfigInfo | null>(null);
  const loading = ref(false);
  const error = ref("");
  const loadedAt = ref(0);

  const reachable = computed(() => info.value !== null && !error.value);
  const llmReady = computed(() => info.value?.llm_available === true);

  const llmLabel = computed(() => {
    const current = info.value;
    if (!current) return "读取中…";
    const provider = (current.llm_provider || "").trim();
    const named = provider !== "" && provider.toLowerCase() !== "null";
    if (!current.llm_available) {
      return named ? `${provider} · 未启用` : "未配置引擎";
    }
    return named ? `${provider} · ${current.llm_model}` : current.llm_model || "已启用";
  });

  /** 降级原因：界面必须在发生的位置说明，而不是只留一句"未启用"。 */
  const degradedReason = computed(() => info.value?.llm_degraded_reason ?? "");

  const llmSourceLabel = computed(() =>
    llmConfig.value?.source === "runtime" ? "界面覆盖" : ".env 基线",
  );

  async function load(force = false) {
    if (!force && loadedAt.value && Date.now() - loadedAt.value < 15_000) return;
    loading.value = true;
    try {
      info.value = await api.health();
      error.value = "";
      loadedAt.value = Date.now();
    } catch (err) {
      error.value = (err as Error).message;
    } finally {
      loading.value = false;
    }
  }

  async function loadLlmConfig() {
    try {
      llmConfig.value = await api.llmConfig();
    } catch {
      /* 大模型配置读取失败不阻塞产品使用，页面内会再提示 */
    }
  }

  return {
    info,
    llmConfig,
    loading,
    error,
    reachable,
    llmReady,
    llmLabel,
    degradedReason,
    llmSourceLabel,
    load,
    loadLlmConfig,
  };
});

