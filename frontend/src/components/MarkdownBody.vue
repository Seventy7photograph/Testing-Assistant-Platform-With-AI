<script setup lang="ts">
import { computed } from "vue";

import { renderMarkdown } from "@/utils/markdown";

const props = defineProps<{
  source: string;
  streaming?: boolean;
  copyableCode?: boolean;
}>();
const html = computed(() =>
  renderMarkdown(props.source, { copyableCode: props.copyableCode }),
);

function fallbackCopy(text: string): void {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

async function copyCode(event: MouseEvent): Promise<void> {
  const target = event.target as HTMLElement | null;
  const button = target?.closest<HTMLButtonElement>("[data-copy-code]");
  if (!button) return;
  const code = button.parentElement?.querySelector("code")?.textContent ?? "";
  if (!code) return;
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(code);
    else fallbackCopy(code);
    button.textContent = "已复制";
    window.setTimeout(() => {
      button.textContent = "复制代码";
    }, 1500);
  } catch {
    fallbackCopy(code);
    button.textContent = "已复制";
  }
}
</script>

<template>
  <div class="md">
    <!-- eslint-disable-next-line vue/no-v-html -- 内容已在 renderMarkdown 中整体转义 -->
    <div class="md__body" v-html="html" @click="copyCode" />
    <span v-if="streaming" class="md__caret" aria-hidden="true" />
  </div>
</template>

<style scoped>
.md {
  font-size: var(--fs-base);
  line-height: 1.78;
  color: var(--ink-1);
  max-width: 74ch;
}

.md__caret {
  display: inline-block;
  width: 7px;
  height: 1.05em;
  margin-left: 2px;
  vertical-align: -0.16em;
  background: var(--glacier);
  animation: caret-blink 1s steps(2, start) infinite;
}

@keyframes caret-blink {
  50% {
    opacity: 0;
  }
}

.md__body :deep(h1),
.md__body :deep(h2) {
  margin: var(--s5) 0 var(--s2);
  font-size: var(--fs-md);
  font-weight: 600;
  letter-spacing: -0.01em;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--ice-3);
}

.md__body :deep(h1:first-child),
.md__body :deep(h2:first-child) {
  margin-top: 0;
}

.md__body :deep(h3),
.md__body :deep(h4) {
  margin: var(--s4) 0 var(--s2);
  font-size: var(--fs-base);
  font-weight: 600;
}

.md__body :deep(p) {
  margin: 0 0 var(--s3);
}

.md__body :deep(ul),
.md__body :deep(ol) {
  margin: 0 0 var(--s3);
  padding-left: 1.35em;
}

.md__body :deep(li) {
  margin-bottom: 4px;
}

.md__body :deep(li::marker) {
  color: var(--glacier);
}

.md__body :deep(strong) {
  font-weight: 600;
  color: var(--ink-1);
}

.md__body :deep(em) {
  font-style: italic;
  color: var(--ink-2);
}

.md__body :deep(code) {
  font-family: var(--font-data);
  font-size: 0.88em;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--ice-2);
  border: 1px solid var(--ice-3);
}

.md__body :deep(pre) {
  margin: 0 0 var(--s3);
  padding: var(--s3);
  overflow-x: auto;
  background: var(--ice-1);
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
}

.md__body :deep(.md-code) {
  position: relative;
  margin-bottom: var(--s3);
}

.md__body :deep(.md-code pre) {
  margin-bottom: 0;
  padding-top: 34px;
}

.md__body :deep(.md-code__copy) {
  position: absolute;
  z-index: 1;
  top: 6px;
  right: 6px;
  padding: 3px 7px;
  border: 1px solid var(--ice-4);
  border-radius: 4px;
  background: var(--ice-0);
  color: var(--ink-3);
  font: inherit;
  font-size: 10px;
  cursor: pointer;
}

.md__body :deep(.md-code__copy:hover) {
  color: var(--ink-1);
  border-color: var(--glacier);
}

.md__body :deep(pre code) {
  background: none;
  border: none;
  padding: 0;
}

.md__body :deep(blockquote) {
  margin: 0 0 var(--s3);
  padding: 2px 0 2px var(--s4);
  border-left: 2px solid var(--ice-4);
  color: var(--ink-2);
  font-size: var(--fs-sm);
}

.md__body :deep(table) {
  width: 100%;
  margin: 0 0 var(--s3);
  border-collapse: collapse;
  font-size: var(--fs-sm);
}

.md__body :deep(th),
.md__body :deep(td) {
  padding: 7px 12px;
  text-align: left;
  border-bottom: 1px solid var(--ice-3);
}

.md__body :deep(th) {
  font-size: var(--fs-xs);
  letter-spacing: 0.03em;
  color: var(--ink-2);
  background: var(--ice-1);
  border-bottom: 1px solid var(--ice-4);
}

.md__body :deep(hr) {
  border: 0;
  height: 1px;
  margin: var(--s4) 0;
  background: var(--ice-3);
}
</style>
