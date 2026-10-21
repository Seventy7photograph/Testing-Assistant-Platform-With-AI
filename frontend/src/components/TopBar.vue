<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import AppIcon from "@/components/AppIcon.vue";
import { useHealthStore } from "@/stores/health";
import { useUiStore, type Density } from "@/stores/ui";

const emit = defineEmits<{ (e: "open-palette"): void }>();

const route = useRoute();
const router = useRouter();
const ui = useUiStore();
const health = useHealthStore();

const title = computed(() => String(route.meta.title ?? ""));
const hint = computed(() => String(route.meta.hint ?? ""));
const domainLabel = computed(() => {
  const map: Record<string, string> = {
    case: "用例生成",
    report: "测试报告",
    platform: "平台",
  };
  return map[String(route.meta.domain ?? "platform")] ?? "平台";
});
const parentPath = computed(() => String(route.meta.parentPath ?? ""));
const parentTitle = computed(() => String(route.meta.parentTitle ?? ""));

const densityMenuOpen = ref(false);
const densityOptions: { value: Density; label: string; hint: string }[] = [
  { value: "cozy", label: "标准", hint: "默认节奏，日常使用" },
  { value: "compact", label: "紧凑", hint: "一屏看更多字段" },
  { value: "relaxed", label: "宽松", hint: "投屏与演示" },
];

function closeDensity() {
  densityMenuOpen.value = false;
}

function onDocumentClick(event: MouseEvent) {
  const target = event.target as HTMLElement | null;
  if (!target?.closest("[data-density-root]")) closeDensity();
}

onMounted(() => document.addEventListener("click", onDocumentClick));
onUnmounted(() => document.removeEventListener("click", onDocumentClick));
</script>

<template>
  <header class="bar">
    <button
      type="button"
      class="bar__toggle"
      :title="ui.railCollapsed ? '展开侧边栏' : '收起侧边栏'"
      :aria-expanded="!ui.railCollapsed"
      @click="ui.toggleRail()"
    >
      <AppIcon name="panel" :size="18" />
      <span class="sr-only">切换侧边栏</span>
    </button>

    <div class="bar__id">
      <nav class="bar__crumbs mono" aria-label="面包屑">
        <button v-if="parentPath" type="button" class="bar__parent" @click="router.push(parentPath)">
          {{ parentTitle }}
        </button>
        <AppIcon v-if="parentPath" name="chevronRight" :size="10" class="bar__crumb-sep" />
        <span class="bar__crumb-current">{{ parentPath ? title : domainLabel }}</span>
      </nav>
      <h1 class="bar__title" :title="hint">
        {{ title }}
        <span v-if="hint" class="bar__hint">{{ hint }}</span>
      </h1>
    </div>

    <div class="spacer" />

    <button
      type="button"
      class="palette"
      title="快速跳转（Ctrl / ⌘ + K）"
      @click="emit('open-palette')"
    >
      <AppIcon name="search" :size="16" />
      <span class="palette__text">跳转到…</span>
      <kbd class="palette__kbd mono">Ctrl K</kbd>
    </button>

    <div class="bar__group" data-density-root>
      <button
        type="button"
        class="icon-btn"
        :title="`显示密度：${ui.density}`"
        :aria-expanded="densityMenuOpen"
        @click.stop="densityMenuOpen = !densityMenuOpen"
      >
        <AppIcon name="layers" :size="17" />
        <span class="sr-only">显示密度</span>
      </button>
      <div v-if="densityMenuOpen" class="menu" role="menu">
        <p class="menu__caption">显示密度</p>
        <button
          v-for="option in densityOptions"
          :key="option.value"
          type="button"
          role="menuitemradio"
          :aria-checked="ui.density === option.value"
          class="menu__item"
          :class="{ 'menu__item--on': ui.density === option.value }"
          @click="ui.setDensity(option.value); closeDensity()"
        >
          <span class="menu__label">{{ option.label }}</span>
          <span class="menu__hint">{{ option.hint }}</span>
          <AppIcon v-if="ui.density === option.value" name="check" :size="15" />
        </button>
      </div>
    </div>

    <button
      type="button"
      class="icon-btn"
      :title="
        ui.theme === 'dark'
          ? '切换到冰川蓝白（浅色）'
          : '切换到深色护眼模式'
      "
      :aria-pressed="ui.theme === 'dark'"
      @click="ui.toggleTheme()"
    >
      <Transition name="theme-swap" mode="out-in">
        <AppIcon
          :key="ui.theme"
          :name="ui.theme === 'dark' ? 'sun' : 'moon'"
          :size="17"
        />
      </Transition>
      <span class="sr-only">切换主题</span>
    </button>

    <button
      type="button"
      class="icon-btn"
      title="使用说明与口径"
      @click="ui.openHelp(String(route.meta.nav ?? ''))"
    >
      <AppIcon name="help" :size="17" />
      <span class="sr-only">帮助</span>
    </button>

    <RouterLink
      to="/settings"
      class="engine"
      :class="{ 'engine--off': !health.llmReady }"
      :title="
        health.llmReady
          ? `推理引擎已启用：${health.llmLabel}（来源：${health.llmSourceLabel}）`
          : `未启用大模型：${health.degradedReason || '未配置 LLM_API_KEY'}`
      "
    >
      <span class="engine__dot" aria-hidden="true" />
      <span class="engine__text mono">{{ health.llmLabel }}</span>
    </RouterLink>
  </header>
