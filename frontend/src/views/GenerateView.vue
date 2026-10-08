<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import type { UploadFile } from "element-plus";

import { api, saveBlob } from "@/api";
import type { DocumentSummary, ExportFormatInfo, GenerateResult } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import CaseTable from "@/components/CaseTable.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorNote from "@/components/ErrorNote.vue";
import FieldHint from "@/components/FieldHint.vue";
import SectionCard from "@/components/SectionCard.vue";
import StatReadout from "@/components/StatReadout.vue";
import Tip from "@/components/Tip.vue";
import { confirmAction } from "@/composables/useFeedback";
import { useHealthStore } from "@/stores/health";
import { useNoticeStore } from "@/stores/notice";
import { RESERVED_METHODS, V1_METHODS, displayExtensions, engineLabel, engineTitle, formatDuration, methodLabel } from "@/utils/labels";

const router = useRouter();
const health = useHealthStore();
const notice = useNoticeStore();

const mode = ref<"text" | "upload">("text");
const text = ref("");
const title = ref("粘贴的需求文本");
const docId = ref<string | null>(null);
const docInfo = ref<DocumentSummary | null>(null);
const uploading = ref(false);

const methods = ref<string[]>([...V1_METHODS]);
const maxItems = ref(8);
const useLlm = ref(true);
const useLlmInDesign = ref(false);

const generating = ref(false);
const result = ref<GenerateResult | null>(null);
const failure = ref<{ message: string; code: string } | null>(null);
const formats = ref<ExportFormatInfo[]>([]);

const METHOD_NOTES: Record<string, string> = {
  equivalence: "在有效类与无效类里各取代表值，覆盖输入域",
  boundary: "取上下界的 min-1 / min / max / max+1，专抓临界错误",
  scenario: "按主流程、备选流程、异常流各走一遍，串起业务链路",
};

const v1List = V1_METHODS.map((name) => ({
  name,
  label: methodLabel(name),
  note: METHOD_NOTES[name] ?? "",
}));

const reservedList = RESERVED_METHODS.map((name) => ({ name, label: methodLabel(name) }));

const acceptAttr = computed(() =>
  (health.info?.supported_extensions ?? [".docx", ".pdf", ".txt", ".md", ".csv", ".json"])
    .map((ext) => ext)
    .join(","),
);

const canGenerate = computed(() => {
  if (generating.value || methods.value.length === 0) return false;
  if (mode.value === "upload") return Boolean(docId.value);
  return text.value.trim().length > 0;
});

const sourceLabel = computed(() => {
  if (mode.value === "upload") return docInfo.value?.filename ?? "未选择文档";
  return text.value.trim() ? `${text.value.trim().length} 字` : "空";
});

const llmNote = computed(() =>
  health.llmReady
    ? `解析阶段将调用 ${health.llmLabel}；失败会自动降级为规则引擎并在结果里标注。`
    : "当前未配置大模型：即使打开此开关，也会自动走规则引擎解析，不会中断流程。",
);

const warnings = computed(() => {
  const data = result.value;
  if (!data) return [];
  return Array.from(
    new Set([
      ...data.warnings,
      ...data.suite.generation_meta.warnings,
      ...data.requirement_doc.parse_meta.warnings,
    ]),
  );
});

onMounted(async () => {
  try {
    formats.value = await api.exportFormats();
  } catch {
    /* 导出格式取自健康快照，失败不影响生成 */
  }
});

function toggleMethod(name: string) {
  const index = methods.value.indexOf(name);
  if (index === -1) methods.value.push(name);
  else methods.value.splice(index, 1);
}

async function onFileChange(file: UploadFile): Promise<void> {
  if (!file.raw) return;
  uploading.value = true;
  failure.value = null;
  try {
    const doc = await api.uploadDocument(file.raw);
    docId.value = doc.doc_id;
    docInfo.value = doc;
    notice.success("文档已上传", `${doc.filename} · ${doc.char_count} 字 · ${doc.parser}`);
  } catch (err) {
    failure.value = { message: (err as Error).message, code: "" };
    notice.error("上传失败", (err as Error).message);
  } finally {
    uploading.value = false;
  }
}

function reset() {
  result.value = null;
  failure.value = null;
}

