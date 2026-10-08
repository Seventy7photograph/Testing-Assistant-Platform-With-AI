<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";

import { api } from "@/api";
import type { LLMConfigInfo, LLMModelOption, LLMTestResult, ThresholdView } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import ErrorNote from "@/components/ErrorNote.vue";
import FieldHint from "@/components/FieldHint.vue";
import SectionCard from "@/components/SectionCard.vue";
import Tip from "@/components/Tip.vue";
import { confirmAction } from "@/composables/useFeedback";
import { useHealthStore } from "@/stores/health";
import { useNoticeStore } from "@/stores/notice";
import { formatDuration } from "@/utils/labels";

const health = useHealthStore();
const notice = useNoticeStore();

const config = ref<LLMConfigInfo | null>(null);
const thresholds = ref<ThresholdView | null>(null);
const loading = ref(true);
const error = ref("");
const saving = ref(false);
const testing = ref(false);
const testResult = ref<LLMTestResult | null>(null);

const provider = ref("");
const model = ref("");
const baseUrl = ref("");
const updateKey = ref(false);
const apiKey = ref("");
const timeout = ref(60);
const maxRetries = ref(2);
const temperature = ref(0.2);
const maxTokens = ref(2048);

const remoteModels = ref<LLMModelOption[]>([]);
const modelsNote = ref("");
const loadingModels = ref(false);
/** 已成功拉取过的「厂商|端点」组合，避免 watcher 把同一个请求重复发出去。 */
let lastModelsKey = "";
let inflightModelsKey = "";
let modelsTimer: ReturnType<typeof setTimeout> | undefined;

const THRESHOLD_META: Record<string, { label: string; hint: string; unit: "percent" | "floor" }> = {
  fail_rate: { label: "失败率上限", hint: "失败率超过该值即判「不建议发版」。", unit: "percent" },
  blocked_rate: { label: "阻塞率上限", hint: "阻塞率超过该值即判「不建议发版」。", unit: "percent" },
  execution_floor: { label: "执行率下限", hint: "执行率低于该值时不给出「通过」结论。", unit: "floor" },
  pass_line: { label: "趋势判读线", hint: "趋势图上的参考线，仅用于阅读，不参与判定。", unit: "percent" },
};

const percentFields = ref<Record<string, number>>({});

const providers = computed(() => config.value?.providers ?? []);
const currentProvider = computed(() => providers.value.find((item) => item.name === provider.value) ?? null);
const modelOptions = computed(() => {
  const list = remoteModels.value.length ? remoteModels.value : (currentProvider.value?.models ?? []);
  return list;
});
const overridden = computed(() => config.value?.overridden_fields ?? []);

/*
 * DeepSeek V4 默认开启思考模式，而官方文档写明「思考模式不支持 temperature」——
 * 界面上摆着一个拨不动的温度旋钮，会让人误以为调它有用。这里据当前模型如实说明。
 */
const thinkingNote = computed(() => {
  const name = (model.value || "").toLowerCase();
  if (name.startsWith("deepseek-flash") || name.startsWith("deepseek-v4-pro")) {
    return `温度建议 0.1–0.3，但当前模型默认开启思考模式，官方文档明确该模式下 temperature 不生效——这里填的值会被忽略，只影响非思考模式。最大输出要留够思考消耗：模型会先把上千 token 花在思维链上，预算太小会导致结构化 JSON 被截断。`;
  }
  return "温度越低越稳定：报告归纳建议用 0.1–0.3；用例设计若开启大模型增强，可适当调高。";
});

const apiKeyConfigured = computed(() => config.value?.api_key_configured ?? false);
const apiKeyPlaceholder = computed(() =>
  config.value?.api_key_configured ? `已配置：${config.value.api_key_masked}` : "尚未配置密钥",
);

onMounted(() => {
  void load();
});

/*
 * 候选模型必须以「表单里当前的厂商 + 端点地址」为准。
 * 之前只在切换厂商时拉一次，而且后端读的是**已保存**的端点——
 * 于是刚把端点换成千问的地址，下拉里还挂着 DeepSeek 的模型。现在端点一改就重拉。
 */
async function refreshModels(force = false): Promise<void> {
  const name = provider.value;
  const endpoint = baseUrl.value.trim();
  if (!name) return;
  const key = `${name}|${endpoint}`;
  if (!force && (key === lastModelsKey || key === inflightModelsKey)) return;
  inflightModelsKey = key;
  loadingModels.value = true;
  try {
    const list = await api.llmModels(name, endpoint);
    remoteModels.value = list.models;
    modelsNote.value =
      list.message || (list.source === "remote" ? "已从端点拉取模型列表。" : "使用内置模型列表。");
    lastModelsKey = key;
  } catch {
    modelsNote.value = "拉取远端模型失败，已回退内置列表。";
  } finally {
    if (inflightModelsKey === key) inflightModelsKey = "";
    loadingModels.value = false;
  }
}

