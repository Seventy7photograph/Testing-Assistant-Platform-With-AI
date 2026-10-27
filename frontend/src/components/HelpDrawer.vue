<script setup lang="ts">
import { computed } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import { helpTopics, type HelpTopic } from "@/content/helpTopics";
import { useHealthStore } from "@/stores/health";
import { useUiStore } from "@/stores/ui";

const ui = useUiStore();
const health = useHealthStore();

const topic = computed<HelpTopic>(
  () => helpTopics[ui.helpTopic] ?? helpTopics.dashboard,
);
</script>

<template>
  <el-drawer
    v-model="ui.helpOpen"
    :title="`使用说明 · ${topic.title}`"
    direction="rtl"
    size="440px"
  >
    <div class="help stack">
      <p class="help__intro">{{ topic.intro }}</p>

      <div class="help__block">
        <p class="label">功能与口径</p>
        <ul class="help__points">
          <li v-for="point in topic.points" :key="point.label">
            <span class="help__chip">{{ point.label }}</span>
            <span class="help__text">{{ point.text }}</span>
          </li>
        </ul>
      </div>

      <div v-if="topic.steps?.length" class="help__block">
        <p class="label">最短路径</p>
        <ol class="help__steps">
          <li v-for="(step, index) in topic.steps" :key="step">
            <span class="help__no mono">{{ String(index + 1).padStart(2, "0") }}</span>
            <span>{{ step }}</span>
          </li>
        </ol>
      </div>

      <div class="help__engine card card--sunk">
        <div class="row">
          <AppIcon name="sliders" :size="16" />
          <p class="help__engineTitle">推理引擎</p>
          <div class="spacer" />
          <span class="chip" :class="health.llmReady ? 'chip--pass' : 'chip--warn'">
            {{ health.llmReady ? "已启用" : "未启用" }}
          </span>
        </div>
        <p class="help__engineValue mono">{{ health.llmLabel }}</p>
        <p class="help__engineNote">
          {{
            health.llmReady
              ? `配置来源：${health.llmSourceLabel}。可在「模型设置」页修改并立即生效。`
              : health.degradedReason ||
                "未配置 LLM_API_KEY：用例链路会自动降级为纯规则引擎，报告链路需要配置后可用。"
          }}
        </p>
      </div>
    </div>
  </el-drawer>
</template>

<style scoped>
.help__intro {
  margin: 0;
  font-size: var(--fs-sm);
  line-height: 1.7;
  color: var(--ink-2);
}

.help__block {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.help__points {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.help__points li {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--s2);
  align-items: start;
}

.help__chip {
  display: inline-block;
  min-width: 34px;
  padding: 1px 8px;
  border-radius: var(--radius-pill);
  background: var(--glacier-wash);
  color: var(--glacier-deep);
  font-size: var(--fs-2xs);
  font-weight: 600;
  line-height: 1.7;
  text-align: center;
  white-space: nowrap;
}

.help__text {
  font-size: var(--fs-sm);
  line-height: 1.7;
  color: var(--ink-2);
}

.help__steps {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.help__steps li {
  display: flex;
  gap: var(--s3);
  font-size: var(--fs-sm);
  color: var(--ink-2);
}

.help__no {
  padding-top: 2px;
  color: var(--glacier-deep);
  font-size: var(--fs-xs);
}

.help__engine {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--s4);
  color: var(--ink-2);
}

.help__engineTitle {
  font-size: var(--fs-xs);
  font-weight: 600;
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  color: var(--ink-3);
}

.help__engineValue {
  font-size: var(--fs-sm);
  color: var(--ink-1);
}

.help__engineNote {
  font-size: var(--fs-xs);
  line-height: 1.65;
  color: var(--ink-2);
}

@media (max-width: 640px) {
  .help__chip {
    min-width: 32px;
  }
}
</style>