</template>

<style scoped>
.bar {
  position: sticky;
  top: 0;
  z-index: 30;
  display: flex;
  align-items: center;
  gap: var(--s3);
  height: var(--topbar-h);
  padding: 0 var(--s5);
  background: var(--bar-face);
  backdrop-filter: saturate(150%) blur(14px);
  -webkit-backdrop-filter: saturate(150%) blur(14px);
  border-bottom: 1px solid var(--ice-3);
}

.bar__toggle,
.icon-btn {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: none;
  border: 1px solid transparent;
  border-radius: var(--radius);
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease);
}

.bar__toggle:hover,
.icon-btn:hover {
  background: var(--ice-1);
  border-color: var(--ice-3);
  color: var(--glacier-deep);
}

.bar__id {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.bar__crumbs {
  display: flex;
  align-items: center;
  gap: 3px;
  min-width: 0;
  max-width: min(42vw, 520px);
  font-size: 9.5px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--ink-3);
}

.bar__parent {
  max-width: 150px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--ink-3);
  font: inherit;
  letter-spacing: inherit;
  text-transform: inherit;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
}

.bar__parent:hover,
.bar__parent:focus-visible {
  color: var(--glacier-deep);
  text-decoration: underline;
  outline: none;
}

.bar__crumb-current {
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.bar__crumb-sep {
  flex: none;
}

.bar__title {
  min-width: 0;
  max-width: min(48vw, 720px);
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: var(--fs-md);
  font-weight: 600;
  letter-spacing: -0.015em;
  line-height: 1.3;
  color: var(--ink-1);
  white-space: nowrap;
}

.bar__hint {
  margin-left: var(--s3);
  font-size: var(--fs-xs);
  font-weight: 400;
  color: var(--ink-3);
}

.palette {
  display: flex;
  align-items: center;
  gap: var(--s2);
  height: 34px;
  padding: 0 8px 0 10px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-1);
  color: var(--ink-3);
  font: inherit;
  font-size: var(--fs-xs);
  cursor: pointer;
  transition: border-color var(--dur-fast) var(--ease), background-color var(--dur-fast) var(--ease);
}

.palette:hover {
  background: var(--ice-0);
  border-color: var(--ice-5);
  color: var(--ink-2);
}

.palette__text {
  white-space: nowrap;
}

.palette__kbd {
  padding: 1px 5px;
  border: 1px solid var(--ice-4);
  border-radius: 4px;
  background: var(--ice-0);
  font-size: 10px;
  color: var(--ink-3);
}

.bar__group {
  position: relative;
}

.menu {
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  width: 208px;
  padding: 6px;
  background: var(--ice-0);
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  box-shadow: var(--shadow-overlay);
  animation: rise-in var(--dur) var(--ease) both;
}

.menu__caption {
  padding: 4px 8px 6px;
  font-size: var(--fs-2xs);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  color: var(--ink-3);
}

.menu__item {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: center;
  gap: 2px;
  width: 100%;
  padding: 6px 8px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--ink-2);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.menu__item:hover {
  background: var(--ice-1);
}

.menu__item--on {
  color: var(--glacier-deep);
}

.menu__label {
  font-size: var(--fs-sm);
  font-weight: 500;
}

.menu__hint {
  grid-column: 1;
  font-size: 10.5px;
  color: var(--ink-3);
}

.menu__item svg {
  grid-row: 1 / span 2;
  grid-column: 2;
}

.engine {
  display: flex;
  align-items: center;
  gap: var(--s2);
  height: 34px;
  max-width: 260px;
  padding: 0 12px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius-pill);
  background: var(--ice-0);
  text-decoration: none;
  color: var(--ink-2);
  transition: border-color var(--dur-fast) var(--ease), background-color var(--dur-fast) var(--ease);
}

.engine:hover {
  border-color: var(--glacier-tint);
  background: var(--glacier-wash);
}

.engine__dot {
  flex: none;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--pass);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--pass) 16%, transparent);
}

.engine--off .engine__dot {
  background: var(--warn);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--warn) 16%, transparent);
}

/* 明暗切换：图标转着换口气，而不是瞬间替换 */
.theme-swap-enter-active,
.theme-swap-leave-active {
  transition: transform var(--dur) var(--ease), opacity var(--dur-fast) var(--ease);
}

.theme-swap-enter-from {
  transform: rotate(-90deg) scale(0.55);
  opacity: 0;
}

.theme-swap-leave-to {
  transform: rotate(90deg) scale(0.55);
  opacity: 0;
}

.engine__text {
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 900px) {
  .bar {
    padding: 0 var(--s4);
  }

  .palette__text,
  .bar__hint,
  .engine__text {
    display: none;
  }

  .engine {
    padding: 0 10px;
  }

  .bar__crumbs {
    max-width: 34vw;
  }

  .bar__parent,
  .bar__crumb-sep {
    display: none;
  }

  .bar__title {
    max-width: 38vw;
  }
}
</style>
