<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import type { UploadFile } from "element-plus";

import { api, saveBlob } from "@/api";
import type { DocumentSummary } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorNote from "@/components/ErrorNote.vue";
import FieldHint from "@/components/FieldHint.vue";
import SectionCard from "@/components/SectionCard.vue";
import Tip from "@/components/Tip.vue";
import { confirmAction } from "@/composables/useFeedback";
import { useActionSession } from "@/stores/actionSession";
import { useHealthStore } from "@/stores/health";
import { useNoticeStore } from "@/stores/notice";
import { displayExtensions, engineLabel, engineTitle, formatBytes, formatRelative } from "@/utils/labels";

const router = useRouter();
const health = useHealthStore();
const notice = useNoticeStore();
const actions = useActionSession();

const documents = ref<DocumentSummary[]>([]);
const loading = ref(true);
const error = ref("");
const uploading = computed(() => actions.isRunning("documents.upload"));
const parsing = computed(() => actions.detail("documents.parse"));
const downloading = computed(() => actions.detail("documents.download"));
const recognizing = computed(() => actions.detail("documents.recognize"));
const keyword = ref("");
const preview = ref<DocumentSummary | null>(null);
let viewAlive = true;

const tableRef = ref<{ clearSelection: () => void } | null>(null);
const checked = ref<DocumentSummary[]>([]);
const batchDeleting = computed(() => actions.isRunning("documents.batch-delete"));

const useLlm = ref(true);
const maxItems = ref(8);

const acceptAttr = computed(() =>
  (health.info?.supported_extensions ?? [".docx", ".pdf", ".txt", ".md", ".csv", ".json"]).join(","),
);

const rows = computed(() => {
  const needle = keyword.value.trim().toLowerCase();
  if (!needle) return documents.value;
  return documents.value.filter((item) =>
    `${item.filename} ${item.extension} ${item.parser}`.toLowerCase().includes(needle),
  );
});

const totalBytes = computed(() => documents.value.reduce((sum, item) => sum + item.size_bytes, 0));
const parsedCount = computed(() => documents.value.filter((item) => item.has_requirement).length);

onMounted(() => {
  void load();
});

onBeforeUnmount(() => {
  viewAlive = false;
});

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    documents.value = await api.documents(100);
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    loading.value = false;
  }
}

async function onFileChange(file: UploadFile): Promise<void> {
  if (!file.raw) return;
  if (!actions.begin("documents.upload", file.name)) return;
  try {
    const doc = await api.uploadDocument(file.raw);
    notice.success("文档已上传", `${doc.filename} · ${doc.char_count} 字`);
    if (viewAlive) await load();
  } catch (err) {
    notice.error("上传失败", (err as Error).message);
  } finally {
    actions.end("documents.upload");
  }
}

async function parse(row: DocumentSummary): Promise<void> {
  if (useLlm.value) {
    const confirmed = await confirmAction({
      title: row.has_requirement ? `重新解析「${row.filename}」` : `解析「${row.filename}」`,
      message: row.has_requirement
        ? "重新解析会覆盖结构化需求；已有用例集不受影响。"
        : "将调用大模型抽取结构化需求，耗时随文档长度增长并消耗额度。解析失败会自动降级为规则引擎，并在结果页标注降级原因。",
      confirmText: row.has_requirement ? "重新解析" : "开始解析",
    });
    if (!confirmed) return;
  }
  if (!actions.begin("documents.parse", row.doc_id)) return;
  try {
    await api.parseRequirement({
      doc_id: row.doc_id,
      title: row.filename,
      use_llm: useLlm.value,
      max_items: maxItems.value,
    });
    notice.success("需求解析完成", "正在打开结构化需求…");
    if (viewAlive) await router.push(`/documents/${row.doc_id}/requirement`);
  } catch (err) {
    notice.error("解析失败", (err as Error).message);
  } finally {
    actions.end("documents.parse");
  }
}

async function download(row: DocumentSummary): Promise<void> {
  if (!actions.begin("documents.download", row.doc_id)) return;
  try {
    const file = await api.downloadDocument(row.doc_id);
    saveBlob(file.blob, file.filename || row.filename);
    notice.success("已开始下载", row.filename);
  } catch (err) {
    notice.error("下载失败", (err as Error).message);
  } finally {
    actions.end("documents.download");
  }
}

function openRequirement(row: DocumentSummary): void {
  void router.push(`/documents/${row.doc_id}/requirement`);
}

