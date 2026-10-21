<script setup lang="ts">
/**
 * 大模型复核意见。
 *
 * 定位：**规则引擎产出的用例不会被模型改写**，模型只负责指出问题、提出建议。
 * 所以这里呈现的是「一份待你判断的清单」，而不是"已经帮你改好了"。
 * 每条都标明指向哪条用例 / 哪个字段，方便逐条核对后再动手。
 */
import { computed, ref } from "vue";

import type { ReviewFinding } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import { claimStatusLabel } from "@/utils/labels";

const props = defineProps<{ findings: ReviewFinding[] }>();

const expanded = ref(false);

const warningCount = computed(() => props.findings.filter((item) => item.severity === "warning").length);
const visible = computed(() => (expanded.value ? props.findings : props.findings.slice(0, 3)));
</script>

<template>
  <div v-if="findings.length" class="rf">
    <p class="rf__head">
      <span class="chip" :class="warningCount ? 'chip--warn' : 'chip--ghost'">
        {{ warningCount }} 条需关注 / 共 {{ findings.length }} 条
      </span>
      <span class="rf__note">规则用例未被改写，以下是模型给出的核对意见。</span>
    </p>
    <ul class="rf__list">
      <li v-for="(item, index) in visible" :key="`${item.requirement_id}-${index}`" :data-tone="item.severity">
        <AppIcon :name="item.severity === 'warning' ? 'alert' : 'info'" :size="14" />
        <div class="rf__body">
          <p class="rf__issue">
            <span v-if="item.target" class="rf__target">{{ item.target }}：</span>{{ item.issue }}
          </p>
          <p v-if="item.suggestion" class="rf__suggestion">建议：{{ item.suggestion }}</p>
          <p class="rf__meta mono">{{ item.requirement_id }} · {{ item.requirement_title }}</p>
          <details class="rf__evidence">
            <summary>
              证据与目标 · {{ claimStatusLabel(item.claim_status) }}
              <span v-if="item.evidence_quotes.length">· {{ item.evidence_quotes.length }} 条</span>
            </summary>
            <p class="rf__target-detail mono">
              {{ item.target_type || "target" }} / {{ item.target_id || item.target || "—" }}
            </p>
            <ul v-if="item.evidence_quotes.length" class="rf__quotes">
              <li v-for="quote in item.evidence_quotes" :key="quote">“{{ quote }}”</li>
            </ul>
            <p v-else class="rf__uncertain">{{ item.uncertainty_reason || "该意见为模型判断，需人工核对。" }}</p>
          </details>
        </div>
      </li>
    </ul>
    <button v-if="findings.length > 3" type="button" class="rf__toggle" @click="expanded = !expanded">
      <AppIcon :name="expanded ? 'chevronDown' : 'chevronRight'" :size="14" />
      {{ expanded ? "收起" : `查看全部 ${findings.length} 条意见` }}
    </button>
  </div>
</template>

<style scoped>
.rf {
  margin-top: var(--s3);
}

.rf__head {
  display: flex;
  align-items: center;
  gap: var(--s2);
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.rf__note {
  font-size: var(--fs-2xs);
  color: var(--ink-3);
}

.rf__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.rf__list li {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 6px 8px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-1);
  min-width: 0;
}

.rf__list li[data-tone="warning"] {
  border-color: color-mix(in srgb, var(--warn) 35%, var(--ice-3));
}

.rf__list li svg {
  flex: 0 0 auto;
  margin-top: 2px;
  color: var(--ink-3);
}

.rf__list li[data-tone="warning"] svg {
  color: var(--warn);
}

.rf__body {
  min-width: 0;
}

.rf__issue,
.rf__suggestion,
.rf__meta {
  font-size: var(--fs-xs);
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.rf__issue {
  color: var(--ink-1);
}

.rf__target {
  font-weight: 600;
}

.rf__suggestion {
  color: var(--ink-2);
}

.rf__meta {
  font-size: 10.5px;
  color: var(--ink-3);
}

.rf__evidence {
  margin-top: 4px;
  font-size: 10.5px;
  color: var(--ink-3);
}

.rf__evidence summary {
  width: fit-content;
  cursor: pointer;
}

.rf__target-detail,
.rf__uncertain,
.rf__quotes {
  margin-top: 4px;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.rf__quotes {
  margin-bottom: 0;
  padding-left: 1.2em;
  color: var(--ink-2);
}

.rf__uncertain {
  color: var(--warn);
}

.rf__toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 6px;
  padding: 2px 8px 2px 4px;
  border: 1px solid var(--ice-3);
  border-radius: 999px;
  background: transparent;
  font-size: var(--fs-2xs);
  color: var(--ink-2);
  cursor: pointer;
}

.rf__toggle:hover {
  border-color: var(--glacier-tint);
  color: var(--glacier-deep);
}
</style>
