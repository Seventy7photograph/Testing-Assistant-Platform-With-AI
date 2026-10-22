<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

import AppIcon from "@/components/AppIcon.vue";
import { useHealthStore } from "@/stores/health";
import { useUiStore } from "@/stores/ui";

interface NavItem {
  nav: string;
  to: string;
  label: string;
  hint: string;
  icon: string;
}

interface NavGroup {
  caption: string;
  items: NavItem[];
}

const groups: NavGroup[] = [
  {
    caption: "平台",
    items: [
      { nav: "dashboard", to: "/", label: "总览", hint: "AI 用例 · 报告", icon: "gauge" },
    ],
  },
  {
    caption: "用例生成",
    items: [
      { nav: "generate", to: "/generate", label: "用例生成", hint: "需求 → 用例", icon: "sparkle" },
      { nav: "documents", to: "/documents", label: "文档与需求", hint: "上传 · 解析", icon: "doc" },
      { nav: "apis", to: "/apis", label: "接口资产", hint: "OpenAPI · Postman", icon: "route" },
      { nav: "suites", to: "/suites", label: "用例集", hint: "统计 · 导出", icon: "cases" },
    ],
  },
  {
    caption: "测试报告",
    items: [
      { nav: "report", to: "/report", label: "报告工作台", hint: "指标 · 生成", icon: "chart" },
      { nav: "archive", to: "/report/archive", label: "报告存档", hint: "趋势 · 检索", icon: "archive" },
    ],
  },
  {
    caption: "平台设置",
    items: [
      { nav: "settings", to: "/settings", label: "大模型与阈值", hint: "两条 AI 链路共用", icon: "sliders" },
    ],
  },
];

const route = useRoute();
const router = useRouter();
const ui = useUiStore();
const health = useHealthStore();

const activeNav = computed(() => String(route.meta.nav ?? ""));
const collapsed = computed(() => ui.railCollapsed);

/** 导轨的层深随激活域移动：这是功能性的颜色，告诉你现在站在冰川的哪一层。 */
const domain = computed(() => {
  const value = route.meta.domain;
  return value === "case" || value === "report" ? value : "platform";
});

/** 从指针位置扩散的冰川底纹。 */
function trackPointer(event: MouseEvent) {
  const target = event.currentTarget as HTMLElement | null;
  if (!target) return;
  const rect = target.getBoundingClientRect();
  target.style.setProperty("--mx", `${event.clientX - rect.left}px`);
  target.style.setProperty("--my", `${event.clientY - rect.top}px`);
}

function go(to: string) {
  if (route.path !== to) void router.push(to);
}
</script>