/** 图片识别状态的中文口径与色调：每一种状态都要能一眼看出「成没成、为什么」。 */
const IMAGE_STATUS: Record<string, { label: string; tone: string }> = {
  recognized: { label: "已识别", tone: "chip--pass" },
  empty: { label: "无文字", tone: "chip--warn" },
  skipped: { label: "已跳过", tone: "chip--ghost" },
  unavailable: { label: "未识别", tone: "chip--warn" },
  pending: { label: "待识别", tone: "chip--ghost" },
};

function imageStatus(status: string): { label: string; tone: string } {
  return IMAGE_STATUS[status] ?? { label: status || "未知", tone: "chip--ghost" };
}

function imageUrl(docId: string, filename: string): string {
  return api.documentImageUrl(docId, filename);
}

async function recognizeImages(row: DocumentSummary): Promise<void> {
  if (!actions.begin("documents.recognize", row.doc_id)) return;
  try {
    const updated = await api.recognizeDocumentImages(row.doc_id);
    const failed = updated.image_count - updated.image_recognized;
    if (updated.image_recognized) {
      notice.success(
        `已识别 ${updated.image_recognized}/${updated.image_count} 张图片`,
        failed ? `其余 ${failed} 张见文档预览里的原因。` : undefined,
      );
    } else {
      notice.info("没有识别出内容", "打开文档预览查看每张图片的具体原因。");
    }
    if (viewAlive && preview.value?.doc_id === row.doc_id) preview.value = updated;
    if (viewAlive) await load();
  } catch (err) {
    notice.error("图片识别失败", (err as Error).message);
  } finally {
    actions.end("documents.recognize");
  }
}

function downloadPreview(): void {
  if (preview.value) void download(preview.value);
}

function openPreviewRequirement(): void {
  const row = preview.value;
  if (!row) return;
  preview.value = null;
  openRequirement(row);
}

async function remove(row: DocumentSummary): Promise<void> {
  const confirmed = await confirmAction({
    title: "删除文档",
    message: `将同时删除「${row.filename}」的原文与已解析的需求。该操作不可撤销，已生成的用例集不受影响。`,
    confirmText: "删除",
    danger: true,
  });
  if (!confirmed) return;
  try {
    await api.deleteDocument(row.doc_id);
    notice.success("已删除", row.filename);
    if (viewAlive) await load();
  } catch (err) {
    notice.error("删除失败", (err as Error).message);
  }
}

function onSelectionChange(rows: DocumentSummary[]): void {
  checked.value = rows;
}

function clearSelection(): void {
  tableRef.value?.clearSelection();
  checked.value = [];
}

async function removeSelected(): Promise<void> {
  const ids = checked.value.map((row) => row.doc_id);
  if (!ids.length) return;
  const confirmed = await confirmAction({
    title: `批量删除 ${ids.length} 份文档`,
    message:
      "将同时删除这些文档的原文与已解析的需求。该操作不可撤销，已生成的用例集不受影响。",
    confirmText: `删除 ${ids.length} 份`,
    danger: true,
  });
  if (!confirmed) return;
  if (!actions.begin("documents.batch-delete")) return;
  try {
    const result = await api.batchDeleteDocuments(ids);
    if (result.missing.length) {
      notice.info(
        `已删除 ${result.deleted} 份文档`,
        `${result.missing.length} 份在服务端已不存在，已自动跳过。`,
      );
    } else {
      notice.success(`已删除 ${result.deleted} 份文档`);
    }
    clearSelection();
    if (viewAlive) await load();
  } catch (err) {
    notice.error("批量删除失败", (err as Error).message);
  } finally {
    actions.end("documents.batch-delete");
  }
}
</script>

