import { ref, shallowRef } from "vue";

import { ApiError } from "@/api";

export interface AsyncState<T> {
  data: ReturnType<typeof shallowRef<T | null>>;
  loading: ReturnType<typeof ref<boolean>>;
  error: ReturnType<typeof ref<string>>;
  code: ReturnType<typeof ref<string>>;
  run: (...args: never[]) => Promise<T | null>;
}

/**
 * 统一的异步状态：loading / error / code 三件套。
 * 错误必须带着可读的原因与机器码一起落地，界面才有东西可提示。
 */
export function useAsync<T>(task: (...args: never[]) => Promise<T>) {
  const data = shallowRef<T | null>(null);
  const loading = ref(false);
  const error = ref("");
  const code = ref("");

  async function run(...args: never[]): Promise<T | null> {
    loading.value = true;
    error.value = "";
    code.value = "";
    try {
      const result = await task(...args);
      data.value = result;
      return result;
    } catch (err) {
      if (err instanceof ApiError) {
        error.value = err.message;
        code.value = err.code;
      } else {
        error.value = (err as Error)?.message || "未知错误";
        code.value = "UNKNOWN";
      }
      return null;
    } finally {
      loading.value = false;
    }
  }

  return { data, loading, error, code, run };
}

/** 毫秒转可读耗时。用于"耗时 1.2s"这类刻度读数。 */
export function formatElapsed(ms: number): string {
  if (!ms || ms < 0) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60_000)}m${Math.round((ms % 60_000) / 1000)}s`;
}
