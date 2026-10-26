<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { api } from "@/api";
import type { PlatformOverview } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorNote from "@/components/ErrorNote.vue";
import SectionCard from "@/components/SectionCard.vue";
import StatReadout from "@/components/StatReadout.vue";
import Tip from "@/components/Tip.vue";
import { useAsync } from "@/composables/useAsync";
import { engineLabel, formatPercent, formatRelative, verdictTone } from "@/utils/labels";

const router = useRouter();
const state = useAsync(() => api.overview());
const data = ref<PlatformOverview | null>(null);

const llmNote = computed(() => {
  const llm = data.value?.llm;
  if (!llm) return "";
  if (!llm.available) {
    return "未配置 API Key：用例链路自动降级为纯规则引擎，报告链路需要配置后才能生成。";
  }
  return `来源：${llm.source === "runtime" ? "界面覆盖" : ".env 基线"} · ${llm.base_url}`;
});

onMounted(async () => {
  const result = await state.run();
  if (result) data.value = result;
});
</script>

<template>
  <div class="stack">
    <ErrorNote
      v-if="state.error.value"
      title="总览数据没有取到"
      :message="state.error.value"
      :code="state.code.value"
      recovery="确认后端已启动（python run.py），然后重试。界面其余功能不依赖这一页。"
      @retry="state.run().then((r) => r && (data = r))"
    />

    <template v-if="data">
      <!-- 刻度带：平台的四个读数，一次编排 -->
      <section class="strip">
        <div class="strip__head">
          <div>
            <p class="strip__name">{{ data.platform.name }}</p>
            <p class="strip__ver mono">v{{ data.platform.version }} · 单机 / 内网部署</p>
          </div>
          <div class="spacer" />
          <span class="chip" :class="data.llm.available ? 'chip--pass' : 'chip--warn'">
            {{ data.llm.available ? "推理引擎已启用" : "推理引擎未启用" }}
          </span>
          <Tip :text="llmNote" :marked="false">
            <span class="chip chip--ghost mono">{{ data.llm.provider }} · {{ data.llm.model }}</span>
          </Tip>
        </div>

        <div class="strip__grid">
          <StatReadout
            label="文档"
            :value="data.counts.documents"
            hint="已上传并解析成功的需求文档数量"
          />
          <StatReadout
            label="结构化需求"
            :value="data.counts.requirements"
            hint="解析出的需求模型数量（每份文档一份）"
          />
          <StatReadout
            label="用例集"
            :value="data.counts.suites"
            hint="每次生成产生的用例集数量"
          />
          <StatReadout
            label="用例总数"
            :value="data.counts.cases"
            hint="最近 200 份用例集的用例合计"
            tone="glacier"
          />
          <StatReadout
            label="测试报告"
            :value="data.counts.reports"
            hint="已归档的测试报告数量"
          />
          <StatReadout
            label="自动化资产"
            :value="data.counts.automation_artifacts"
            hint="已生成的受控 pytest 项目版本数"
          />
          <StatReadout
            label="执行记录"
            :value="data.counts.test_runs"
            hint="已回收的 JUnit 运行记录数"
          />
          <StatReadout
            label="待跟进"
            :value="data.counts.work_items_open"
            hint="未完成的工作任务数"
            :tone="data.counts.work_items_overdue ? 'warn' : 'default'"
          />
        </div>
      </section>

      <!-- 两条链路 -->
      <div class="lanes">
        <article class="lane lane--case">
          <header class="lane__head">
            <span class="lane__mark"><AppIcon name="sparkle" :size="19" /></span>
            <div>
              <h2 class="lane__title">用例生成</h2>
              <p class="lane__sub">需求文档 → 结构化需求 → 等价类 / 边界值 / 场景法 → 用例集</p>
            </div>
          </header>

          <ul class="lane__facts">
            <li>
              <span class="lane__k">设计方法</span>
              <span class="lane__v">
                <template v-for="(method, index) in data.capabilities.methods.filter((m) => m.implemented)" :key="method.name">
                  <span>{{ method.label }}</span><span v-if="index < data.capabilities.methods.filter((m) => m.implemented).length - 1" class="lane__sep">·</span>
                </template>
              </span>
            </li>
            <li>
              <span class="lane__k">导出格式</span>
              <span class="lane__v">{{ data.capabilities.export_formats.map((f) => f.label).join(" · ") }}</span>
            </li>
            <li>
              <span class="lane__k">最近用例集</span>
              <span class="lane__v mono">
                {{
                  data.recent.suites[0]
                    ? `${data.recent.suites[0].stats.total} 条 · ${engineLabel(data.recent.suites[0].generation_meta)} · ${formatRelative(data.recent.suites[0].created_at)}`
                    : "尚无"
                }}
              </span>
            </li>
          </ul>

          <div class="lane__foot">
            <el-button type="primary" @click="router.push('/generate')">
              <AppIcon name="sparkle" :size="15" />
              开始生成用例
            </el-button>
            <el-button text @click="router.push('/suites')">查看用例集</el-button>
          </div>
        </article>

        <article class="lane lane--report">
          <header class="lane__head">
            <span class="lane__mark"><AppIcon name="chart" :size="19" /></span>
            <div>
              <h2 class="lane__title">测试报告</h2>
              <p class="lane__sub">执行数据 → 确定性指标 → AI 归纳与建议 → 存档 / 趋势 / 导出</p>
            </div>
          </header>

          <ul class="lane__facts">
            <li>
              <span class="lane__k">指标口径</span>
              <span class="lane__v">通过率 · 执行率 · 缺陷分布 · 发版判定</span>
            </li>
            <li>
              <span class="lane__k">导出格式</span>
              <span class="lane__v">Markdown · HTML · Word · JSON</span>
            </li>
            <li>
              <span class="lane__k">最近报告</span>
              <span class="lane__v mono">
                {{ data.recent.reports[0] ? `${data.recent.reports[0].verdict_label} · ${formatRelative(data.recent.reports[0].created_at)}` : "尚无" }}
              </span>
            </li>
          </ul>

          <div class="lane__foot">
            <el-button type="primary" @click="router.push('/report')">
              <AppIcon name="chart" :size="15" />
              生成测试报告
            </el-button>
            <el-button text @click="router.push('/report/archive')">查看存档</el-button>
          </div>

          <p v-if="!data.report.llm_configured" class="lane__warn">
            未配置大模型：指标仍可计算并导出，但 AI 归纳不可用。去
            <RouterLink to="/settings">大模型与阈值</RouterLink> 填写 API Key。
          </p>
        </article>
      </div>

      <section class="delivery-band">
        <div class="delivery-band__head">
          <span class="delivery-band__mark"><AppIcon name="route" :size="19" /></span>
          <div>
            <h2 class="lane__title">交付工作台</h2>
            <p class="lane__sub">接口用例 → pytest 资产 → JUnit 结果 → 跟进事项与提醒</p>
          </div>
          <div class="spacer" />
          <span class="chip" :class="data.counts.work_items_overdue ? 'chip--fail' : 'chip--ghost'">
            逾期 {{ data.counts.work_items_overdue }}
          </span>
        </div>
        <div class="delivery-band__facts">
          <div>
            <span class="label">今日事项</span>
            <strong class="mono">{{ data.recent.work_summary.today }}</strong>
          </div>
          <div>
            <span class="label">收件箱</span>
            <strong class="mono">{{ data.recent.work_summary.inbox }}</strong>
          </div>
          <div>
            <span class="label">即将到期</span>
            <strong class="mono">{{ data.recent.work_summary.upcoming }}</strong>
          </div>
          <div class="delivery-band__recent">
            <span class="label">最近跟进</span>
            <span>{{ data.recent.work_items[0]?.title || "还没有待办，记下一条下一步。" }}</span>
          </div>
          <el-button type="primary" @click="router.push('/workspace')">
            <AppIcon name="route" :size="15" />
            打开交付工作台
          </el-button>
        </div>
      </section>

      <!-- 最近动态 -->
      <div class="grid grid--3">
        <SectionCard title="最近文档" sub="上传即解析，可随时回溯原文" icon="doc" flush>
          <template #actions>
            <el-button size="small" text @click="router.push('/documents')">全部</el-button>
          </template>
          <ul v-if="data.recent.documents.length" class="feed">
            <li v-for="doc in data.recent.documents.slice(0, 4)" :key="doc.doc_id">
              <button type="button" class="feed__item" @click="router.push('/documents')">
                <span class="feed__name">{{ doc.filename }}</span>
                <span class="feed__meta mono">
                  {{ doc.char_count }} 字 · {{ formatRelative(doc.created_at) }}
                </span>
              </button>
            </li>
          </ul>
          <EmptyState
            v-else
            icon="doc"
            title="还没有上传过需求文档"
            reason="上传 .docx / .pdf / .md / .txt 后会自动解析成结构化需求，作为用例生成的输入。"
            action-label="去上传"
            @action="router.push('/generate')"
          />
        </SectionCard>

        <SectionCard title="最近用例集" sub="带完整统计口径与导出" icon="cases" flush>
          <template #actions>
            <el-button size="small" text @click="router.push('/suites')">全部</el-button>
          </template>
          <ul v-if="data.recent.suites.length" class="feed">
            <li v-for="suite in data.recent.suites.slice(0, 4)" :key="suite.suite_id">
              <button
                type="button"
                class="feed__item"
                :title="`由「${suite.doc_title || suite.doc_id}」生成 · 需求 ${suite.doc_id}`"
                @click="router.push(`/suites/${suite.suite_id}`)"
              >
                <span class="feed__name">{{ suite.doc_title || "未命名用例集" }}</span>
                <span class="feed__meta mono">
                  {{ suite.stats.total }} 条 · {{ engineLabel(suite.generation_meta) }} ·
                  {{ formatRelative(suite.created_at) }}
                </span>
              </button>
            </li>
          </ul>
          <EmptyState
            v-else
            icon="cases"
            title="还没有生成过用例集"
            reason="在「用例生成」里粘贴或上传需求，选择设计方法后即可生成，并导出 Excel 四表。"
            action-label="去生成"
            @action="router.push('/generate')"
          />
        </SectionCard>

        <SectionCard title="最近报告" sub="指标由代码算，判断由模型写" icon="chart" flush>
          <template #actions>
            <el-button size="small" text @click="router.push('/report/archive')">全部</el-button>
          </template>
          <ul v-if="data.recent.reports.length" class="feed">
            <li v-for="report in data.recent.reports.slice(0, 4)" :key="report.id">
              <button type="button" class="feed__item" @click="router.push(`/report/archive/${report.id}`)">
                <span class="feed__name">{{ report.title || "未命名报告" }}</span>
                <span class="feed__meta mono">
                  <span class="feed__verdict" :data-tone="verdictTone(report.verdict)">
                    {{ report.verdict_label }}
                  </span>
                  · {{ report.pass_rate === null ? "—" : formatPercent(report.pass_rate) }}
                  · {{ formatRelative(report.created_at) }}
                </span>
              </button>
            </li>
          </ul>
          <EmptyState
            v-else
            icon="chart"
            title="还没有生成过测试报告"
            reason="把跑完的执行数据（JSON 或纯文本）粘贴进报告工作台，几秒内得到一份可归档的报告。"
            action-label="去生成报告"
            @action="router.push('/report')"
          />
        </SectionCard>
      </div>

    </template>

    <div v-else-if="state.loading.value" class="grid grid--3">
      <div v-for="n in 3" :key="n" class="card"><el-skeleton :rows="5" animated class="skel" /></div>
    </div>
  </div>