watch(provider, (next, previous) => {
  if (!next || next === previous) return;
  const option = providers.value.find((item) => item.name === next);
  if (!option) return;
  // 切回「当前已保存的那个厂商」时，还原已保存的端点与模型，而不是套目录默认值。
  const saved = config.value?.provider === next ? config.value : null;
  baseUrl.value = saved?.base_url || option.default_base_url;
  model.value = saved?.model || option.default_model;
  remoteModels.value = [];
  modelsNote.value = "";
  lastModelsKey = "";
  inflightModelsKey = "";
  void refreshModels();
});

// 端点地址改完（停顿 600ms）自动重拉，不用先保存再手动刷新。
watch(baseUrl, () => {
  if (modelsTimer) clearTimeout(modelsTimer);
  modelsTimer = setTimeout(() => void refreshModels(), 600);
});

onUnmounted(() => {
  if (modelsTimer) clearTimeout(modelsTimer);
});

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const [llmConfig, thresholdView] = await Promise.all([api.llmConfig(), api.thresholds()]);
    applyConfig(llmConfig);
    thresholds.value = thresholdView;
    percentFields.value = Object.fromEntries(
      Object.entries(thresholdView.thresholds).map(([key, value]) => [key, Math.round(value * 1000) / 10]),
    );
    // 打开页面即按「当前厂商 + 端点」拉一次实时列表；拉不到会自动落到内置目录。
    void refreshModels();
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    loading.value = false;
  }
}

function applyConfig(info: LLMConfigInfo): void {
  config.value = info;
  provider.value = info.provider;
  model.value = info.model;
  baseUrl.value = info.base_url;
  timeout.value = info.timeout;
  maxRetries.value = info.max_retries;
  temperature.value = info.temperature;
  maxTokens.value = info.max_tokens;
  updateKey.value = false;
  apiKey.value = "";
  testResult.value = null;
}

function payload() {
  return {
    provider: provider.value,
    model: model.value,
    base_url: baseUrl.value,
    timeout: timeout.value,
    max_retries: maxRetries.value,
    temperature: temperature.value,
    max_tokens: maxTokens.value,
    ...(updateKey.value && apiKey.value ? { api_key: apiKey.value } : {}),
  };
}

async function testConnection(): Promise<void> {
  testing.value = true;
  testResult.value = null;
  try {
    testResult.value = await api.testLlmConfig(payload());
  } catch (err) {
    testResult.value = {
      ok: false,
      provider: provider.value,
      model: model.value,
      elapsed_ms: 0,
      message: (err as Error).message,
      reply: "",
    };
  } finally {
    testing.value = false;
  }
}

async function save(): Promise<void> {
  saving.value = true;
  try {
    const info = await api.saveLlmConfig(payload());
    applyConfig(info);
    await health.load(true);
    // 刚保存的端点/密钥此刻才生效，强制重拉一次实时模型列表。
    void refreshModels(true);
    notice.success("大模型配置已保存", "两条链路立即生效，无需重启。");
  } catch (err) {
    notice.error("保存失败", (err as Error).message);
  } finally {
    saving.value = false;
  }
}

async function resetConfig(): Promise<void> {
  const confirmed = await confirmAction({
    title: "恢复 .env 配置",
    message: "将清除所有界面覆盖项，回到 .env 基线配置（含模型、端点、参数与密钥）。该操作不影响已生成的用例与报告。",
    confirmText: "恢复默认",
    danger: true,
  });
  if (!confirmed) return;
  try {
    const info = await api.resetLlmConfig();
    applyConfig(info);
    await health.load(true);
    void refreshModels(true);
    notice.success("已恢复 .env 配置");
  } catch (err) {
    notice.error("恢复失败", (err as Error).message);
  }
}

async function clearKey(): Promise<void> {
  const confirmed = await confirmAction({
    title: "清除已保存的 API Key",
    message: "将删除界面保存的密钥。若 .env 里配置了 LLM_API_KEY，则仍会回落到该密钥；否则大模型将不可用。",
    confirmText: "清除密钥",
    danger: true,
  });
  if (!confirmed) return;
  try {
    const info = await api.saveLlmConfig({ api_key: "" });
    applyConfig(info);
    await health.load(true);
    notice.success("已清除界面保存的密钥");
  } catch (err) {
    notice.error("清除失败", (err as Error).message);
  }
}

