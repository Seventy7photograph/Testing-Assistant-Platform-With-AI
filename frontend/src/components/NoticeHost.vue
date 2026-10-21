<script setup lang="ts">
import AppIcon from "@/components/AppIcon.vue";
import { useNoticeStore, type NoticeKind } from "@/stores/notice";

const notice = useNoticeStore();

const icon: Record<NoticeKind, string> = {
  success: "check",
  error: "alert",
  warning: "alert",
  info: "info",
};
</script>

<template>
  <Teleport to="body">
    <div class="host" role="status" aria-live="polite">
      <TransitionGroup name="notice">
        <div v-for="item in notice.items" :key="item.id" class="note" :data-kind="item.kind">
          <span class="note__icon"><AppIcon :name="icon[item.kind]" :size="17" /></span>
          <div class="note__body">
            <p class="note__title">{{ item.title }}</p>
            <p v-if="item.detail" class="note__detail">{{ item.detail }}</p>
            <button
              v-if="item.action"
              type="button"
              class="note__action"
              @click="item.action.run(); notice.dismiss(item.id)"
            >
              {{ item.action.label }}
            </button>
          </div>
          <button
            type="button"
            class="note__close"
            title="关闭提示"
            @click="notice.dismiss(item.id)"
          >
            <AppIcon name="x" :size="14" />
            <span class="sr-only">关闭</span>
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.host {
  position: fixed;
  right: var(--s5);
  bottom: calc(var(--s5) + 136px + env(safe-area-inset-bottom));
  z-index: 90;
  display: flex;
  flex-direction: column-reverse;
  gap: var(--s2);
  width: min(380px, calc(100vw - 32px));
  pointer-events: none;
}

.note {
  pointer-events: auto;
  display: flex;
  align-items: flex-start;
  gap: var(--s3);
  padding: var(--s3) var(--s3) var(--s3) var(--s4);
  background: var(--ice-0);
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  box-shadow: var(--shadow-overlay);
  animation: drift-in var(--dur) var(--ease) both;
}

.note__icon {
  display: grid;
  place-items: center;
  flex: none;
  width: 26px;
  height: 26px;
  border-radius: var(--radius-sm);
  background: var(--ice-2);
  color: var(--ink-2);
}

.note[data-kind="success"] .note__icon {
  background: var(--pass-wash);
  color: var(--pass);
}

.note[data-kind="error"] .note__icon {
  background: var(--fail-wash);
  color: var(--fail);
}

.note[data-kind="warning"] .note__icon {
  background: var(--warn-wash);
  color: var(--warn);
}

.note[data-kind="info"] .note__icon {
  background: var(--info-wash);
  color: var(--info);
}

.note__body {
  flex: 1 1 auto;
  min-width: 0;
}

.note__title {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--ink-1);
  line-height: 1.45;
}

.note__detail {
  margin-top: 2px;
  font-size: var(--fs-xs);
  line-height: 1.6;
  color: var(--ink-2);
  word-break: break-word;
  max-height: 8.4em;
  overflow: auto;
}

.note__action {
  margin-top: 6px;
  padding: 3px 10px;
  border: 1px solid var(--glacier-tint);
  border-radius: var(--radius-pill);
  background: var(--glacier-wash);
  color: var(--glacier-deep);
  font: inherit;
  font-size: var(--fs-xs);
  font-weight: 500;
  cursor: pointer;
}

.note__action:hover {
  background: var(--glacier-tint);
}

.note__close {
  flex: none;
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
}

.note__close:hover {
  background: var(--ice-2);
  color: var(--ink-1);
}

.notice-enter-active,
.notice-leave-active {
  transition: opacity var(--dur) var(--ease), transform var(--dur) var(--ease);
}

.notice-enter-from,
.notice-leave-to {
  opacity: 0;
  transform: translateY(10px) scale(0.99);
}

.notice-move {
  transition: transform var(--dur) var(--ease);
}

@media (max-width: 640px) {
  .host {
    right: var(--s3);
    left: var(--s3);
    bottom: calc(var(--s3) + 136px + env(safe-area-inset-bottom));
    width: auto;
  }
}
</style>
