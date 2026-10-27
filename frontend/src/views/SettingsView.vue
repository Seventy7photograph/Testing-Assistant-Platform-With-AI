<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";

import { api } from "@/api";
import type {
  LLMConfigInfo,
  LLMModelOption,
  LLMTestResult,
  ThresholdView,
  VisionConfigInfo,
  VisionTestResult,
} from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import ErrorNote from "@/components/ErrorNote.vue";
import FieldHint from "@/components/FieldHint.vue";
import SectionCard from "@/components/SectionCard.vue";
import Tip from "@/components/Tip.vue";
import { confirmAction } from "@/composables/useFeedback";
import { useActionSession } from "@/stores/actionSession";
import { useHealthStore } from "@/stores/health";
import { useNoticeStore } from "@/stores/notice";
import { formatDuration } from "@/utils/labels";

const health = useHealthStore();
const notice = useNoticeStore();
const actions = useActionSession();

const config = ref<LLMConfigInfo | null>(null);
const vision = ref<VisionConfigInfo | null>(null);
const thresholds = ref<ThresholdView | null>(null);
const loading = ref(true);
const error = ref("");
const saving = computed(() => actions.isRunning("settings.llm.save"));
const testing = computed(() => actions.isRunning("settings.llm.test"));
const resettingConfig = computed(() => actions.isRunning("settings.llm.reset"));
const clearingKey = computed(() => actions.isRunning("settings.llm.clear-key"));
const testResult = ref<LLMTestResult | null>(null);

const visionSaving = computed(() => actions.isRunning("settings.vision.save"));
const visionTesting = computed(() => actions.isRunning("settings.vision.test"));
const visionResetting = computed(() => actions.isRunning("settings.vision.reset"));
const thresholdSaving = computed(() => actions.isRunning("settings.thresholds.save"));
const thresholdResetting = computed(() => actions.isRunning("settings.thresholds.reset"));
const visionResult = ref<VisionTestResult | null>(null);
const visionProvider = ref("auto");
const visionMode = ref("text");
const visionModel = ref("");
const visionBaseUrl = ref("");
const visionUpdateKey = ref(false);
const visionApiKey = ref("");
const visionKeyConfigured = computed(() => vision.value?.api_key_configured ?? false);
const visionKeyPlaceholder = computed(() =>
  vision.value?.api_key_configured ? `已配置：${vision.value.api_key_masked}` : "尚未配置密钥（可复用大模型的 Key）",
);
const visionProviders = computed(() => vision.value?.providers ?? []);
const currentVisionProvider = computed(
  () => visionProviders.value.find((item) => item.name === visionProvider.value) ?? null,
);
/** 只有多模态模型需要 Key / 端点 / 模型名；其它通道填了也没用，直接收起。 */
const visionNeedsModel = computed(() => Boolean(currentVisionProvider.value?.allow_model));
const visionNeedsKey = computed(() => Boolean(currentVisionProvider.value?.requires_key));
const visionModes = computed(() => vision.value?.modes ?? []);

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
const loadingModels = computed(() => actions.isRunning("settings.models"));
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
    return "当前模型下 temperature 不生效；最大输出需预留思考 token。";
  }
  return "温度越低越稳定。";
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
  if (!actions.begin("settings.models", key)) return;
  inflightModelsKey = key;
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
    actions.end("settings.models");
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
    const [llmConfig, thresholdView, visionConfig] = await Promise.all([
      api.llmConfig(),
      api.thresholds(),
      api.visionConfig(),
    ]);
    applyConfig(llmConfig);
    applyVision(visionConfig);
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

function applyVision(info: VisionConfigInfo): void {
  vision.value = info;
  visionProvider.value = info.provider;
  visionMode.value = info.mode;
  visionModel.value = info.model;
  visionBaseUrl.value = info.base_url;
  visionUpdateKey.value = false;
  visionApiKey.value = "";
  visionResult.value = null;
}

function visionPayload() {
  const limits = vision.value;
  return {
    provider: visionProvider.value,
    mode: visionMode.value,
    ...(visionNeedsModel.value
      ? { model: visionModel.value, base_url: visionBaseUrl.value }
      : {}),
    ...(visionNeedsKey.value && visionUpdateKey.value && visionApiKey.value
      ? { api_key: visionApiKey.value }
      : {}),
    ...(limits
      ? {
          max_images: limits.max_images,
          max_side: limits.max_side,
          min_pixels: limits.min_pixels,
        }
      : {}),
  };
}

async function saveVision(): Promise<void> {
  if (!actions.begin("settings.vision.save")) return;
  try {
    applyVision(await api.saveVisionConfig(visionPayload()));
    await health.load(true);
    notice.success("图片识别配置已保存", "下次上传文档即按新通道识别。");
  } catch (err) {
    notice.error("保存失败", (err as Error).message);
  } finally {
    actions.end("settings.vision.save");
  }
}

