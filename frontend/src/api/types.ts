export interface ApiResponse<T> {
  success: boolean;
  code: string;
  message: string;
  data: T | null;
}

export type DesignMethod =
  | "equivalence"
  | "boundary"
  | "scenario"
  | "decision_table"
  | "cause_effect"
  | "orthogonal";

export type Priority = "P0" | "P1" | "P2" | "P3";

export type CaseType =
  | "功能"
  | "边界"
  | "异常"
  | "场景"
  | "安全"
  | "性能"
  | "兼容性";

export interface FieldConstraint {
  name: string;
  label: string;
  data_type: string;
  required: boolean;
  nullable: boolean;
  min_value: number | null;
  max_value: number | null;
  min_length: number | null;
  max_length: number | null;
  enum_values: string[];
  pattern: string | null;
  default: string | null;
  unit: string | null;
  description: string;
}

export interface RequirementItem {
  id: string;
  title: string;
  module: string;
  description: string;
  priority: Priority;
  requirement_type: string;
  fields: FieldConstraint[];
  business_rules: string[];
  preconditions: string[];
  main_flow: string[];
  alternative_flows: string[];
  exceptions: string[];
  acceptance_criteria: string[];
  source_ref: string;
  raw_text: string;
}

export interface ParseMeta {
  provider: string;
  model: string;
  llm_used: boolean;
  fallback_used: boolean;
  fallback_reason: string;
  attempts: number;
  elapsed_ms: number;
  item_count: number;
  warnings: string[];
}

export interface RequirementDoc {
  doc_id: string;
  title: string;
  source_file: string;
  source_type: string;
  version: string;
  summary: string;
  items: RequirementItem[];
  created_at: string;
  parse_meta: ParseMeta;
}

export interface TestStep {
  no: number;
  action: string;
  expected: string;
}

export interface TestCase {
  case_id: string;
  title: string;
  module: string;
  requirement_ids: string[];
  design_method: DesignMethod;
  case_type: CaseType;
  priority: Priority;
  preconditions: string[];
  steps: TestStep[];
  expected_result: string;
  test_data: Record<string, string>;
  tags: string[];
  remarks: string;
  source: string;
  checksum: string;
  covered_methods: DesignMethod[];
}

export interface SuiteStats {
  total: number;
  duplicate_removed: number;
  by_method: Record<string, number>;
  /** 合并用例按「覆盖到的全部方法」重新计数，避免跨方法合并后被少算。 */
  by_covered_method: Record<string, number>;
  by_type: Record<string, number>;
  by_priority: Record<string, number>;
  requirement_coverage: Record<string, number>;
}

export interface GenerationMeta {
  methods: string[];
  llm_used: boolean;
  llm_provider: string;
  llm_model: string;
  fallback_used: boolean;
  warnings: string[];
  elapsed_ms: number;
}

export interface TestCaseSuite {
  suite_id: string;
  doc_id: string;
  doc_title: string;
  methods: DesignMethod[];
  cases: TestCase[];
  stats: SuiteStats;
  generation_meta: GenerationMeta;
  parse_meta: ParseMeta;
  created_at: string;
}

/** 用例集列表项：与 TestCaseSuite 同口径，但**不含 cases 明细**（列表不需要用例内容）。 */
export type TestCaseSuiteSummary = Omit<TestCaseSuite, "cases">;

export interface DocumentSummary {
  doc_id: string;
  filename: string;
  extension: string;
  size_bytes: number;
  char_count: number;
  line_count: number;
  encoding: string;
  parser: string;
  page_count: number | null;
  table_count: number;
  warnings: string[];
  created_at: string;
  preview: string;
  /** 是否已解析出结构化需求（列表页据此把「解析需求」换成「查看需求」）。 */
  has_requirement: boolean;
  /** 已解析的需求条目数，未解析为 0。 */
  requirement_items: number;
  /** 解析阶段的口径快照（哪个 provider / 模型、是否降级）；未解析为 null。 */
  parse_meta: ParseMeta | null;
}

export interface MethodInfo {
  name: string;
  label: string;
  implemented: boolean;
  description: string;
}

export interface ExportFormatInfo {
  name: string;
  label: string;
  media_type: string;
  extension: string;
}

export interface HealthInfo {
  app_name: string;
  version: string;
  status: string;
  llm_provider: string;
  llm_model: string;
  llm_base_url: string;
  llm_available: boolean;
  llm_degraded_reason: string;
  /** env=来自 .env 基线；runtime=被「大模型配置」界面覆盖 */
  llm_source: string;
  methods: MethodInfo[];
  export_formats: ExportFormatInfo[];
  supported_extensions: string[];
}

export interface LLMModelOption {
  value: string;
  label: string;
  base_url: string;
}

export interface LLMProviderOption {
  name: string;
  label: string;
  description: string;
  requires_key: boolean;
  requires_base_url: boolean;
  allow_custom_model: boolean;
  default_base_url: string;
  default_model: string;
  models: LLMModelOption[];
}

