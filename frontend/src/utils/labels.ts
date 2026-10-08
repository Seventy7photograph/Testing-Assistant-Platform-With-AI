/** 领域术语到界面语言的映射，以及全局格式化函数。集中在一处，避免各页各写一套。 */
import type { CaseType, DesignMethod, Priority } from "@/api";

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

export const METHOD_CODES: Record<string, string> = {
  equivalence: "EQ",
  boundary: "BV",
  scenario: "SC",
  decision_table: "DT",
  cause_effect: "CE",
  orthogonal: "OG",
};

/** V1.0 已交付的三种设计方法。 */
export const V1_METHODS: DesignMethod[] = ["equivalence", "boundary", "scenario"];

/** 架构中已预留、但当前调用会返回 501 的设计方法。 */
export const RESERVED_METHODS: DesignMethod[] = [
  "decision_table",
  "cause_effect",
  "orthogonal",
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