async function resetVision(): Promise<void> {
  const confirmed = await confirmAction({
    title: "恢复图片识别基线",
    message: "将清除图片识别的界面覆盖，回到 .env 基线。大模型那边的界面配置不受影响。",
    confirmText: "恢复默认",
    danger: true,
  });
  if (!confirmed) return;
  if (!actions.begin("settings.vision.reset")) return;
  try {
    applyVision(await api.resetVisionConfig());
    await health.load(true);
    notice.success("已恢复图片识别基线");
  } catch (err) {
    notice.error("恢复失败", (err as Error).message);
  } finally {
    actions.end("settings.vision.reset");
  }
}

async function testVision(): Promise<void> {
  if (!actions.begin("settings.vision.test")) return;
  visionResult.value = null;
  try {
    visionResult.value = await api.testVisionConfig();
    if (visionResult.value.ok) {
      notice.success("识别通道可用", "已用探针图片真跑一次识别。");
    }
  } catch (err) {
    visionResult.value = {
      ok: false,
      provider: visionProvider.value,
      extractor: "",
      mode: visionMode.value,
      elapsed_ms: 0,
      message: (err as Error).message,
      sample: "",
    };
  } finally {
    actions.end("settings.vision.test");
  }
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
  if (!actions.begin("settings.llm.test")) return;
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
    actions.end("settings.llm.test");
  }
}