<template>
  <aside class="rail" :data-domain="domain" :data-collapsed="collapsed ? '1' : '0'">
    <button
      type="button"
      class="rail__scrim"
      aria-label="关闭侧边栏"
      tabindex="-1"
      @click="ui.toggleRail()"
    />
    <div class="rail__brand" :title="collapsed ? '测试工程师助手平台' : undefined">
      <span class="rail__mark" aria-hidden="true">
        <svg viewBox="0 0 32 32" width="20" height="20" fill="none" aria-hidden="true">
          <path
            d="M4 21.5 16 5l12 16.5M8.5 21.5 16 11.5l7.5 10M12.5 21.5 16 17l3.5 4.5"
            stroke="currentColor"
            stroke-width="1.7"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </span>
      <span class="rail__names">
        <span class="rail__title">测试工程师助手</span>
        <span class="rail__sub mono">TEST ENGINEER CONSOLE</span>
      </span>
    </div>

    <nav class="rail__nav" aria-label="主导航">
      <div v-for="group in groups" :key="group.caption" class="rail__group">
        <p class="rail__caption">{{ group.caption }}</p>
        <ul class="rail__list">
          <li v-for="item in group.items" :key="item.nav">
            <a
              class="nav"
              :class="{ 'nav--on': activeNav === item.nav }"
              :href="item.to"
              :title="collapsed ? `${item.label} · ${item.hint}` : undefined"
              :aria-current="activeNav === item.nav ? 'page' : undefined"
              @mousemove="trackPointer"
              @click.prevent="go(item.to)"
            >
              <span class="nav__icon"><AppIcon :name="item.icon" :size="18" /></span>
              <span class="nav__text">
                <span class="nav__label">{{ item.label }}</span>
                <span class="nav__hint">{{ item.hint }}</span>
              </span>
            </a>
          </li>
        </ul>
      </div>
    </nav>

    <div class="rail__foot">
      <button
        type="button"
        class="status"
        :title="
          health.llmReady
            ? `推理引擎：${health.llmLabel}（${health.llmSourceLabel}）`
            : `未启用大模型：${health.degradedReason || '未配置 LLM_API_KEY'}`
        "
        @click="go('/settings')"
      >
        <span class="status__dot" :data-ready="health.llmReady ? '1' : '0'" aria-hidden="true" />
        <span class="status__text">
          <span class="status__label">推理引擎</span>
          <span class="status__value">{{ health.llmLabel }}</span>
        </span>
      </button>

      <p v-if="health.reachable && !health.llmReady" class="rail__warn">
        未配置 API Key：用例链路降级为规则引擎，报告链路需配置后可用。
      </p>
      <p v-else-if="!health.reachable" class="rail__warn">
        {{ health.error || "正在读取服务状态…" }}
      </p>

      <button
        type="button"
        class="collapse"
        :title="collapsed ? '展开侧边栏' : '收起侧边栏'"
        :aria-expanded="!collapsed"
        @click="ui.toggleRail()"
      >
        <AppIcon name="panel" :size="17" />
        <span class="collapse__text">收起侧边栏</span>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.rail {
  --rail-face: var(--ice-2);
  --rail-edge: var(--ice-3);
  --rail-hover: color-mix(in srgb, var(--ice-0) 72%, transparent);
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  width: var(--rail-w);
  height: 100vh;
  padding: var(--s4) var(--s3) var(--s4) var(--s3);
  background: linear-gradient(180deg, var(--ice-0) 0%, var(--rail-face) 46%, var(--ice-2) 100%);
  border-right: 1px solid var(--rail-edge);
  color: var(--ink-2);
  transition: width var(--dur) var(--ease), background var(--dur-slow) var(--ease);
  overflow: hidden;
}

.rail[data-domain="case"] {
  --rail-face: color-mix(in srgb, var(--glacier) 5%, var(--ice-2));
}

.rail[data-domain="report"] {
  --rail-face: color-mix(in srgb, var(--glacier) 11%, var(--ice-2));
}

.rail[data-collapsed="1"] {
  width: var(--rail-w-mini);
  padding-inline: var(--s2);
}

/* --- 品牌冰芯 ----------------------------------------------- */
.rail__brand {
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding: 2px var(--s2) var(--s3);
  border-bottom: 1px solid var(--rail-edge);
}

.rail__mark {
  display: grid;
  place-items: center;
  flex: none;
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: var(--mass);
  color: var(--on-mass);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--on-mass) 14%, transparent);
}

.rail__names {
  display: flex;
  flex-direction: column;
  min-width: 0;
  opacity: 1;
  transition: opacity var(--dur-fast) var(--ease);
}

.rail__title {
  font-size: var(--fs-sm);
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--ink-1);
  white-space: nowrap;
}

.rail__sub {
  font-size: 9.5px;
  letter-spacing: 0.12em;
  color: var(--ink-3);
  white-space: nowrap;
}

.rail[data-collapsed="1"] .rail__names {
  opacity: 0;
  pointer-events: none;
}

/* --- 导航 --------------------------------------------------- */
.rail__nav {
  flex: 1 1 auto;
  overflow-y: auto;
  overflow-x: hidden;
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

.rail__group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.rail__caption {
  padding: 0 var(--s3) 4px;
  font-size: var(--fs-2xs);
  font-weight: 600;
  letter-spacing: var(--tracking-label);
  color: var(--ink-3);
  text-transform: uppercase;
  white-space: nowrap;
  transition: opacity var(--dur-fast) var(--ease);
}

.rail[data-collapsed="1"] .rail__caption {
  opacity: 0;
  height: 2px;
  padding: 0;
  overflow: hidden;
}

.rail__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding: 8px var(--s3);
  border-radius: var(--radius);
  color: var(--ink-2);
  text-decoration: none;
  isolation: isolate;
  transition: color var(--dur-fast) var(--ease), background-color var(--dur-fast) var(--ease);
}