</template>

<style scoped>
.strip {
  background: var(--ice-0);
  border: 1px solid var(--ice-3);
  border-radius: var(--radius-lg);
  padding: var(--s4) var(--s5) var(--s5);
}

.strip__head {
  display: flex;
  align-items: center;
  gap: var(--s3);
  padding-bottom: var(--s3);
  border-bottom: 1px solid var(--ice-3);
}

.strip__name {
  font-size: var(--fs-md);
  font-weight: 600;
  letter-spacing: -0.015em;
}

.strip__ver {
  font-size: var(--fs-xs);
  color: var(--ink-3);
}

.strip__grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s4);
  padding-top: var(--s4);
}

@media (max-width: 1280px) {
  .strip__grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

@media (max-width: 700px) {
  .strip__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

/* --- 两条链路 ------------------------------------------------- */
.lanes {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--gap-grid);
}

@media (max-width: 1080px) {
  .lanes {
    grid-template-columns: minmax(0, 1fr);
  }
}

.lane {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--s4);
  padding: var(--s5);
  border-radius: var(--radius-lg);
  border: 1px solid var(--ice-3);
  background: linear-gradient(158deg, var(--ice-0) 0%, var(--lane-wash) 100%);
  overflow: hidden;
}

.lane--case {
  --lane-wash: color-mix(in srgb, var(--glacier) 9%, var(--ice-1));
}