<template>
  <div class="stack">
    <ErrorNote
      v-if="error"
      title="文档列表没有取到"
      :message="error"
      recovery="确认服务已启动后重试。"
      @retry="load"
    />

    <div class="grid grid--2">
      <SectionCard title="上传需求文档" sub="原文与解析结果分开存放，随时可回溯" icon="upload">
        <el-upload
          drag
          :auto-upload="false"
          :show-file-list="false"
          :limit="1"
          :accept="acceptAttr"
          :on-change="onFileChange"
        >
          <div class="drop" :class="{ 'drop--scanning': uploading }">
            <span v-if="uploading" class="drop__scan" aria-hidden="true" />
            <span class="drop__mark"><AppIcon name="upload" :size="20" /></span>
            <p class="drop__title">
              {{ uploading ? "正在上传并解析文档结构…" : "拖拽文件到此处，或点击选择" }}
            </p>
            <p class="drop__sub">
              支持 {{ displayExtensions(health.info?.supported_extensions ?? [".docx"]).join(" / ") }}
            </p>
          </div>
        </el-upload>
        <p v-if="uploading" class="scan-status" role="status">
          <span class="dot is-unfrozen" /> 解析中
        </p>
        <FieldHint>
          单个文件不超过 20MB。Word 表格会被结构化平铺，PDF 按页抽取，兼容 GBK 等中文编码。
        </FieldHint>
      </SectionCard>

      <SectionCard title="解析设置" sub="决定文档变成结构化需求的方式" icon="sliders">
        <div class="settings">
          <label class="setting">
            <span class="setting__label">
              解析引擎
              <Tip text="大模型抽取 + 规则引擎双路：大模型失败时自动降级，降级原因会写在结果里。" />
            </span>
            <div class="row">
              <el-switch v-model="useLlm" />
              <span class="setting__value">{{ useLlm ? "大模型优先" : "仅规则引擎" }}</span>
            </div>
            <FieldHint :tone="health.llmReady ? 'muted' : 'warn'">
              {{
                health.llmReady
                  ? `当前引擎：${health.llmLabel}。`
                  : "未配置大模型：即使打开此开关也会走规则引擎，不会中断流程。"
              }}
            </FieldHint>
          </label>

          <label class="setting">
            <span class="setting__label">
              解析需求条目上限
              <Tip text="这篇文档最多解析出多少条需求条目（按章节切分后取前 N 条）。它决定「能抽出几条需求」，与每条需求生成多少用例无关。" />
            </span>
            <el-input-number v-model="maxItems" :min="1" :max="50" controls-position="right" />
            <FieldHint>1–50，默认 8。只影响抽取，不影响用例条数。</FieldHint>
          </label>

          <hr class="rule" />
          <div class="tally">
            <div>
              <p class="tally__k">已上传</p>
              <p class="tally__v mono">{{ documents.length }} 份</p>
            </div>
            <div>
              <p class="tally__k">原文合计</p>
              <p class="tally__v mono">{{ formatBytes(totalBytes) }}</p>
            </div>
          </div>
        </div>
      </SectionCard>
    </div>

    <SectionCard
      title="文档库"
      :sub="`${rows.length} / ${documents.length} 份 · 已解析 ${parsedCount} 份`"
      icon="doc"
      flush
    >
      <template #actions>
        <div class="search">
          <AppIcon name="search" :size="15" />
          <input v-model="keyword" type="search" placeholder="按文件名 / 类型 / 解析器搜索" aria-label="搜索文档" />
        </div>
        <template v-if="checked.length">
          <span class="sel mono">已选 {{ checked.length }}</span>
          <el-button size="small" text @click="clearSelection">取消选择</el-button>
          <el-button size="small" type="danger" plain :loading="batchDeleting" @click="removeSelected">
            <AppIcon name="trash" :size="16" /> 批量删除
          </el-button>
        </template>
        <el-button size="small" @click="load">
          <AppIcon name="refresh" :size="14" /> 刷新
        </el-button>
      </template>

      <el-table
        v-if="rows.length || loading"
        ref="tableRef"
        v-loading="loading"
        :data="rows"
        size="small"
        row-key="doc_id"
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="42" />
        <el-table-column label="文件名" min-width="228">
          <template #default="{ row }">
            <button type="button" class="name" @click="preview = row">
              <AppIcon name="file" :size="15" />
              <span class="name__text">{{ row.filename }}</span>
            </button>
            <p v-if="row.warnings.length" class="row-warn">{{ row.warnings.join("；") }}</p>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="74">
          <template #default="{ row }"><span class="chip chip--ghost mono">{{ row.extension }}</span></template>
        </el-table-column>
        <el-table-column label="大小" width="86">
          <template #default="{ row }"><span class="mono">{{ formatBytes(row.size_bytes) }}</span></template>
        </el-table-column>
        <el-table-column prop="char_count" label="字数" width="90">
          <template #default="{ row }"><span class="mono">{{ row.char_count }}</span></template>
        </el-table-column>
        <el-table-column label="解析器" width="106">
          <template #default="{ row }"><span class="muted">{{ row.parser }}</span></template>
        </el-table-column>
        <el-table-column label="结构化需求" width="158">
          <template #default="{ row }">
            <button
              v-if="row.has_requirement"
              type="button"
              class="name"
              :title="`查看「${row.filename}」的 ${row.requirement_items} 条结构化需求`"
              @click="openRequirement(row)"
            >
              <AppIcon name="cases" :size="15" />
              <span class="name__text">{{ row.requirement_items }} 条</span>
            </button>
            <span v-else class="muted">未解析</span>
            <p
              v-if="row.parse_meta"
              class="engine mono"
              :title="`解析：${engineTitle(row.parse_meta)}`"
            >
              {{ engineLabel(row.parse_meta) }}
            </p>
          </template>
        </el-table-column>
        <el-table-column label="图片" width="112">
          <template #default="{ row }">
            <button
              v-if="row.image_count"
              type="button"
              class="name"
              :title="`共 ${row.image_count} 张图片，已识别 ${row.image_recognized} 张；点击查看详情`"
              @click="preview = row"
            >
              <AppIcon name="image" :size="15" />
              <span class="name__text mono">{{ row.image_recognized }}/{{ row.image_count }}</span>
            </button>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="上传时间" width="110">
          <template #default="{ row }"><span class="muted">{{ formatRelative(row.created_at) }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="286" align="right">
          <template #default="{ row }">
            <el-button size="small" text @click="preview = row">预览</el-button>
            <el-button
              size="small"
              text
              :loading="downloading === row.doc_id"
              title="下载上传时的原文"
              @click="download(row)"
            >
              <AppIcon name="download" :size="16" />
            </el-button>
            <el-button
              v-if="row.has_requirement"
              size="small"
              text
              :loading="parsing === row.doc_id"
              @click="parse(row)"
            >
              重新解析
            </el-button>
            <el-button
              v-else
              size="small"
              type="primary"
              plain
              :loading="parsing === row.doc_id"
              @click="parse(row)"
            >
              解析需求
            </el-button>
            <el-button size="small" text @click="remove(row)">
              <AppIcon name="trash" :size="17" />
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <EmptyState
        v-else
        icon="doc"
        title="文档库还是空的"
        reason="支持 Word、PDF、Markdown。"
        action-label="去上传"
        @action="load"
      />
    </SectionCard>

    <el-drawer :model-value="Boolean(preview)" size="560px" direction="rtl" @close="preview = null">
      <template #header>
        <div class="phead">
          <AppIcon name="file" :size="18" />
          <span class="phead__title">{{ preview?.filename }}</span>
        </div>
      </template>
      <template #footer>
        <div class="pfoot">
          <el-button
            v-if="preview?.image_count"
            size="small"
            :loading="recognizing === preview?.doc_id"
            title="按当前图片识别通道重新识别本文档里的全部图片"
            @click="preview && recognizeImages(preview)"
          >
            <AppIcon name="refresh" :size="15" /> 重新识别图片
          </el-button>
          <el-button size="small" :loading="downloading === preview?.doc_id" @click="downloadPreview">
            <AppIcon name="download" :size="15" /> 下载原文
          </el-button>
          <el-button
            v-if="preview?.has_requirement"
            size="small"
            type="primary"
            @click="openPreviewRequirement"
          >
            查看结构化需求（{{ preview?.requirement_items }} 条）
          </el-button>
        </div>
      </template>
      <div v-if="preview" class="preview">
        <div class="preview__grid">
          <div><p class="preview__k">类型</p><p class="preview__v mono">{{ preview.extension }}</p></div>
          <div><p class="preview__k">编码</p><p class="preview__v mono">{{ preview.encoding }}</p></div>
          <div><p class="preview__k">字数</p><p class="preview__v mono">{{ preview.char_count }}</p></div>
          <div><p class="preview__k">行数</p><p class="preview__v mono">{{ preview.line_count }}</p></div>
          <div v-if="preview.page_count"><p class="preview__k">页数</p><p class="preview__v mono">{{ preview.page_count }}</p></div>
          <div v-if="preview.table_count"><p class="preview__k">表格</p><p class="preview__v mono">{{ preview.table_count }}</p></div>
        </div>
        <hr class="rule" />
        <template v-if="preview.image_count">
          <p class="label">
            图片（识别 {{ preview.image_recognized }}/{{ preview.image_count }} 张）
          </p>
          <div class="shots">
            <figure v-for="shot in preview.images" :key="shot.filename" class="shot">
              <img
                class="shot__img"
                :src="imageUrl(preview.doc_id, shot.filename)"
                :alt="`第 ${shot.index} 张图片`"
                loading="lazy"
              />
              <figcaption class="shot__cap">
                <span class="chip" :class="imageStatus(shot.status).tone">
                  #{{ shot.index }} {{ imageStatus(shot.status).label }}
                </span>
                <span v-if="shot.anchor" class="shot__anchor">{{ shot.anchor }}</span>
              </figcaption>
              <p v-if="shot.extractor" class="shot__meta mono">{{ shot.extractor }}</p>
              <p v-if="shot.text_preview" class="shot__text">{{ shot.text_preview }}</p>
              <p v-else-if="shot.message" class="shot__note">{{ shot.message }}</p>
            </figure>
          </div>
        </template>
        <hr class="rule" />
        <p class="label">原文预览</p>
        <pre class="preview__body pre">{{ preview.preview || "（没有可预览的文本）" }}</pre>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.drop {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: var(--s5) var(--s3);
}

