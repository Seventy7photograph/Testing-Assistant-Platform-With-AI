<script setup lang="ts">
import AppIcon from "@/components/AppIcon.vue";

defineProps<{ open: boolean }>();
const emit = defineEmits<{ (e: "toggle"): void }>();
</script>

<template>
  <aside class="assistant-rail" aria-label="项目助手">
    <button
      type="button"
      class="assistant-rail__button"
      :class="{ 'assistant-rail__button--open': open }"
      :aria-expanded="open"
      :title="open ? '收起项目助手' : '打开项目助手'"
      @click="emit('toggle')"
    >
      <AppIcon name="sparkle" :size="18" />
      <span class="sr-only">助手</span>
    </button>
    <span class="assistant-rail__rule" />
    <span class="assistant-rail__word">助手</span>
    <span class="assistant-rail__dot" :data-open="open ? '1' : '0'" />
  </aside>
</template>

<style scoped>
.assistant-rail {
  position: fixed;
  z-index: 45;
  top: 0;
  right: 0;
  bottom: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  width: var(--assistant-rail-w);
  padding: 12px 0;
  background: var(--rail-ink);
  border-left: 1px solid var(--rail-line);
  color: var(--rail-muted);
}

.assistant-rail__button {
  display: grid;
  place-items: center;
  gap: 2px;
  width: 34px;
  height: 48px;
  border: 1px solid transparent;
  border-radius: 4px;
  background: transparent;
  color: var(--rail-muted);
  font-size: 9px;
  cursor: pointer;
  transition:
    color 160ms var(--ease),
    background-color 160ms var(--ease),
    border-color 160ms var(--ease);
}

.assistant-rail__button:hover,
.assistant-rail__button--open {
  border-color: color-mix(in srgb, var(--signal) 38%, transparent);
  background: color-mix(in srgb, var(--signal) 10%, transparent);
  color: var(--ice-0);
}

.assistant-rail__button:active {
  transform: translateY(1px);
}

.assistant-rail__rule {
  width: 1px;
  flex: 1 1 auto;
  margin: 14px 0;
  background: var(--rail-line);
}

.assistant-rail__word {
  writing-mode: vertical-rl;
  font-size: 11px;
  letter-spacing: 0.12em;
  color: var(--rail-muted);
}

.assistant-rail__dot {
  width: 6px;
  height: 6px;
  margin-top: 14px;
  border-radius: 50%;
  background: var(--rail-muted);
  transition: background-color 160ms var(--ease);
}

.assistant-rail__dot[data-open="1"] {
  background: var(--signal);
}

@media (max-width: 760px) {
  .assistant-rail {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .assistant-rail__button,
  .assistant-rail__dot {
    transition: none;
  }
}
</style>