.lane--report {
  --lane-wash: color-mix(in srgb, var(--glacier) 16%, var(--ice-1));
}

.lane::before {
  content: "";
  position: absolute;
  inset: 0;
  background: radial-gradient(
    520px circle at 108% -12%,
    color-mix(in srgb, var(--glacier) 12%, transparent),
    transparent 62%
  );
  pointer-events: none;
}

.lane__head {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--s3);
}

.lane__mark {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  flex: none;
  border-radius: 13px;
  background: var(--ice-0);
  border: 1px solid var(--ice-3);
  color: var(--glacier-deep);
}

.lane__title {
  font-size: var(--fs-lg);
  font-weight: 600;
  letter-spacing: -0.02em;
}

.lane__sub {
  font-size: var(--fs-xs);
  color: var(--ink-3);
  line-height: 1.6;
}

.lane__facts {
  position: relative;
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s2);
}

.lane__facts li {
  display: grid;
  grid-template-columns: 84px 1fr;
  gap: var(--s3);
  align-items: baseline;
  padding-bottom: var(--s2);
  border-bottom: 1px solid color-mix(in srgb, var(--ice-4) 60%, transparent);
}

.lane__k {
  font-size: var(--fs-2xs);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  color: var(--ink-3);
}

.lane__v {
  font-size: var(--fs-sm);
  color: var(--ink-1);
}

