import { createRouter, createWebHistory } from "vue-router";

export type Domain = "case" | "report" | "platform";

declare module "vue-router" {
  interface RouteMeta {
    nav: string;
    title: string;
    domain: Domain;
    hint?: string;
    parentPath?: string;
    parentTitle?: string;
    keepAlive?: boolean;
  }
}

export const router = createRouter({
  history: createWebHistory("/"),
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    {
      path: "/",
      name: "dashboard",
      component: () => import("@/views/DashboardView.vue"),
      meta: { nav: "dashboard", title: "总览", domain: "platform", hint: "两条链路的状态与最近动态" },
    },
    {
      path: "/generate",
      name: "generate",
      component: () => import("@/views/GenerateView.vue"),
      meta: {
        nav: "generate",
        title: "用例生成",
        domain: "case",
        hint: "需求文档 → 结构化需求 → 用例集",
        keepAlive: true,
      },
    },
    {
      path: "/documents",
      name: "documents",
      component: () => import("@/views/DocumentsView.vue"),
      meta: { nav: "documents", title: "文档与需求", domain: "case", hint: "上传 · 解析 · 追溯" },
    },
    {
      path: "/documents/:docId/requirement",
      name: "requirement",
      component: () => import("@/views/RequirementView.vue"),
      meta: {
        nav: "documents",
        title: "结构化需求",
        domain: "case",
        parentPath: "/documents",
        parentTitle: "文档与需求",
      },
    },
    {
      path: "/suites",
      name: "suites",
      component: () => import("@/views/SuitesView.vue"),
      meta: { nav: "suites", title: "用例集", domain: "case", hint: "浏览 · 统计 · 导出" },
    },
    {
      path: "/suites/:suiteId",
      name: "suite-detail",
      component: () => import("@/views/SuiteDetailView.vue"),
      meta: {
        nav: "suites",
        title: "用例集详情",
        domain: "case",
        parentPath: "/suites",
        parentTitle: "用例集",
      },
    },
    {
      path: "/report",
      name: "report",
      component: () => import("@/views/ReportWorkbenchView.vue"),
      meta: {
        nav: "report",
        title: "报告工作台",
        domain: "report",
        hint: "执行数据 → 指标 → AI 报告",
        keepAlive: true,
      },
    },
    {
      path: "/report/archive",
      name: "archive",
      component: () => import("@/views/ArchiveView.vue"),
      meta: { nav: "archive", title: "报告存档", domain: "report", hint: "趋势 · 检索 · 对比" },
    },
    {
      path: "/report/archive/:reportId",
      name: "report-detail",
      component: () => import("@/views/ReportDetailView.vue"),
      meta: {
        nav: "archive",
        title: "报告详情",
        domain: "report",
        parentPath: "/report/archive",
        parentTitle: "报告存档",
      },
    },
    {
      path: "/settings",
      name: "settings",
      component: () => import("@/views/SettingsView.vue"),
      meta: { nav: "settings", title: "大模型与阈值", domain: "platform", hint: "两条链路共用" },
    },
    {
      path: "/:pathMatch(.*)*",
      name: "not-found",
      component: () => import("@/views/NotFoundView.vue"),
      meta: { nav: "", title: "页面不存在", domain: "platform" },
    },
  ],
});

export { router as default };
