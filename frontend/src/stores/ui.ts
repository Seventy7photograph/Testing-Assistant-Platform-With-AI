import { defineStore } from "pinia";
import { ref } from "vue";

export type Density = "cozy" | "compact" | "relaxed";
export type Theme = "light" | "dark";

const DENSITY_KEY = "tap.density";
const RAIL_KEY = "tap.rail-collapsed";
const THEME_KEY = "tap.theme";

/**
 * 全站的节奏与浮层状态。
 * 密度只影响行高、内边距与表格字号，不影响层级与色彩。
 */
export const useUiStore = defineStore("ui", () => {
  const density = ref<Density>("cozy");
  const theme = ref<Theme>("light");
  const railCollapsed = ref(false);
  const helpOpen = ref(false);
  const helpTopic = ref<string>("");

  function applyTheme(next: Theme) {
    theme.value = next;
    document.documentElement.dataset.theme = next;
  }

  function applyDensity(next: Density) {
    density.value = next;
    document.documentElement.dataset.density = next;
  }

  function setDensity(next: Density) {
    applyDensity(next);
    try {
      localStorage.setItem(DENSITY_KEY, next);
    } catch {
      /* 隐私模式下 localStorage 不可写，忽略即可 */
    }
  }

  function toggleRail() {
    railCollapsed.value = !railCollapsed.value;
    try {
      localStorage.setItem(RAIL_KEY, railCollapsed.value ? "1" : "0");
    } catch {
      /* 同上 */
    }
  }

  /**
   * 切换主题：顺手给 <html> 挂上 260ms 的全局过渡，
   * 让冰层「重结晶」而不是硬跳；过渡结束后立刻摘掉，不拖累日常交互。
   */
  function setTheme(next: Theme) {
    if (next === theme.value) return;
    const root = document.documentElement;
    root.dataset.themeSwitching = "1";
    window.setTimeout(() => {
      delete root.dataset.themeSwitching;
    }, 300);
    applyTheme(next);
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      /* 同上 */
    }
  }

  function toggleTheme() {
    setTheme(theme.value === "dark" ? "light" : "dark");
  }

  function openHelp(topic = "") {
    helpTopic.value = topic;
    helpOpen.value = true;
  }

  /** 挂载前把偏好落到 <html>，避免首屏闪动。 */
  function hydrate() {
    let saved: string | null = null;
    let collapsed: string | null = null;
    let savedTheme: string | null = null;
    try {
      saved = localStorage.getItem(DENSITY_KEY);
      collapsed = localStorage.getItem(RAIL_KEY);
      savedTheme = localStorage.getItem(THEME_KEY);
    } catch {
      /* 忽略 */
    }
    const next: Density =
      saved === "compact" || saved === "relaxed" || saved === "cozy" ? saved : "cozy";
    applyDensity(next);
    applyTheme(savedTheme === "dark" ? "dark" : "light");
    railCollapsed.value = collapsed === "1";
  }

  return {
    density,
    theme,
    railCollapsed,
    helpOpen,
    helpTopic,
    setDensity,
    setTheme,
    toggleTheme,
    toggleRail,
    openHelp,
    hydrate,
  };
});