.lane__sep {
  margin: 0 6px;
  color: var(--ice-5);
}

.lane__foot {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--s2);
  margin-top: auto;
}

.lane__warn {
  position: relative;
  font-size: var(--fs-xs);
  line-height: 1.65;
  color: var(--warn);
}

/* --- 交付闭环 ------------------------------------------------ */
.delivery-band {
  padding: var(--s4) var(--s5);
  border: 1px solid var(--glacier-tint);
  border-radius: var(--radius-lg);
  background: linear-gradient(106deg, var(--ice-0), var(--glacier-wash));
}

.delivery-band__head {
  display: flex;
  align-items: center;
  gap: var(--s3);
}

.delivery-band__mark {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  flex: none;
  border: 1px solid var(--glacier-tint);
  border-radius: 12px;
  background: var(--ice-0);
  color: var(--glacier-deep);
}

.delivery-band__facts {
  display: grid;
  grid-template-columns: repeat(3, minmax(86px, auto)) minmax(220px, 1fr) auto;
  align-items: center;
  gap: var(--s4);
  margin-top: var(--s4);
  padding-top: var(--s4);
  border-top: 1px solid var(--glacier-tint);
}

.delivery-band__facts > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.delivery-band__facts strong {
  font-size: var(--fs-xl);
}

.delivery-band__recent span:last-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ink-1);
  font-size: var(--fs-sm);
}

@media (max-width: 900px) {
  .delivery-band__facts {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .delivery-band__recent {
    grid-column: 1 / -1;
  }

  .delivery-band__facts :deep(.el-button) {
    grid-column: 1 / -1;
    justify-self: start;
  }
}

/* --- 动态列表 ------------------------------------------------ */
.feed {
  list-style: none;
  margin: 0;
  padding: 0;
}

.feed li + li {
  border-top: 1px solid var(--ice-3);
}

.feed__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  padding: 10px var(--s4);
  border: none;
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease);
}

.feed__item:hover {
  background: var(--glacier-wash);
}

.feed__name {
  font-size: var(--fs-sm);
  font-weight: 500;
  color: var(--ink-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.feed__meta {
  font-size: 10.5px;
  color: var(--ink-3);
}

.feed__verdict[data-tone="pass"] {
  color: var(--pass);
}

.feed__verdict[data-tone="warn"] {
  color: var(--warn);
}

.feed__verdict[data-tone="fail"] {
  color: var(--fail);
}

.skel {
  padding: var(--s5);
}
</style>

