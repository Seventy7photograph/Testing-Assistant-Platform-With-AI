<script setup lang="ts">
import { computed } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import { useHealthStore } from "@/stores/health";
import { useUiStore } from "@/stores/ui";

const ui = useUiStore();
const health = useHealthStore();

interface Topic {
  title: string;
  intro: string;
  points: { label: string; text: string }[];
  steps?: string[];
}

/** 每个页面的使用说明与口径。提示是产品的一部分，不是补丁。 */
const topics: Record<string, Topic> = {
  dashboard: {
    title: "总览",
    intro: "这里把两条链路的状态放在一起：左边是你手上的素材，右边是你产出的交付物。",
    points: [
      { label: "刻度", text: "数字全部来自服务端实际存储，不是估算值。" },
      { label: "降级", text: "未配置大模型时，用例链路仍可用；报告链路会在生成前明确提示。" },
    ],
    steps: ["先看推理引擎是否就绪", "从「用例生成」或「报告工作台」开始一条链路"],
  },
  generate: {
    title: "用例生成",
    intro: "一条流水线：需求文档 → 结构化需求 → 用例集。可以只用规则引擎跑，也可以让大模型增强。",
    points: [
      { label: "两阶段口径", text: "「解析用 LLM」与「生成用 LLM」是两件事，结果页会分开显示。" },
      { label: "单条需求上限", text: "上限 60 条，用来抑制边界值爆炸；超出会被截断并给出告警。" },
      { label: "去重", text: "两层去重：精确指纹 + 跨方法语义重叠。被合并的用例会在「覆盖方法」列留下痕迹。" },
    ],
    steps: ["上传或粘贴需求", "选择设计方法", "生成", "在用例集里导出（Excel / CSV / XMind / TestLink XML / JSON）"],
  },
  documents: {
    title: "文档与需求",
    intro: "上传的原文、解析出的结构化需求都放在这里，可以随时回溯与删除。",
    points: [
      { label: "编码", text: "自动识别 UTF-8 / GBK 等中文编码，兼容 Windows 导出的 Word。" },
      { label: "表格", text: "Word 原生表格与 Markdown 表格会保留列结构；纯空格对齐的表格可能识别失败并给出告警。" },
    ],
  },
  suites: {
    title: "用例集",
    intro: "每次生成都会落一份用例集，带完整统计口径，可随时导出。",
    points: [
      { label: "覆盖方法", text: "跨方法合并后的用例会记录它覆盖到的全部方法，因此各项之和可以大于用例总数。" },
      { label: "导出", text: "Excel 四个 Sheet：用例明细 / 用例统计 / 需求追溯 / 生成信息。" },
    ],
  },
  report: {
    title: "报告工作台",
    intro: "指标由代码算，判断由模型写。左侧送检、右侧读数，生成过程是流式的。",
    points: [
      { label: "权威口径", text: "通过率、执行率、缺陷分布由服务端确定性计算，模型只引用不重算。" },
      { label: "读不出来就是读不出来", text: "纯文本或结构不完整的输入会返回「无法计算指标」并说明原因，不会凭空补数。" },
      { label: "判定闸门", text: "未关闭 P0 直接判「不建议发版」；未标注状态的缺陷一律按未关闭计入。" },
    ],
    steps: ["粘贴执行数据（JSON 或文本）", "可选：补充分析要求", "生成报告", "导出或归档"],
  },
  archive: {
    title: "报告存档",
    intro: "每份报告都落在本地 SQLite，可检索、可对比、可导出。",
    points: [
      { label: "趋势", text: "曲线只取最近若干轮，判读线跟随你配置的阈值。" },
      { label: "留痕", text: "存的是正文 + 指标快照 + 原始输入，删除后不可恢复。" },
    ],
  },
  settings: {
    title: "大模型与阈值",
    intro: "两条链路共用同一份大模型配置；判定阈值只作用于报告的发版结论。",
    points: [
      { label: "优先级", text: "界面保存的覆盖 > .env 基线。可以逐项恢复，也可以一键回到 .env。" },
      { label: "密钥", text: "只回显掩码，不落明文到日志；填写后无需重启即可生效。" },
      { label: "阈值", text: "失败率 / 阻塞率上限、执行率下限、趋势判读线，逐项可回退。" },
    ],
  },
};

const topic = computed<Topic>(() => topics[ui.helpTopic] ?? topics.dashboard);
</script>

<template>
  <el-drawer
    v-model="ui.helpOpen"
    :title="`使用说明 · ${topic.title}`"
    direction="rtl"
    size="420px"
  >
    <div class="help stack">
      <p class="help__intro">{{ topic.intro }}</p>

      <div class="help__block">
        <p class="label">要点</p>
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
              ? `配置来源：${health.llmSourceLabel}。可在「大模型与阈值」页修改并立即生效。`
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
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.help__points li {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--s2);
  align-items: start;
}

.help__chip {
  display: inline-block;
  padding: 1px 8px;
  border-radius: var(--radius-pill);
  background: var(--glacier-wash);
  color: var(--glacier-deep);
  font-size: var(--fs-2xs);
  font-weight: 600;
  white-space: nowrap;
  line-height: 1.7;
}

.help__text {
  font-size: var(--fs-sm);
  line-height: 1.7;
  color: var(--ink-2);
}

.help__steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.help__steps li {
  display: flex;
  gap: var(--s3);
  font-size: var(--fs-sm);
  color: var(--ink-2);
}

.help__no {
  color: var(--glacier-deep);
  font-size: var(--fs-xs);
  padding-top: 2px;
}

.help__engine {
  padding: var(--s4);
  display: flex;
  flex-direction: column;
  gap: 6px;
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
</style>