/* 从指针位置扩散的冰川底纹 */
.nav::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  z-index: -1;
  background: radial-gradient(
    120px circle at var(--mx, 50%) var(--my, 50%),
    var(--glacier-wash),
    transparent 72%
  );
  opacity: 0;
  transition: opacity var(--dur) var(--ease);
}

.nav:hover::before {
  opacity: 1;
}

.nav:hover {
  color: var(--glacier-deep);
}

.nav--on {
  background: var(--ice-0);
  color: var(--ink-1);
  box-shadow: inset 0 0 0 1px var(--ice-3);
}

.nav--on::after {
  content: "";
  position: absolute;
  left: 0;
  top: 50%;
  width: 2px;
  height: 18px;
  transform: translateY(-50%);
  border-radius: 0 2px 2px 0;
  background: var(--glacier);
}

.nav--on .nav__hint {
  color: var(--ink-3);
}

.nav__icon {
  display: grid;
  place-items: center;
  flex: none;
  width: 22px;
  color: inherit;
}

.nav--on .nav__icon {
  color: var(--glacier-deep);
}

.nav__text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  transition: opacity var(--dur-fast) var(--ease);
}

.nav__label {
  font-size: var(--fs-base);
  font-weight: 500;
  white-space: nowrap;
}

.nav__hint {
  font-size: 10.5px;
  color: var(--ink-3);
  white-space: nowrap;
}

.rail[data-collapsed="1"] .nav__text {
  opacity: 0;
  pointer-events: none;
}

.rail[data-collapsed="1"] .nav {
  justify-content: center;
  padding-inline: 0;
}

.rail[data-collapsed="1"] .nav--on::after {
  height: 22px;
}

/* --- 页脚 --------------------------------------------------- */
.rail__foot {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  padding-top: var(--s3);
  border-top: 1px solid var(--rail-edge);
}

.status {
  display: flex;
  align-items: center;
  gap: var(--s2);
  width: 100%;
  padding: 7px var(--s2);
  border: 1px solid transparent;
  border-radius: var(--radius);
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease);
}

.status:hover {
  background: var(--ice-0);
  border-color: var(--ice-3);
}

.status__dot {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ice-5);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--ice-5) 24%, transparent);
}

.status__dot[data-ready="1"] {
  background: var(--pass);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--pass) 16%, transparent);
}

.status__text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  transition: opacity var(--dur-fast) var(--ease);
}

.status__label {
  font-size: var(--fs-2xs);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  color: var(--ink-3);
  white-space: nowrap;
}

.status__value {
  font-size: var(--fs-xs);
  color: var(--ink-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rail__warn {
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--warn);
  padding: 0 var(--s2);
}

.rail[data-collapsed="1"] .rail__warn,
.rail[data-collapsed="1"] .status__text {
  opacity: 0;
  height: 0;
  overflow: hidden;
}

.rail[data-collapsed="1"] .status {
  justify-content: center;
}

.collapse {
  display: flex;
  align-items: center;
  gap: var(--s2);
  width: 100%;
  padding: 7px var(--s2);
  border: 1px solid transparent;
  border-radius: var(--radius);
  background: transparent;
  color: var(--ink-3);
  font: inherit;
  font-size: var(--fs-xs);
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}

.collapse:hover {
  background: var(--ice-0);
  color: var(--glacier-deep);
}

.collapse__text {
  white-space: nowrap;
  transition: opacity var(--dur-fast) var(--ease);
}

.rail[data-collapsed="1"] .collapse {
  justify-content: center;
}

.rail[data-collapsed="1"] .collapse__text {
  display: none;
}

/* 窄屏浮层：背面加一层可点击的遮罩，点空白即收起 */
.rail__scrim {
  display: none;
}

@media (max-width: 1080px) {
  .rail {
    position: fixed;
    z-index: 40;
    box-shadow: var(--shadow-overlay);
  }

  .rail[data-collapsed="0"] .rail__scrim {
    display: block;
    position: fixed;
    inset: 0 0 0 var(--rail-w);
    border: none;
    padding: 0;
    background: var(--scrim);
    backdrop-filter: blur(2px);
    cursor: pointer;
    animation: rise-in var(--dur) var(--ease) both;
  }

  .rail[data-collapsed="1"] .rail__scrim {
    display: none;
  }

  .rail[data-collapsed="1"] {
    width: 0;
    padding-inline: 0;
    border-right: none;
  }
}
</style>

