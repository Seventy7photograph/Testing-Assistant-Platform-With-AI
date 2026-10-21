<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";

import AppIcon from "@/components/AppIcon.vue";

const visible = ref(false);
const THRESHOLD = 480;

function onScroll() {
  visible.value = window.scrollY > THRESHOLD;
}

function toTop() {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  window.scrollTo({ top: 0, behavior: reduced ? "auto" : "smooth" });
}

onMounted(() => {
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });
});

onUnmounted(() => window.removeEventListener("scroll", onScroll));
</script>

<template>
  <Transition name="backtop">
    <button
      v-if="visible"
      type="button"
      class="backtop"
      title="返回顶部"
      aria-label="返回顶部"
      @click="toTop"
    >
      <AppIcon name="chevronDown" :size="18" />
    </button>
  </Transition>
</template>

<style scoped>
.backtop {
  position: fixed;
  right: var(--s5);
  bottom: calc(var(--s5) + 72px + env(safe-area-inset-bottom));
  z-index: 55;
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border: 1px solid var(--ice-3);
  border-radius: 50%;
  background: color-mix(in srgb, var(--ice-0) 92%, transparent);
  box-shadow: var(--shadow-overlay);
  color: var(--ink-2);
  cursor: pointer;
  backdrop-filter: blur(12px);
}

.backtop svg {
  transform: rotate(180deg);
}

.backtop:hover,
.backtop:focus-visible {
  border-color: var(--glacier);
  color: var(--glacier-deep);
  outline: none;
}

.backtop-enter-active,
.backtop-leave-active {
  transition: opacity var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);
}

.backtop-enter-from,
.backtop-leave-to {
  opacity: 0;
  transform: translateY(8px) scale(0.92);
}

@media (max-width: 1080px) {
  .backtop {
    right: var(--s3);
    bottom: calc(var(--s3) + 72px + env(safe-area-inset-bottom));
  }
}

@media (prefers-reduced-motion: reduce) {
  .backtop-enter-active,
  .backtop-leave-active {
    transition: none;
  }
}
</style>