export interface LLMConfigInfo {
  provider: string;
  model: string;
  base_url: string;
  api_key_configured: boolean;
  api_key_masked: string;
  timeout: number;
  max_retries: number;
  temperature: number;
  max_tokens: number;
  available: boolean;
  degraded_reason: string;
  /** env=来自 .env 基线；runtime=被界面覆盖 */
  source: string;
  overridden_fields: string[];
  env_defaults: Record<string, unknown>;
  providers: LLMProviderOption[];
}

export interface LLMConfigPayload {
  provider?: string;
  model?: string;
  base_url?: string;
  /** 省略=沿用现有 Key；空字符串=清除已保存的 Key */
  api_key?: string;
  timeout?: number;
  max_retries?: number;
  temperature?: number;
  max_tokens?: number;
}

export interface LLMTestResult {
  ok: boolean;
  provider: string;
  model: string;
  elapsed_ms: number;
  message: string;
  reply: string;
}

export interface LLMModelList {
  source: string;
  message: string;
  models: LLMModelOption[];
}

export interface IntegrationInfo {
  name: string;
  label: string;
  implemented: boolean;
}

export interface GenerateResult {
  requirement_doc: RequirementDoc;
  suite: TestCaseSuite;
  warnings: string[];
}

/* ================= 测试报告域 ================= */

export type Verdict = "pass" | "conditional" | "reject" | "unknown";

export interface CountItem {
  key: string;
  label: string;
  count: number;
}

export interface Defect {
  id: string | null;
  title: string | null;
  priority: string | null;
  module: string | null;
  status: string | null;
  status_raw: string | null;
}

export interface ReportMetrics {
  total: number;
  passed: number;
  failed: number;
  blocked: number;
  skipped: number;
  executed: number;
  pass_rate: number;
  fail_rate: number;
  execution_rate: number;
  effective_pass_rate: number;
  defects_total: number;
  defects_open: number;
  open_p0: number;
  open_p1: number;
  by_priority: CountItem[];
  by_status: CountItem[];
  by_module: CountItem[];
  verdict: Verdict;
  verdict_label: string;
  verdict_reasons: string[];
}

export interface MetricsResult {
  metrics: ReportMetrics | null;
  defects: Defect[];
  version: string | null;
  source_format: "json" | "text";
  warnings: string[];
}

export interface AnalyzeRequest {
  test_data: string;
  instruction?: string;
  model?: string | null;
  temperature?: number | null;
  title?: string | null;
  save?: boolean;
}

export interface AnalyzeResponse {
  id: string | null;
  report: string;
  model: string;
  provider: string;
  metrics: ReportMetrics | null;
  warnings: string[];
  version: string | null;
  created_at: string;
  elapsed_ms: number;
  usage: Record<string, unknown> | null;
}

export interface ReportSummary {
  id: string;
  title: string | null;
  version: string | null;
  model: string;
  provider: string;
  created_at: string;
  elapsed_ms: number;
  verdict: Verdict;
  verdict_label: string;
  pass_rate: number | null;
  total: number | null;
  failed: number | null;
  blocked: number | null;
  excerpt: string;
}

export interface ReportDetail extends ReportSummary {
  instruction: string;
  source_data: string;
  report: string;
  metrics: ReportMetrics | null;
  defects: Defect[];
  usage: Record<string, unknown> | null;
  warnings: string[];
}

export interface ReportListResponse {
  items: ReportSummary[];
  total: number;
}

/** 批量删除的统一回执：deleted 为实际删除数，missing 为未找到/已删除的 ID。 */
export interface BatchDeleteResult {
  deleted: number;
  missing: string[];
}

export interface TrendPoint {
  id: string;
  label: string;
  created_at: string;
  pass_rate: number;
  total: number;
  failed: number;
  blocked: number;
  verdict: Verdict;
  verdict_label: string;
}

export interface SampleDataset {
  id: string;
  name: string;
  description: string;
  content: string;
}

export interface ThresholdView {
  thresholds: Record<string, number>;
  defaults: Record<string, number>;
  sources: Record<string, string>;
}

export interface ReportStatus {
  llm_configured: boolean;
  provider: string;
  model: string;
  base_url: string;
  thresholds: Record<string, number>;
  storage_backend: string;
  storage_path: string;
  report_count: number;
}

export interface ReportLLMTestResult {
  ok: boolean;
  model: string;
  provider: string;
  latency_ms: number;
  message: string;
}

/* ================= 平台总览 ================= */

export interface PlatformOverview {
  platform: { name: string; version: string };
  llm: {
    provider: string;
    model: string;
    base_url: string;
    available: boolean;
    source: string;
  };
  counts: {
    documents: number;
    requirements: number;
    suites: number;
    cases: number;
    reports: number;
  };
  report: { llm_configured: boolean; thresholds: Record<string, number> };
  recent: {
    documents: DocumentSummary[];
    suites: TestCaseSuiteSummary[];
    reports: ReportSummary[];
  };
  capabilities: {
    methods: MethodInfo[];
    export_formats: ExportFormatInfo[];
    integrations: IntegrationInfo[];
    extensions: string[];
  };
}
