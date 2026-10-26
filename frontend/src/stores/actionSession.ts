import { defineStore } from "pinia";
import { ref } from "vue";

interface ActionState {
  detail: string;
  startedAt: number;
}

/**
 * 跨路由的轻量异步动作会话。
 *
 * 页面可以卸载，但上传、解析、模型测试等请求仍会继续。把运行状态放在 Pinia 里，
 * 返回页面后仍能显示“处理中”，同时阻止同一动作被重复提交。
 */
export const useActionSession = defineStore("action-session", () => {
  const running = ref<Record<string, ActionState>>({});

  function begin(key: string, detail = ""): boolean {
    if (running.value[key]) return false;
    running.value = {
      ...running.value,
      [key]: { detail, startedAt: Date.now() },
    };
    return true;
  }

  function end(key: string): void {
    if (!running.value[key]) return;
    const next = { ...running.value };
    delete next[key];
    running.value = next;
  }

  function isRunning(key: string): boolean {
    return Boolean(running.value[key]);
  }

  function detail(key: string): string {
    return running.value[key]?.detail ?? "";
  }

  return { running, begin, end, isRunning, detail };
});
