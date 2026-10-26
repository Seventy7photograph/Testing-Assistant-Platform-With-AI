import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { api } from "@/api";
import type { WorkItem, WorkItemSummary } from "@/api";
import { useNoticeStore } from "@/stores/notice";

const POLL_MS = 30_000;

export const useWorkItemsStore = defineStore("work-items", () => {
  const summary = ref<WorkItemSummary | null>(null);
  const due = ref<WorkItem[]>([]);
  const loading = ref(false);
  const error = ref("");
  const started = ref(false);
  let timer: number | null = null;

  const attention = computed(
    () => (summary.value?.overdue ?? 0) + (summary.value?.today ?? 0),
  );

  async function refreshSummary(quiet = true) {
    if (!quiet) loading.value = true;
    try {
      summary.value = await api.workItemSummary();
      error.value = "";
      return summary.value;
    } catch (err) {
      error.value = (err as Error).message;
      return null;
    } finally {
      loading.value = false;
    }
  }

  async function pollReminders(notify = true) {
    try {
      const items = await api.dueWorkItemReminders();
      due.value = items;
      if (items.length && notify) {
        const notice = useNoticeStore();
        for (const item of items.slice(0, 3)) {
          notice.warning(
            `事项提醒：${item.title}`,
            item.due_at ? `截止 ${formatLocal(item.due_at)}` : "已到提醒时间",
          );
        }
        if (
          typeof Notification !== "undefined" &&
          Notification.permission === "granted"
        ) {
          for (const item of items.slice(0, 3)) {
            new Notification("测试工程师助手 · 事项提醒", { body: item.title });
          }
        }
        await api.ackWorkItemReminders(items.map((item) => item.work_item_id));
        due.value = [];
      }
      await refreshSummary();
      return items;
    } catch {
      return [];
    }
  }

  function start() {
    if (started.value) return;
    started.value = true;
    void refreshSummary();
    void pollReminders();
    timer = window.setInterval(() => void pollReminders(), POLL_MS);
  }

  function stop() {
    started.value = false;
    if (timer !== null) window.clearInterval(timer);
    timer = null;
  }

  return {
    summary,
    due,
    loading,
    error,
    started,
    attention,
    refreshSummary,
    pollReminders,
    start,
    stop,
  };
});

function formatLocal(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}