async function generate(): Promise<void> {
  if (!canGenerate.value) return;
  if (useLlm.value) {
    const confirmed = await confirmAction({
      title: "确认使用大模型解析",
      message:
        "解析阶段会调用大模型，耗时随文档长度增长并消耗额度。解析失败时自动降级为规则引擎，降级原因会写在结果里。",
      confirmText: "开始生成",
    });
    if (!confirmed) return;
  }

  generating.value = true;
  result.value = null;
  failure.value = null;
  try {
    const common = {
      methods: methods.value,
      use_llm: useLlm.value,
      use_llm_in_design: useLlmInDesign.value,
      max_items: maxItems.value,
    };
    const payload =
      mode.value === "upload"
        ? { doc_id: docId.value, ...common }
        : { text: text.value, title: title.value.trim() || "未命名需求", ...common };
    const data = await api.generate(payload);
    result.value = data;
    notice.success(
      "用例集已生成",
      `共 ${data.suite.stats.total} 条 · 用时 ${formatDuration(data.suite.generation_meta.elapsed_ms)}`,
    );
  } catch (err) {
    failure.value = { message: (err as Error).message, code: "" };
  } finally {
    generating.value = false;
  }
}

async function exportSuite(format: string): Promise<void> {
  if (!result.value) return;
  try {
    const file = await api.exportSuite(result.value.suite.suite_id, format);
    saveBlob(file.blob, file.filename || `用例集.${format}`);
    notice.success("导出完成", file.filename || undefined);
  } catch (err) {
    notice.error("导出失败", (err as Error).message);
  }
}
</script>