async function saveThresholds(): Promise<void> {
  if (!thresholds.value) return;
  const values: Record<string, number> = {};
  Object.entries(percentFields.value).forEach(([key, value]) => {
    values[key] = Math.min(Math.max(value / 100, 0), 1);
  });
  try {
    thresholds.value = await api.saveThresholds(values);
    percentFields.value = Object.fromEntries(
      Object.entries(thresholds.value.thresholds).map(([key, value]) => [key, Math.round(value * 1000) / 10]),
    );
    notice.success("判定阈值已保存");
  } catch (err) {
    notice.error("保存失败", (err as Error).message);
  }
}

async function resetThresholds(): Promise<void> {
  const confirmed = await confirmAction({
    title: "恢复阈值默认值",
    message: "将清除界面保存的阈值覆盖，全部回到 .env 默认值。已归档报告的历史判定不会被改写。",
    confirmText: "恢复默认",
    danger: true,
  });
  if (!confirmed) return;
  try {
    thresholds.value = await api.resetThresholds();
    percentFields.value = Object.fromEntries(
      Object.entries(thresholds.value.thresholds).map(([key, value]) => [key, Math.round(value * 1000) / 10]),
    );
    notice.success("已恢复阈值默认值");
  } catch (err) {
    notice.error("恢复失败", (err as Error).message);
  }
}

const sourceLabel = (key: string): string =>
  thresholds.value?.sources[key] === "saved" ? "界面覆盖" : ".env 默认";
</script>

<template>
  <div class="stack">
    <ErrorNote
      v-if="error"
      title="配置没有取到"
      :message="error"
      recovery="确认后端已启动（python run.py），然后重试。"
      @retry="load"
    />

    <template v-if="config">
      <SectionCard title="大模型配置" sub="用例链路与报告链路共用同一份配置" icon="sliders">
        <template #actions>
          <span class="chip" :class="config.source === 'runtime' ? 'chip--glacier' : 'chip--ghost'">
            来源：{{ config.source === "runtime" ? "界面覆盖" : ".env 基线" }}
          </span>
          <span class="chip" :class="config.available ? 'chip--pass' : 'chip--warn'">
            {{ config.available ? "可用" : "不可用" }}
          </span>
        </template>

        <div class="grid grid--2">
          <label class="field">
            <span class="field__label">服务商</span>
            <el-select v-model="provider" placeholder="选择服务商" style="width: 100%">
              <el-option v-for="item in providers" :key="item.name" :label="item.label" :value="item.name">
                <div class="opt">
                  <span>{{ item.label }}</span>
                  <span class="opt__desc">{{ item.description }}</span>
                </div>
              </el-option>
            </el-select>
            <FieldHint>{{ currentProvider?.description || "选择后会自动带出默认端点与模型。" }}</FieldHint>
          </label>

          <label class="field">
            <span class="field__label">
              模型
              <Tip text="可从端点拉取的模型列表中选择，也可直接输入自定义模型名。" />
            </span>
            <div class="modelrow">
              <el-select
                v-model="model"
                filterable
                allow-create
                default-first-option
                placeholder="选择或输入模型名"
                style="width: 100%"
              >
                <el-option v-for="item in modelOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-button :loading="loadingModels" :disabled="!provider" @click="refreshModels(true)">
                <AppIcon name="refresh" :size="14" /> 拉取
              </el-button>
            </div>
            <FieldHint>{{ modelsNote || "覆盖模型只影响这两条链路的默认调用。" }}</FieldHint>
          </label>

          <label class="field">
            <span class="field__label">端点地址</span>
            <el-input v-model="baseUrl" placeholder="https://api.deepseek.com/v1" />
            <FieldHint>OpenAI 兼容端点均可；填写到包含 /v1 的根路径。</FieldHint>
          </label>

          <label class="field">
            <span class="field__label">API Key</span>
            <div class="keyrow">
              <el-input
                v-model="apiKey"
                type="password"
                show-password
                :disabled="!updateKey"
                :placeholder="apiKeyPlaceholder"
              />
              <el-switch v-model="updateKey" />
            </div>
            <FieldHint :tone="apiKeyConfigured ? 'muted' : 'warn'">
              {{
                updateKey
                  ? "打开开关后填写新密钥；保存时才会写入，明文不会出现在日志里。"
                  : "关闭开关表示保持现有密钥不变，保存其他项时不会覆盖它。"
              }}
            </FieldHint>
            <el-button v-if="apiKeyConfigured" size="small" text @click="clearKey">清除已保存的密钥</el-button>
          </label>
        </div>

        <hr class="rule" />

        <div class="grid grid--4">
          <label class="field">
            <span class="field__label">超时（秒）</span>
            <el-input-number v-model="timeout" :min="5" :max="600" controls-position="right" />
          </label>
          <label class="field">
            <span class="field__label">最大重试</span>
            <el-input-number v-model="maxRetries" :min="0" :max="6" controls-position="right" />
          </label>
          <label class="field">
            <span class="field__label">温度</span>
            <el-input-number v-model="temperature" :min="0" :max="2" :step="0.1" :precision="2" controls-position="right" />
          </label>
          <label class="field">
            <span class="field__label">最大输出</span>
            <el-input-number v-model="maxTokens" :min="256" :max="32768" :step="256" controls-position="right" />
          </label>
        </div>

        <FieldHint>
          {{ thinkingNote }}
        </FieldHint>

        <hr class="rule" />

        <div class="actions">
          <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
          <el-button :loading="testing" @click="testConnection">
            <AppIcon name="play" :size="14" /> 测试连通性
          </el-button>
          <el-button @click="resetConfig">恢复 .env</el-button>
          <div class="spacer" />
          <span v-if="overridden.length" class="chip chip--ghost mono">覆盖项：{{ overridden.join(" / ") }}</span>
        </div>

        <div v-if="testResult" class="test" :data-ok="testResult.ok">
          <AppIcon :name="testResult.ok ? 'check' : 'alert'" :size="16" />
          <div>
            <p class="test__title">
              {{ testResult.ok ? "连接成功" : "连接失败" }}
              <span class="mono test__meta">
                {{ testResult.provider }} · {{ testResult.model }}
                <template v-if="testResult.elapsed_ms"> · {{ formatDuration(testResult.elapsed_ms) }}</template>
              </span>
            </p>
            <p class="test__msg">{{ testResult.message }}</p>
            <p v-if="testResult.reply" class="test__reply mono">模型回复：{{ testResult.reply }}</p>
          </div>
        </div>
      </SectionCard>

      <SectionCard
        v-if="thresholds"
        title="发版判定阈值"
        sub="只作用于报告的发版结论，不改写已归档报告"
        icon="target"
      >
        <template #actions>
          <el-button size="small" @click="resetThresholds">恢复默认</el-button>
        </template>

        <div class="grid grid--4">
          <label v-for="(meta, key) in THRESHOLD_META" :key="key" class="field">
            <span class="field__label">
              {{ meta.label }}
              <Tip :text="meta.hint" />
            </span>
            <el-input-number
              v-model="percentFields[key]"
              :min="0"
              :max="100"
              :step="1"
              :precision="1"
              controls-position="right"
            />
            <FieldHint>当前来源：{{ sourceLabel(key) }}</FieldHint>
          </label>
        </div>

        <FieldHint>
          未关闭的 P0 会直接判「不建议发版」，与阈值无关；未标注状态的缺陷一律按未关闭计入。趋势判读线只影响曲线阅读。
        </FieldHint>

        <hr class="rule" />
        <div class="actions">
          <el-button type="primary" @click="saveThresholds">保存阈值</el-button>
        </div>
      </SectionCard>
    </template>

    <div v-else-if="loading" class="grid grid--2">
      <div v-for="n in 2" :key="n" class="card"><el-skeleton :rows="6" animated class="skel" /></div>
    </div>
  </div>
