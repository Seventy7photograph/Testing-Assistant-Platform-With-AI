<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";

import BackToTop from "@/components/BackToTop.vue";
import AssistantPanel from "@/components/AssistantPanel.vue";
import AssistantRail from "@/components/AssistantRail.vue";
import CommandPalette from "@/components/CommandPalette.vue";
import HelpDrawer from "@/components/HelpDrawer.vue";
import NoticeHost from "@/components/NoticeHost.vue";
import SideRail from "@/components/SideRail.vue";
import TopBar from "@/components/TopBar.vue";
import { useUiStore } from "@/stores/ui";
import { useWorkItemsStore } from "@/stores/workItems";
import { useProjectStore } from "@/stores/project";

/** 窄屏下导航轨是浮层：默认收起，避免盖住内容。 */
const NARROW = 1080;

const ui = useUiStore();
const workItems = useWorkItemsStore();
const projectStore = useProjectStore();
const paletteOpen = ref(false);
const assistantOpen = ref(false);

watch(
  () => projectStore.activeId,
  () => {
    assistantOpen.value = false;
  },
);

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
  workItems.start();
});

onUnmounted(() => {
  document.removeEventListener("keydown", onKeydown);
  window.removeEventListener("resize", syncRailToViewport);
  workItems.stop();
});
</script>

<template>
  <div class="shell">
    <a class="skip-link" href="#main-content">跳到主要内容</a>
    <SideRail />
    <div class="shell__main">
      <TopBar
        @open-palette="paletteOpen = true"
        @open-assistant="assistantOpen = true"
      />
      <main id="main-content" class="shell__content" tabindex="-1">
        <RouterView v-slot="{ Component, route: currentRoute }">
          <KeepAlive :include="['GenerateView', 'ReportWorkbenchView']" :max="4">
            <component
              :is="Component"
              :key="`${projectStore.activeId}:${currentRoute.meta.keepAlive ? String(currentRoute.name) : currentRoute.fullPath}`"
            />
          </KeepAlive>
        </RouterView>
      </main>
    </div>

    <CommandPalette :open="paletteOpen" @close="paletteOpen = false" />
    <AssistantRail :open="assistantOpen" @toggle="assistantOpen = !assistantOpen" />
    <AssistantPanel :open="assistantOpen" @close="assistantOpen = false" />
    <HelpDrawer />
    <NoticeHost />
    <BackToTop />
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  align-items: stretch;
  min-height: 100vh;
  padding-right: var(--assistant-rail-w);
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
  padding: var(--s5) var(--s5) calc(var(--s5) + 92px);
  max-width: var(--content-max);
  width: 100%;
}

.skip-link {
  position: fixed;
  z-index: 120;
  top: 8px;
  left: 50%;
  padding: 7px 12px;
  border: 1px solid var(--signal);
  border-radius: var(--radius);
  background: var(--rail-ink);
  color: var(--ice-0);
  font-size: var(--fs-sm);
  text-decoration: none;
  transform: translate(-50%, -160%);
}

.skip-link:focus {
  transform: translate(-50%, 0);
}

@media (max-width: 1080px) {
  .shell__content {
    padding: var(--s4) var(--s3);
  }
}

@media (max-width: 760px) {
  .shell {
    padding-right: 0;
  }

  .shell__content {
    padding-bottom: calc(104px + env(safe-area-inset-bottom));
  }
}
</style>