<template>
  <div class="gen">
    <!-- 送检：左栏固定在视口内 -->
    <div class="gen__intake">
      <SectionCard title="送检" sub="需求文档或文本 → 结构化需求 → 用例集" icon="sparkle">
        <div class="form">
          <div class="seg" role="tablist" aria-label="输入方式">
            <button
              type="button"
              role="tab"
              class="seg__item"
              :class="{ 'seg__item--on': mode === 'text' }"
              :aria-selected="mode === 'text'"
              @click="mode = 'text'"
            >
              <AppIcon name="file" :size="15" /> 粘贴文本
            </button>
            <button
              type="button"
              role="tab"
              class="seg__item"
              :class="{ 'seg__item--on': mode === 'upload' }"
              :aria-selected="mode === 'upload'"
              @click="mode = 'upload'"
            >
              <AppIcon name="upload" :size="15" /> 上传文档
            </button>
          </div>

          <template v-if="mode === 'text'">
            <label class="field">
              <span class="field__label">用例集标题</span>
              <el-input v-model="title" size="default" placeholder="例如：登录模块 v1.2" />
            </label>
            <label class="field">
              <span class="field__label">需求文本</span>
              <el-input
                v-model="text"
                type="textarea"
                :rows="9"
                resize="vertical"
                placeholder="粘贴需求描述、验收标准或用户故事；越结构化，抽出的需求越准"
              />
              <FieldHint>支持 Markdown 标题与列表；编号、字段名、取值范围会被优先识别。</FieldHint>
            </label>
          </template>

          <template v-else>
            <el-upload
              drag
              :auto-upload="false"
              :show-file-list="false"
              :limit="1"
              :accept="acceptAttr"
              :on-change="onFileChange"
            >
              <div class="drop">
                <span class="drop__mark"><AppIcon name="upload" :size="20" /></span>
                <p class="drop__title">拖拽文件到此处，或点击选择</p>
                <p class="drop__sub">
                  支持 {{ displayExtensions(health.info?.supported_extensions ?? [".docx"]).join(" / ") }}
                </p>
              </div>
            </el-upload>
            <FieldHint>单个文件不超过 20MB；Word 表格会被结构化平铺，兼容 GBK 等中文编码。</FieldHint>

            <div v-if="uploading" class="picked picked--busy">
              <span class="dot is-unfrozen" />
              正在上传并解析文档结构…
            </div>
            <div v-else-if="docInfo" class="picked">
              <AppIcon name="doc" :size="16" />
              <div class="picked__body">
                <p class="picked__name">{{ docInfo.filename }}</p>
                <p class="picked__meta mono">
                  {{ docInfo.char_count }} 字 · {{ docInfo.parser }}
                  <template v-if="docInfo.table_count"> · {{ docInfo.table_count }} 张表</template>
                </p>
              </div>
              <el-button size="small" text @click="docId = null; docInfo = null">更换</el-button>
            </div>
          </template>

          <div class="field">
            <span class="field__label">
              设计方法
              <Tip text="三种方法平行生成，再按指纹去重、按语义合并，跨方法合并会记录 covered_methods。" />
            </span>
            <div class="methods">
              <button
                v-for="item in v1List"
                :key="item.name"
                type="button"
                class="method"
                :class="{ 'method--on': methods.includes(item.name) }"
                :aria-pressed="methods.includes(item.name)"
                @click="toggleMethod(item.name)"
              >
                <span class="method__box" aria-hidden="true">
                  <AppIcon v-if="methods.includes(item.name)" name="check" :size="12" />
                </span>
                <span class="method__text">
                  <span class="method__label">{{ item.label }}</span>
                  <span class="method__note">{{ item.note }}</span>
                </span>
              </button>

              <Tip
                v-for="item in reservedList"
                :key="item.name"
              :text="`${item.label}尚未实现：当前调用会返回 501，界面不会假装它可用。`"
              >
                <span class="method method--off">
                  <span class="method__box" aria-hidden="true" />
                  <span class="method__text">
                    <span class="method__label">{{ item.label }}</span>
              <span class="method__note">未实现</span>
                  </span>
                </span>
              </Tip>
            </div>
          </div>

          <div class="grid grid--2">
            <label class="field">
              <span class="field__label">
                单条需求用例上限
                <Tip text="边界值方法最容易膨胀，这个上限用于抑制它。取值范围 1–50。" />
              </span>
              <el-input-number v-model="maxItems" :min="1" :max="50" size="default" controls-position="right" />
              <FieldHint>1–50，默认 8。</FieldHint>
            </label>
            <div class="field">
              <span class="field__label">引擎策略</span>
              <div class="switches">
                <label class="switch">
                  <el-switch v-model="useLlm" />
                  <span>解析用大模型</span>
                </label>
                <label class="switch">
                  <el-switch v-model="useLlmInDesign" />
                  <span>生成用大模型</span>
                </label>
              </div>
              <FieldHint :tone="health.llmReady ? 'muted' : 'warn'">{{ llmNote }}</FieldHint>
            </div>
          </div>

          <hr class="rule" />

          <div class="actions">
            <el-button type="primary" :loading="generating" :disabled="!canGenerate" @click="generate">
              <AppIcon v-if="!generating" name="sparkle" :size="15" />
              {{ generating ? "生成中…" : "生成用例集" }}
            </el-button>
            <el-button :disabled="generating" @click="reset">清空结果</el-button>
            <div class="spacer" />
            <span class="source mono">来源：{{ sourceLabel }}</span>
          </div>
        </div>
      </SectionCard>
    </div>

    <!-- 读数：右栏 -->
    <div class="gen__side">
      <ErrorNote
        v-if="failure"
        title="本次生成没有完成"
        :message="failure.message"
        :code="failure.code || undefined"
        recovery="确认后端已启动（python run.py），或缩小单条需求用例上限后重试。"
        @retry="generate"
      />

      <template v-if="generating">
        <SectionCard title="正在生成" sub="规则引擎跑方法，必要时调用大模型增强">
          <div class="grid grid--4">
            <StatReadout label="用例总数" :value="null" pending hint="本轮生成的用例条目数" />
            <StatReadout label="去重合并" :value="null" pending hint="精确指纹与语义重叠合并掉的条数" />
            <StatReadout label="覆盖需求" :value="null" pending hint="至少被一条用例覆盖的需求条目数" />
            <StatReadout label="生成耗时" :value="null" pending hint="服务端从解析到排序的总耗时" />
          </div>
        </SectionCard>
      </template>

      <template v-else-if="result">
        <SectionCard
          title="本轮读数"
          :sub="`${result.suite.doc_title} · ${result.suite.methods.map(methodLabel).join(' / ')}`"
          icon="gauge"
        >
          <template #actions>
            <span class="chip chip--ghost mono">{{ result.suite.suite_id.slice(0, 12) }}</span>
          </template>
          <div class="grid grid--4">
            <StatReadout
              label="用例总数"
              :value="result.suite.stats.total"
              tone="glacier"
              hint="去重排序后的最终用例条目数"
            />
            <StatReadout
              label="去重合并"
              :value="result.suite.stats.duplicate_removed"
              hint="精确指纹命中 + 跨方法语义重叠合并掉的条数"
            />
            <StatReadout
              label="覆盖需求"
              :value="Object.keys(result.suite.stats.requirement_coverage).length"
              :unit="`/ ${result.requirement_doc.items.length}`"
              hint="至少被一条用例覆盖的需求条目数 / 需求条目总数"
            />
            <StatReadout
              label="生成耗时"
              :value="formatDuration(result.suite.generation_meta.elapsed_ms)"
              hint="服务端从解析到编号排序的总耗时"
            />
          </div>

          <hr class="rule" />

          <div class="meta">
            <span
              class="chip"
              :class="result.requirement_doc.parse_meta.llm_used ? 'chip--glacier' : 'chip--ghost'"
              :title="engineTitle(result.requirement_doc.parse_meta)"
            >
              解析：{{ engineLabel(result.requirement_doc.parse_meta) }}
            </span>
            <span
              class="chip"
              :class="result.suite.generation_meta.llm_used ? 'chip--glacier' : 'chip--ghost'"
              :title="engineTitle(result.suite.generation_meta)"
            >
              生成：{{ engineLabel(result.suite.generation_meta) }}
            </span>
            <span v-if="result.requirement_doc.parse_meta.fallback_used" class="chip chip--warn">
              已降级：{{ result.requirement_doc.parse_meta.fallback_reason }}
            </span>
            <span class="chip chip--ghost mono">{{ result.requirement_doc.parse_meta.provider }}</span>
          </div>

          <ul v-if="warnings.length" class="warns">
            <li v-for="item in warnings" :key="item">
              <AppIcon name="alert" :size="14" />
              <span>{{ item }}</span>
            </li>
          </ul>

        </SectionCard>

      </template>

      <SectionCard v-else title="还没有生成结果" icon="sparkle">
        <EmptyState
          icon="sparkle"
          title="左侧送检后，这里会显示用例集"
          reason="平台会先用规则引擎抽取结构化需求，再按选中的设计方法生成用例，最后去重、排序、按方法编号。"
          action-label="加载示例需求"
          @action="
            mode = 'text';
            title = '示例：账户登录需求';
            text =
              '功能：用户使用手机号与密码登录。\n\n字段：手机号（11 位数字，必填）、密码（8-20 位，必填，含大小写字母与数字）。\n\n业务规则：连续 5 次密码错误锁定账户 30 分钟。\n\n主流程：输入手机号 → 输入密码 → 点击登录 → 进入首页。\n\n异常：验证码错误提示“手机号或密码错误”；账户锁定时提示剩余锁定时间。\n\n验收标准：正确凭据可登录；错误凭据给出明确提示；锁定后 30 分钟内不允许登录。';
          "
        />
      </SectionCard>
    </div>

    <!-- 产出：跨两列铺满，用例表需要宽度 -->
    <div v-if="result" class="gen__full">
      <SectionCard
        title="用例明细"
        :sub="`${result.suite.cases.length} 条，按编号排序`"
        icon="cases"
        flush
      >
        <template #actions>
          <el-button
            v-for="fmt in formats"
            :key="fmt.name"
            size="small"
            @click="exportSuite(fmt.name)"
          >
            <AppIcon name="download" :size="14" />
            {{ fmt.label }}
          </el-button>
          <el-button size="small" type="primary" plain @click="router.push(`/suites/${result.suite.suite_id}`)">
            用例集详情
            <AppIcon name="chevronRight" :size="14" />
          </el-button>
        </template>
        <CaseTable :suite="result.suite" />
      </SectionCard>

      <SectionCard title="需求追溯" :sub="`解析出 ${result.requirement_doc.items.length} 条结构化需求`" icon="doc">
        <p class="trace__summary">{{ result.requirement_doc.summary || "解析未给出摘要。" }}</p>
        <ul class="trace">
          <li v-for="item in result.requirement_doc.items" :key="item.id">
            <div class="trace__head">
              <span class="trace__id mono">{{ item.id }}</span>
              <span class="trace__title">{{ item.title }}</span>
              <span class="chip chip--ghost">{{ item.module }}</span>
              <div class="spacer" />
              <span class="trace__count mono">
                {{ result.suite.stats.requirement_coverage[item.id] ?? 0 }} 条用例
              </span>
            </div>
            <p class="trace__desc clamp-2">{{ item.description || item.raw_text }}</p>
          </li>
        </ul>
        <FieldHint>
          每条用例都带 requirement_ids；导出的 Excel 里有独立的「需求追溯」页，可直接核对覆盖缺口。
        </FieldHint>
      </SectionCard>
    </div>
  </div>
