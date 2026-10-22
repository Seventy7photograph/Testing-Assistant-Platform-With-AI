import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

export default defineConfig(({ command }) => ({
  // 生产构建由 FastAPI 挂载在 /static/；开发服务器则必须使用根路径，
  // 否则 Vite 会把 / 重定向到 /static/，Vue Router 再将 /static/ 当成不存在的业务路由。
  base: command === "serve" ? "/" : "/static/",
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    outDir: "../app/static",
    emptyOutDir: true,
    assetsDir: "assets",
    chunkSizeWarningLimit: 2000,
  },
  server: {
    port: 5173,
    proxy: {
      // 只代理真正的 API 前缀；"/apis" 是接口资产页面，不能被 "/api" 前缀误吞。
      "^/api/": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
}));
