/** 领域术语到界面语言的映射，以及全局格式化函数。集中在一处，避免各页各写一套。 */
import type { CaseType, DesignMethod, ExportFormatInfo, MethodInfo, Priority } from "@/api";

/**
 * 生成 / 解析阶段用到的引擎元信息。
 * `GenerationMeta`（llm_provider / llm_model）与 `ParseMeta`（provider / model）
 * 的字段名不同，这里统一收敛，避免每个页面各写一套「大模型增强」这种没有信息量的文案。
 */
export interface EngineMeta {
  llm_used?: boolean;
  fallback_used?: boolean;
  llm_provider?: string;
  llm_model?: string;
  provider?: string;
  model?: string;
}

function engineParts(meta: EngineMeta): { provider: string; model: string } {
  return {
    provider: meta.llm_provider || meta.provider || "",
    model: meta.llm_model || meta.model || "",
  };
}

/**
 * 引擎标签：只写「大模型增强」等于没说。
 * 换个模型结果就会变，复盘「这批用例为什么长这样」时第一个要问的就是它。
 */
export function engineLabel(meta?: EngineMeta): string {
  if (!meta) return "—";
  if (!meta.llm_used) return meta.fallback_used ? "规则引擎（降级）" : "规则引擎";
  const { provider, model } = engineParts(meta);
  return model || provider || "大模型增强";
}

/** 引擎标签的悬停说明：把 provider · model 与降级情况一次说清。 */
export function engineTitle(meta?: EngineMeta): string {
  if (!meta) return "";
  if (!meta.llm_used) {
    return meta.fallback_used
      ? "调用大模型失败，已自动降级为规则引擎（具体原因见详情）"
      : "全程规则引擎：结果确定、可离线复现";
  }
  const { provider, model } = engineParts(meta);
  const used = [provider, model].filter(Boolean).join(" · ");
  return `使用 ${used || "大模型"}${meta.fallback_used ? "（部分降级）" : ""}`;
}

export const METHOD_LABELS: Record<string, string> = {
  equivalence: "等价类划分",
  boundary: "边界值分析",
  scenario: "场景法",
  decision_table: "判定表",
  cause_effect: "因果图",
  orthogonal: "正交实验",
};

export const METHOD_SHORT: Record<string, string> = {
  equivalence: "等价类",
  boundary: "边界值",
  scenario: "场景法",
  decision_table: "判定表",
  cause_effect: "因果图",
  orthogonal: "正交实验",
};

export const METHOD_ORDER: DesignMethod[] = [
  "equivalence",
  "boundary",
  "scenario",
  "decision_table",
  "cause_effect",
  "orthogonal",
];

export const CLAIM_STATUS_LABELS: Record<string, string> = {
  verified: "原文证据已核验",
  inferred: "模型推断待复核",
  rejected: "已拒绝",
};

export const CASE_SOURCE_LABELS: Record<string, string> = {
  rule: "规则引擎",
  llm: "LLM",
  hybrid: "混合",
};

export function claimStatusLabel(value?: string): string {
  return CLAIM_STATUS_LABELS[value ?? ""] ?? value ?? "未标注";
}

export const METHOD_CODES: Record<string, string> = {
  equivalence: "EQ",
  boundary: "BV",
  scenario: "SC",
  decision_table: "DT",
  cause_effect: "CE",
  // 必须与后端 app/design/optimizer.py 的 ID_PREFIX 一致，否则界面显示的方法代码
  // 与用例编号（TC-OR-xxx）对不上。
  orthogonal: "OR",
};

/** 每种设计方法的界面说明（纯展示文案，前端维护）。 */
export const METHOD_NOTES: Record<string, string> = {
  equivalence: "在有效类与无效类里各取代表值，覆盖输入域",
  boundary: "取上下界的 min-1 / min / max / max+1，专抓临界错误",
  scenario: "按主流程、备选流程、异常流各走一遍，串起业务链路",
  decision_table: "多条件组合成表，无关项合并后每条规则一条用例",
  cause_effect: "从业务规则画因与果，异或 / 包含 / 屏蔽约束折算成判定表",
  orthogonal: "多因子多水平取两两覆盖表，用最少用例覆盖水平组合",
};

/**
 * 不指定方法时的默认集合：与后端 `DEFAULT_METHODS` 保持一致。
 * 新方法要显式勾选 —— 默认全选会让一次生成的用例数直接翻倍。
 */
export const DEFAULT_METHODS: DesignMethod[] = ["equivalence", "boundary", "scenario"];

/**
 * 能力真相只有一个来源：后端接口（`/health`、`/testcases/methods`、`/export/formats`）。
 * 下面两份清单**只在后端拉不到时兜底**，不参与"某个能力是否可用"的判断。
 *
 * 这里曾经写过一份「已实现 / 未实现」的硬编码副本，结果 V2.0 把判定表、因果图、
 * 正交实验做完之后，界面还在显示「未实现」并提示「调用会返回 501」——
 * 同一事实存两处，必然会有一处过期。
 */