</template>

<style scoped>
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field__label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: var(--fs-xs);
  font-weight: 600;
  letter-spacing: 0.03em;
  color: var(--ink-2);
}

.opt {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s3);
}

.opt__desc {
  font-size: 10.5px;
  color: var(--ink-3);
}

.keyrow {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.keyrow .el-input {
  flex: 1 1 auto;
}

.modelrow {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.modelrow .el-select {
  flex: 1 1 auto;
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--s2);
  margin-top: var(--s3);
}

.test {
  display: flex;
  align-items: flex-start;
  gap: var(--s2);
  margin-top: var(--s3);
  padding: var(--s3) var(--s4);
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-1);
  color: var(--ink-2);
}

.test[data-ok="true"] {
  border-color: var(--pass-line);
  background: var(--pass-wash);
}

.test[data-ok="false"] {
  border-color: var(--fail-line);
  background: var(--fail-wash);
}

.test[data-ok="true"] > svg {
  color: var(--pass);
}

.test[data-ok="false"] > svg {
  color: var(--fail);
}

.test__title {
  display: flex;
  align-items: baseline;
  gap: var(--s2);
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--ink-1);
}

.test__meta {
  font-size: 10.5px;
  font-weight: 400;
  color: var(--ink-3);
}

.test__msg {
  margin-top: 2px;
  font-size: var(--fs-sm);
  line-height: 1.65;
  color: var(--ink-2);
}

.test__reply {
  margin-top: 2px;
  font-size: 10.5px;
  color: var(--ink-3);
}

.skel {
  padding: var(--s5);
}
</style>