.drop--scanning {
  overflow: hidden;
}

.drop__scan {
  position: absolute;
  z-index: 2;
  left: 5%;
  right: 5%;
  height: 2px;
  background: var(--signal);
  box-shadow: none;
  animation: document-scan 1.8s var(--ease) infinite;
  pointer-events: none;
}

.scan-status {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: var(--s2);
  font-size: var(--fs-xs);
  color: var(--ink-2);
}

@keyframes document-scan {
  from {
    top: 8%;
  }
  to {
    top: 92%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .drop__scan {
    top: 50%;
    animation: none;
    opacity: 0.5;
  }
}

.drop__mark {
  display: grid;
  place-items: center;
  width: 46px;
  height: 46px;
  margin-bottom: 4px;
  border-radius: 14px;
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

.settings {
  display: flex;
  flex-direction: column;
  gap: var(--s4);
}

.setting {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.setting__label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: var(--fs-xs);
  font-weight: 600;
  letter-spacing: 0.03em;
  color: var(--ink-2);
}

.setting__value {
  font-size: var(--fs-sm);
  color: var(--ink-1);
}

.tally {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s3);
}

.tally__k {
  font-size: var(--fs-2xs);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  color: var(--ink-3);
}

.tally__v {
  font-size: var(--fs-lg);
  color: var(--ink-1);
}

.search {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  height: 30px;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-1);
  color: var(--ink-3);
}

