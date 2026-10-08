import { defineStore } from "pinia";
import { ref } from "vue";

export type NoticeKind = "success" | "error" | "warning" | "info";

export interface Notice {
  id: number;
  kind: NoticeKind;
  title: string;
  detail?: string;
  /** 可撤销的提示：给出一个"撤销/重试"动作。 */
  action?: { label: string; run: () => void };
}

let seq = 0;

/**
 * 浮层通知队列。成功 3 秒自动消失；失败与警告必须手动关闭 ——
 * 测试工程师最不能接受的就是"刚才那步到底成没成"。
 */
export const useNoticeStore = defineStore("notice", () => {
  const items = ref<Notice[]>([]);

  function push(kind: NoticeKind, title: string, detail?: string, action?: Notice["action"]) {
    const id = ++seq;
    items.value.push({ id, kind, title, detail, action });
    if (kind === "success" || kind === "info") {
      window.setTimeout(() => dismiss(id), kind === "success" ? 3200 : 6000);
    }
    return id;
  }

  function dismiss(id: number) {
    items.value = items.value.filter((item) => item.id !== id);
  }

  const success = (title: string, detail?: string) => push("success", title, detail);
  const error = (title: string, detail?: string, action?: Notice["action"]) =>
    push("error", title, detail, action);
  const warning = (title: string, detail?: string, action?: Notice["action"]) =>
    push("warning", title, detail, action);
  const info = (title: string, detail?: string, action?: Notice["action"]) =>
    push("info", title, detail, action);

  function clear() {
    items.value = [];
  }

  return { items, push, dismiss, success, error, warning, info, clear };
});