</template>

<style scoped>
.gen {
  display: grid;
  grid-template-columns: minmax(320px, 384px) minmax(0, 1fr);
  align-items: start;
  gap: var(--gap-grid);
}

/* 产出跨两列铺满，所以送检面板不吸顶：吸顶会被下方表格压住 */
.gen__intake {
  min-width: 0;
}

.gen__side,
.gen__full {
  display: flex;
  flex-direction: column;
  gap: var(--gap-stack);
  min-width: 0;
}

.gen__full {
  grid-column: 1 / -1;
}

@media (max-width: 1080px) {
  .gen {
    grid-template-columns: minmax(0, 1fr);
  }
}

.form {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

.seg {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 3px;
  padding: 3px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-1);
}

.seg__item {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 7px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--ink-2);
  font: inherit;
  font-size: var(--fs-sm);
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}

.seg__item--on {
  background: var(--ice-0);
  color: var(--glacier-deep);
  box-shadow: inset 0 0 0 1px var(--ice-3);
}

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

.drop {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: var(--s4) var(--s3);
}

.drop__mark {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  margin-bottom: 4px;
  border-radius: 13px;
  border: 1px dashed var(--ice-4);
  color: var(--glacier-deep);
}

.drop__title {
  font-size: var(--fs-sm);
  font-weight: 500;
  color: var(--ink-1);
}