.search input {
  border: none;
  outline: none;
  background: transparent;
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--ink-1);
  width: 200px;
}

.sel {
  font-size: var(--fs-xs);
  color: var(--glacier-deep);
  white-space: nowrap;
}

.name {
  display: flex;
  align-items: center;
  gap: 7px;
  border: none;
  background: transparent;
  padding: 0;
  font: inherit;
  color: var(--glacier-deep);
  cursor: pointer;
}

.name__text {
  font-size: var(--fs-sm);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.engine {
  margin-top: 2px;
  font-size: 10.5px;
  color: var(--ink-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-warn {
  margin-top: 2px;
  font-size: 10.5px;
  color: var(--warn);
  /* 告警里可能夹着正则或长填充串，这里限一行并截断，避免把整行撑高、撑宽。 */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  overflow-wrap: anywhere;
}

.phead {
  display: flex;
  align-items: center;
  gap: var(--s2);
  color: var(--ink-1);
}

.phead__title {
  font-size: var(--fs-base);
  font-weight: 600;
}

.pfoot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--s2);
}

.preview {
  display: flex;
  flex-direction: column;
  gap: var(--s3);
}

.preview__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s3);
}

.preview__k {
  font-size: var(--fs-2xs);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  color: var(--ink-3);
}

.preview__v {
  font-size: var(--fs-base);
  color: var(--ink-1);
}

.preview__body {
  max-height: 60vh;
  overflow: auto;
  padding: var(--s3);
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: var(--ice-1);
  font-size: var(--fs-xs);
  line-height: 1.7;
  color: var(--ink-2);
}

.shots {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: var(--s3);
}

.shot {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  min-width: 0;
}

.shot__img {
  width: 100%;
  height: 96px;
  object-fit: contain;
  border: 1px solid var(--ice-3);
  border-radius: var(--radius);
  background: #fff;
}

.shot__cap {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.shot__anchor {
  font-size: var(--fs-2xs);
  color: var(--ink-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.shot__meta {
  font-size: 10.5px;
  color: var(--ink-3);
  overflow-wrap: anywhere;
}

.shot__text,
.shot__note {
  font-size: var(--fs-2xs);
  line-height: 1.6;
  color: var(--ink-2);
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.shot__note {
  color: var(--ink-3);
}
</style>