export const FALLBACK_METHODS: MethodInfo[] = [
  { name: "equivalence", label: "等价类划分", implemented: true, description: "" },
  { name: "boundary", label: "边界值分析", implemented: true, description: "" },
  { name: "scenario", label: "场景法", implemented: true, description: "" },
  { name: "decision_table", label: "判定表", implemented: true, description: "" },
  { name: "cause_effect", label: "因果图", implemented: true, description: "" },
  { name: "orthogonal", label: "正交实验", implemented: true, description: "" },
];

/** 导出格式的兜底清单（`/export/formats` 拉不到时用）。 */
export const FALLBACK_EXPORT_FORMATS: ExportFormatInfo[] = [
  { name: "excel", label: "Excel", media_type: "", extension: "xlsx" },
  { name: "json", label: "JSON", media_type: "", extension: "json" },
  { name: "csv", label: "CSV", media_type: "", extension: "csv" },
  { name: "xmind", label: "XMind", media_type: "", extension: "xmind" },
  { name: "testlink", label: "TestLink XML", media_type: "", extension: "xml" },
];

/** 上传控件 accept 的兜底值（`/health` 拉不到时用）。 */
export const FALLBACK_UPLOAD_EXTENSIONS: string[] = [
  ".docx",
  ".pdf",
  ".xlsx",
  ".xlsm",
  ".txt",
  ".md",
  ".csv",
  ".json",
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
  ".bmp",
  ".tif",
  ".tiff",
];

export const PRIORITY_ORDER: Priority[] = ["P0", "P1", "P2", "P3"];

export const CASE_TYPES: CaseType[] = [
  "功能",
  "边界",
  "异常",
  "场景",
  "安全",
  "性能",
  "兼容性",
];

export function methodLabel(name?: string): string {
  if (!name) return "—";
  return METHOD_LABELS[name] ?? name;
}

export function methodShort(name?: string): string {
  if (!name) return "—";
  return METHOD_SHORT[name] ?? name;
}

export function priorityRank(value: string): number {
  const index = PRIORITY_ORDER.indexOf(value as Priority);
  return index === -1 ? PRIORITY_ORDER.length : index;
}

export const PRIORITY_LABELS: Record<string, string> = {
  P0: "P0 阻断",
  P1: "P1 严重",
  P2: "P2 一般",
  P3: "P3 轻微",
};

/** 优先级用形状 + 文字双通道表达，不靠颜色单独区分。 */
export function priorityTone(priority: string): "p0" | "p1" | "p2" | "p3" {
  const value = priority.toUpperCase();
  if (value === "P0") return "p0";
  if (value === "P1") return "p1";
  if (value === "P2") return "p2";
  return "p3";
}

export const REQUIREMENT_TYPE_LABELS: Record<string, string> = {
  functional: "功能",
  business_rule: "业务规则",
  interface: "接口",
  constraint: "约束",
  non_functional: "非功能",
};

export const DATA_TYPE_LABELS: Record<string, string> = {
  string: "字符串",
  integer: "整数",
  float: "小数",
  boolean: "布尔",
  enum: "枚举",
  date: "日期",
  datetime: "日期时间",
  other: "其它",
};

export function requirementTypeLabel(value?: string): string {
  if (!value) return "—";
  return REQUIREMENT_TYPE_LABELS[value] ?? value;
}

export function dataTypeLabel(value?: string): string {
  if (!value) return "—";
  return DATA_TYPE_LABELS[value] ?? value;
}

export const VERDICT_LABELS: Record<string, string> = {
  pass: "通过",
  conditional: "有条件通过",
  reject: "不建议发版",
  unknown: "无法判定",
};

export function verdictTone(verdict: string): "pass" | "warn" | "fail" | "unknown" {
  if (verdict === "pass") return "pass";
  if (verdict === "conditional") return "warn";
  if (verdict === "reject") return "fail";
  return "unknown";
}

/** 去掉与规范扩展名重复的别名，只用于展示（选文件时的 accept 仍用全量）。 */
const EXTENSION_ALIASES: Record<string, string> = { markdown: "md", text: "txt" };

export function displayExtensions(extensions: string[]): string[] {
  const set = new Set(extensions.map((ext) => ext.toLowerCase()));
  const seen = new Set<string>();
  return extensions.filter((ext) => {
    const canonical = EXTENSION_ALIASES[ext.toLowerCase()];
    if (canonical && set.has(canonical)) return false;
    if (seen.has(ext)) return false;
    seen.add(ext);
    return true;
  });
}
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const exp = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** exp;
  return `${exp === 0 ? value : value.toFixed(1)} ${units[exp]}`;
}

export function formatPercent(ratio: number | null | undefined, digits = 1): string {
  if (ratio === null || ratio === undefined || Number.isNaN(ratio)) return "—";
  return `${(ratio * 100).toFixed(digits)}%`;
}

export function percent(part: number, whole: number): string {
  if (!whole) return "—";
  return `${Math.round((part / whole) * 100)}%`;
}

/** 毫秒转可读耗时，用于「耗时 1.2s」这类刻度读数。 */
export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${Math.round(seconds % 60)} s`;
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

/** 与 formatTime 同义，保留旧调用点。 */
export const formatDateTime = formatTime;

export function formatRelative(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const diff = Date.now() - date.getTime();
  if (diff < 60_000) return "刚刚";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)} 天前`;
  return formatTime(value);
}



