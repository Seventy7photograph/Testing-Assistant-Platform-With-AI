<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";

import CommandPalette from "@/components/CommandPalette.vue";
import HelpDrawer from "@/components/HelpDrawer.vue";
import NoticeHost from "@/components/NoticeHost.vue";
import SideRail from "@/components/SideRail.vue";
import TopBar from "@/components/TopBar.vue";
import { useUiStore } from "@/stores/ui";

/** 窄屏下导航轨是浮层：默认收起，避免盖住内容。 */
const NARROW = 1080;

const ui = useUiStore();
const paletteOpen = ref(false);

function syncRailToViewport() {
  if (window.innerWidth <= NARROW) ui.railCollapsed = true;
}

function onKeydown(event: KeyboardEvent) {
  const meta = event.ctrlKey || event.metaKey;
  if (meta && event.key.toLowerCase() === "k") {
    event.preventDefault();
    paletteOpen.value = true;
    return;
  }
  if (event.key === "/" && !isTyping(event.target)) {
    event.preventDefault();
    paletteOpen.value = true;
  }
}

function isTyping(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  if (!element) return false;
  const tag = element.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || element.isContentEditable;
}

onMounted(() => {
  syncRailToViewport();
  document.addEventListener("keydown", onKeydown);
  window.addEventListener("resize", syncRailToViewport);
});

onUnmounted(() => {
  document.removeEventListener("keydown", onKeydown);
  window.removeEventListener("resize", syncRailToViewport);
});
</script>

<template>
  <div class="shell">
    <SideRail />
    <div class="shell__main">
      <TopBar @open-palette="paletteOpen = true" />
      <main class="shell__content">
        <RouterView v-slot="{ Component }">
          <Transition name="route-fade" mode="out-in">
            <component :is="Component" />
          </Transition>
        </RouterView>
      </main>
    </div>

    <CommandPalette :open="paletteOpen" @close="paletteOpen = false" />
    <HelpDrawer />
    <NoticeHost />
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  align-items: stretch;
  min-height: 100vh;
}

.shell__main {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.shell__content {
  position: relative;
  flex: 1 1 auto;
  padding: var(--s5);
  max-width: var(--content-max);
  width: 100%;
}

@media (max-width: 1080px) {
  .shell__content {
    padding: var(--s4) var(--s3);
  }
}
</style>