async function save(): Promise<void> {
  if (!actions.begin("settings.llm.save")) return;
  try {
    const info = await api.saveLlmConfig(payload());
    applyConfig(info);
    await health.load(true);
    // 刚保存的端点/密钥此刻才生效，强制重拉一次实时模型列表。
    void refreshModels(true);
    notice.success("大模型配置已保存", "所有模型任务立即生效，无需重启。");
  } catch (err) {
    notice.error("保存失败", (err as Error).message);
  } finally {
    actions.end("settings.llm.save");
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
  if (!actions.begin("settings.llm.reset")) return;
  try {
    const info = await api.resetLlmConfig();
    applyConfig(info);
    await health.load(true);
    void refreshModels(true);
    notice.success("已恢复 .env 配置");
  } catch (err) {
    notice.error("恢复失败", (err as Error).message);
  } finally {
    actions.end("settings.llm.reset");
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
  if (!actions.begin("settings.llm.clear-key")) return;
  try {
    const info = await api.saveLlmConfig({ api_key: "" });
    applyConfig(info);
    await health.load(true);
    notice.success("已清除界面保存的密钥");
  } catch (err) {
    notice.error("清除失败", (err as Error).message);
  } finally {
    actions.end("settings.llm.clear-key");
  }
}

async function saveThresholds(): Promise<void> {
  if (!thresholds.value) return;
  if (!actions.begin("settings.thresholds.save")) return;
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
  } finally {
    actions.end("settings.thresholds.save");
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
  if (!actions.begin("settings.thresholds.reset")) return;
  try {
    thresholds.value = await api.resetThresholds();
    percentFields.value = Object.fromEntries(
      Object.entries(thresholds.value.thresholds).map(([key, value]) => [key, Math.round(value * 1000) / 10]),
    );
    notice.success("已恢复阈值默认值");
  } catch (err) {
    notice.error("恢复失败", (err as Error).message);
  } finally {
    actions.end("settings.thresholds.reset");
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
            <el-button v-if="apiKeyConfigured" size="small" text :loading="clearingKey" @click="clearKey">清除已保存的密钥</el-button>
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
          <el-button :loading="resettingConfig" @click="resetConfig">恢复 .env</el-button>
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
        v-if="vision"
        title="图片识别"
        sub="需求文档里的图片（内嵌图 / 整页扫描 / 直接上传）→ 文字，主模型不必支持图片输入"
        icon="image"
      >
        <template #actions>
          <span class="chip" :class="vision.source === 'runtime' ? 'chip--glacier' : 'chip--ghost'">
            来源：{{ vision.source === "runtime" ? "界面覆盖" : ".env 基线" }}
          </span>
          <span class="chip" :class="vision.available ? 'chip--pass' : 'chip--warn'">
            {{ vision.available ? `当前：${vision.label}` : "当前不可用" }}
          </span>
        </template>

        <FieldHint v-if="!vision.available" tone="warn">
          {{ vision.degraded_reason }}
          <template v-if="vision.local_ocr_hint">安装任一本地 OCR 引擎即可离线识别：{{ vision.local_ocr_hint }}</template>
        </FieldHint>
        <FieldHint v-else>
          当前通道：{{ vision.label }}（{{ vision.extractor }}，产物类型 {{ vision.kind }}）。识别不了或跳过的图片，
          会在文档预览里逐张写明原因。
        </FieldHint>

        <hr class="rule" />

        <div class="grid grid--2">
          <label class="field">
            <span class="field__label">识别通道</span>
            <el-select v-model="visionProvider" placeholder="选择识别通道" style="width: 100%">
              <el-option v-for="item in visionProviders" :key="item.name" :label="item.label" :value="item.name">
                <div class="opt">
                  <span>{{ item.label }}</span>
                  <span class="opt__desc">{{ item.description }}</span>
                </div>
              </el-option>
            </el-select>
            <FieldHint>{{ currentVisionProvider?.description || "选择识别图片的方式。" }}</FieldHint>
          </label>

          <label v-if="currentVisionProvider?.allow_mode" class="field">
            <span class="field__label">识别方式</span>
            <el-select v-model="visionMode" placeholder="选择识别方式" style="width: 100%">
              <el-option v-for="item in visionModes" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <FieldHint>
              {{ visionModes.find((m) => m.value === visionMode)?.description || "" }}
            </FieldHint>
          </label>

          <template v-if="visionNeedsModel">
            <label class="field">
              <span class="field__label">视觉模型</span>
              <el-input v-model="visionModel" placeholder="如 qwen-vl-max / glm-4v-plus / gpt-4o" />
              <FieldHint>必须选支持图片输入的型号；纯文本模型传图片会被端点拒绝。</FieldHint>
            </label>
            <label class="field">
              <span class="field__label">端点地址</span>
              <el-input v-model="visionBaseUrl" placeholder="留空则复用大模型端点" />
              <FieldHint>留空即复用「大模型配置」里的端点。</FieldHint>
            </label>
          </template>

          <label v-if="visionNeedsKey" class="field">
            <span class="field__label">API Key</span>
            <div class="keyrow">
              <el-input
                v-model="visionApiKey"
                type="password"
                show-password
                :disabled="!visionUpdateKey"
                :placeholder="visionKeyPlaceholder"
              />
              <el-switch v-model="visionUpdateKey" />
            </div>
            <FieldHint :tone="visionKeyConfigured ? 'muted' : 'warn'">
              留空即复用大模型的 Key；需要单独计费或换厂商时在这里填。
            </FieldHint>
          </label>

          <label v-if="!visionNeedsModel" class="field">
            <span class="field__label">识别语言</span>
            <el-input :model-value="vision.languages" disabled />
            <FieldHint>本地 / 云端 OCR 的语言包设置，来自 .env（VISION_LANGUAGES）。</FieldHint>
          </label>
        </div>

        <hr class="rule" />

        <div class="grid grid--4">
          <label class="field">
            <span class="field__label">单文档图片上限</span>
            <el-input-number v-model="vision.max_images" :min="1" :max="200" controls-position="right" />
            <FieldHint>超出后按「已跳过」记录并写明原因。</FieldHint>
          </label>
          <label class="field">
            <span class="field__label">长边上限</span>
            <el-input-number v-model="vision.max_side" :min="200" :max="6000" :step="100" controls-position="right" />
            <FieldHint>提交前下采样，控制 token 与费用。</FieldHint>
          </label>
          <label class="field">
            <span class="field__label">最小像素面积</span>
            <el-input-number v-model="vision.min_pixels" :min="0" :max="1000000" :step="1024" controls-position="right" />
            <FieldHint>小于该面积的图片（图标、分隔线）不识别。</FieldHint>
          </label>
          <label class="field">
            <span class="field__label">本地 OCR 引擎</span>
            <el-input :model-value="vision.local_ocr_backend || '未检测到'" disabled />
            <FieldHint>留空即自动探测（RapidOCR / pytesseract / tesseract）。</FieldHint>
          </label>
        </div>

        <div class="actions">
          <el-button type="primary" :loading="visionSaving" @click="saveVision">保存配置</el-button>
          <el-button :loading="visionTesting" @click="testVision">
            <AppIcon name="play" :size="14" /> 测试识别
          </el-button>
          <el-button :loading="visionResetting" @click="resetVision">恢复基线</el-button>
          <div class="spacer" />
          <span v-if="vision.overridden_fields.length" class="chip chip--ghost mono">
            覆盖项：{{ vision.overridden_fields.length }} 项
          </span>
        </div>

        <div v-if="visionResult" class="test" :data-ok="visionResult.ok">
          <AppIcon :name="visionResult.ok ? 'check' : 'alert'" :size="16" />
          <div>
            <p class="test__title">
              {{ visionResult.ok ? "识别通道可用" : "识别通道不可用" }}
              <span class="mono test__meta">
                {{ visionResult.extractor || visionResult.provider }}
                <template v-if="visionResult.elapsed_ms"> · {{ formatDuration(visionResult.elapsed_ms) }}</template>
              </span>
            </p>
            <p class="test__msg">{{ visionResult.message }}</p>
            <p v-if="visionResult.sample" class="test__reply mono">识别样例：{{ visionResult.sample }}</p>
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
          <el-button size="small" :loading="thresholdResetting" @click="resetThresholds">恢复默认</el-button>
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
          <el-button type="primary" :loading="thresholdSaving" @click="saveThresholds">保存阈值</el-button>
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

