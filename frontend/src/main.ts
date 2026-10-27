import { createPinia } from "pinia";
import { createApp } from "vue";
import ElementPlus from "element-plus";
import zhCn from "element-plus/es/locale/lang/zh-cn";

/* Paper & Ink Workbench: self-hosted Archivo + Azeret Mono. */
import "@fontsource/archivo/400.css";
import "@fontsource/archivo/500.css";
import "@fontsource/archivo/600.css";
import "@fontsource/azeret-mono/400.css";
import "@fontsource/azeret-mono/500.css";

import "element-plus/dist/index.css";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/element.css";

import App from "./App.vue";
import { router } from "./router";
import { useUiStore } from "./stores/ui";

const app = createApp(App);

app.use(createPinia());
app.use(router);
app.use(ElementPlus, { locale: zhCn });

/* 密度与主题偏好：在挂载前落到 <html>，避免首屏闪动 */
useUiStore().hydrate();

app.mount("#app");
