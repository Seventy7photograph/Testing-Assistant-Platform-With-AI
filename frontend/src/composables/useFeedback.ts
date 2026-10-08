import { ElMessageBox } from "element-plus";

import { useNoticeStore } from "@/stores/notice";

/**
 * 二次确认：覆盖性 / 破坏性操作前必须经过。
 * 文案要说明「后果」与「是否可撤销」，而不是只问一句"确定吗"。
 */
export async function confirmAction(options: {
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
}): Promise<boolean> {
  try {
    await ElMessageBox.confirm(options.message, options.title, {
      confirmButtonText: options.confirmText ?? "确认执行",
      cancelButtonText: options.cancelText ?? "取消",
      type: options.danger ? "warning" : "info",
      confirmButtonClass: options.danger ? "el-button--danger" : undefined,
      draggable: true,
      closeOnClickModal: false,
      customClass: "tap-confirm",
    });
    return true;
  } catch {
    return false;
  }
}

/** 组件里最常用的一组：提示 + 确认 + 错误归一化。 */
export function useFeedback() {
  const notice = useNoticeStore();
  return {
    notice,
    confirm: confirmAction,
    fail(title: string, err: unknown) {
      notice.error(title, (err as Error)?.message || "未知错误");
    },
  };
}