.drop__sub {
  font-size: var(--fs-xs);
  color: var(--ink-3);
}

.picked {
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding: var(--s3);
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-1);
  color: var(--ink-2);
}

.picked--busy {
  font-size: var(--fs-sm);
}

.picked__body {
  flex: 1 1 auto;
  min-width: 0;
}

.picked__name {
  font-size: var(--fs-sm);
  font-weight: 500;
  color: var(--ink-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.picked__meta {
  font-size: 10.5px;
  color: var(--ink-3);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  background: var(--glacier);
}

.methods {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.method {
  display: flex;
  align-items: flex-start;
  gap: var(--s2);
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-0);
  color: var(--ink-2);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color var(--dur-fast) var(--ease), background-color var(--dur-fast) var(--ease);
}

.method:hover {
  border-color: var(--glacier-tint);
  background: var(--glacier-wash);
}

.method--on {
  border-color: var(--glacier);
  background: var(--glacier-wash);
}

.method--off {
  opacity: 0.72;
  cursor: not-allowed;
}

.method__box {
  display: grid;
  place-items: center;
  flex: none;
  width: 16px;
  height: 16px;
  margin-top: 1px;
  border: 1px solid var(--ice-5);
  border-radius: 4px;
  color: var(--ice-0);
  background: var(--ice-0);
}

.method--on .method__box {
  background: var(--glacier);
  border-color: var(--glacier);
}

.method__text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.method__label {
  font-size: var(--fs-sm);
  font-weight: 500;
  color: var(--ink-1);
}

.method__note {
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--ink-3);
}

.switches {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 2px;
}

.switch {
  display: flex;
  align-items: center;
  gap: var(--s2);
  font-size: var(--fs-sm);
  color: var(--ink-2);
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.source {
  font-size: 10.5px;
  color: var(--ink-3);
}

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: var(--s3);
}

.warns {
  list-style: none;
  margin: var(--s3) 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.warns li {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: var(--fs-xs);
  line-height: 1.6;
  color: var(--warn);
}

.trace__summary {
  font-size: var(--fs-sm);
  line-height: 1.7;
  color: var(--ink-2);
  margin-bottom: var(--s3);
}

.trace {
  list-style: none;
  margin: 0 0 var(--s3);
  padding: 0;
  display: flex;
  flex-direction: column;
}

.trace li {
  padding: var(--s3) 0;
  border-bottom: 1px solid var(--ice-3);
}

.trace__head {
  display: flex;
  align-items: center;
  gap: var(--s2);
}

.trace__id {
  font-size: var(--fs-xs);
  color: var(--glacier-deep);
}

.trace__title {
  font-size: var(--fs-sm);
  font-weight: 500;
  color: var(--ink-1);
}

.trace__count {
  font-size: var(--fs-xs);
  color: var(--ink-3);
}

.trace__desc {
  margin-top: 3px;
  font-size: var(--fs-xs);
  line-height: 1.65;
  color: var(--ink-2);
}
</style>

