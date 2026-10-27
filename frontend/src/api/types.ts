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
  evidence_quotes: string[];
  claim_status: ClaimStatus;
  uncertainty_reason: string;
}

export type ClaimStatus = "verified" | "inferred" | "rejected";

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
  evidence_quotes: string[];
  claim_status: ClaimStatus;
  uncertainty_reason: string;
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
  prompt_id: string;
  prompt_version: string;
  prompt_temperature: number | null;
  prompt_runs: Record<string, unknown>[];
  validation_failures: string[];
  injection_warnings: string[];
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
  evidence_quotes: string[];
  claim_status: ClaimStatus;
  uncertainty_reason: string;
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
  /** 本次生成阶段实际调用模型的次数（0 = 纯规则引擎）。 */
  llm_calls: number;
  fallback_used: boolean;
  warnings: string[];
  /** 大模型对规则产出的复核意见（只提意见，不自动改写用例）。 */
  review_findings: ReviewFinding[];
  elapsed_ms: number;
  prompt_runs: Record<string, unknown>[];
  validation_failures: string[];
  unreviewed_requirements: string[];
  evidence_counts: Record<string, number>;
}

/** 大模型复核规则用例时给出的一条意见。 */
export interface ReviewFinding {
  severity: string;
  requirement_id: string;
  requirement_title: string;
  target: string;
  target_type: string;
  target_id: string;
  issue: string;
  suggestion: string;
  evidence_quotes: string[];
  claim_status: ClaimStatus;
  uncertainty_reason: string;
}

export interface TestCaseSuite {
  suite_id: string;
  doc_id: string;
  doc_title: string;
  /** 同一条需求下的第几个版本（V2.0 起由后端分配，0 表示未分配）。 */
  revision: number;
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
  /** 文档里发现的图片张数（V2.0 多模态 OCR）。 */
  image_count: number;
  /** 其中成功识别出内容的张数。 */
  image_recognized: number;
  images: DocumentAssetBrief[];
}

/** 文档里的图片（列表视图：带预览、不带全文）。 */
export interface DocumentAssetBrief {
  index: number;
  filename: string;
  mime: string;
  size_bytes: number;
  /** docx / pdf / pdf-page / upload */
  source: string;
  anchor: string;
  /** pending / recognized / empty / skipped / unavailable */
  status: string;
  extractor: string;
  /** text / description / mixed / none */
  kind: string;
  confidence: number | null;
  /** 内容重复时复用第几张图片的识别结果（0 表示无）。 */
  reused_from: number;
  text_preview: string;
  message: string;
}

export interface VisionCapabilities {
  provider: string;
  mode: string;
  extractor: string;
  label: string;
  available: boolean;
  kind: string;
  degraded_reason: string;
  max_images_per_doc: number;
  local_ocr_backend: string;
  local_ocr_hint: string;
  supported: string[];
}

export interface VisionProviderOption {
  name: string;
  label: string;
  description: string;
  requires_key: boolean;
  requires_url: boolean;
  allow_model: boolean;
  allow_mode: boolean;
}

export interface VisionModeOption {
  value: string;
  label: string;
  description: string;
}

export interface VisionConfigInfo {
  provider: string;
  mode: string;
  model: string;
  base_url: string;
  api_key_configured: boolean;
  api_key_masked: string;
  cloud_url_configured: boolean;
  ocr_backend: string;
  languages: string;
  max_images: number;
  max_side: number;
  min_pixels: number;
  extractor: string;
  label: string;
  kind: string;
  available: boolean;
  degraded_reason: string;
  local_ocr_backend: string;
  local_ocr_hint: string;
  source: string;
  overridden_fields: string[];
  env_defaults: Record<string, unknown>;
  providers: VisionProviderOption[];
  modes: VisionModeOption[];
}

export interface VisionConfigPayload {
  provider?: string;
  mode?: string;
  model?: string;
  base_url?: string;
  /** 省略=沿用现有 Key；空字符串=清除已保存的 Key */
  api_key?: string;
  cloud_url?: string;
  cloud_key?: string;
  ocr_backend?: string;
  languages?: string;
  max_images?: number;
  max_side?: number;
  min_pixels?: number;
}

export interface VisionTestResult {
  ok: boolean;
  provider: string;
  extractor: string;
  mode: string;
  elapsed_ms: number;
  message: string;
  sample: string;
}

/* ================= 覆盖率分析（V2.0 S4） ================= */

export interface CoverageItem {
  requirement_id: string;
  requirement_title: string;
  target: string;
  detail: string;
}

export interface CoverageDimension {
  key: string;
  label: string;
  total: number;
  covered: number;
  ratio: number;
  note: string;
  gaps: CoverageItem[];
}

export interface CoverageReport {
  doc_id: string;
  doc_title: string;
  suite_id: string;
  dimensions: CoverageDimension[];
  overall_ratio: number;
  summary: string;
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

/* ================= 接口测试资产（V2.2） ================= */

export interface ApiServer {
  url: string;
  description: string;
}

export interface ApiSecurityScheme {
  name: string;
  type: string;
  scheme: string;
  location: string;
  parameter_name: string;
  bearer_format: string;
  description: string;
}

export interface ApiParameter {
  name: string;
  location: "path" | "query" | "header" | "cookie";
  required: boolean;
  description: string;
  deprecated: boolean;
  example: unknown;
  schema: Record<string, unknown>;
  source_ref: string;
}

export interface ApiMediaType {
  content_type: string;
  schema: Record<string, unknown>;
  example: unknown;
  examples: Record<string, unknown>;
  source_ref: string;
}

export interface ApiRequestBody {
  required: boolean;
  description: string;
  content: ApiMediaType[];
  source_ref: string;
}

export interface ApiResponseDefinition {
  status_code: string;
  description: string;
  content: ApiMediaType[];
  headers: ApiParameter[];
  source_ref: string;
}

export interface ApiOperation {
  operation_id: string;
  method: string;
  path: string;
  summary: string;
  description: string;
  tags: string[];
  deprecated: boolean;
  parameters: ApiParameter[];
  request_body: ApiRequestBody | null;
  responses: ApiResponseDefinition[];
  security: Record<string, string[]>[];
  servers: ApiServer[];
  requirement_ids: string[];
  source_ref: string;
  warnings: string[];
}

export interface ApiSpecStats {
  operations: number;
  cases: number;
  positive_cases: number;
  negative_cases: number;
  contract_assertions: number;
  manual_assertions: number;
  operation_gaps: number;
}

export interface ApiReviewFinding {
  severity: "info" | "warning";
  kind: "case_gap" | "assertion_gap" | "documentation";
  operation_id: string;
  target: string;
  issue: string;
  suggestion: string;
  source_ref: string;
  claim_status: "inferred" | "verified" | "rejected";
  uncertainty_reason: string;
}

export interface ApiReviewMeta {
  requested: boolean;
  used: boolean;
  status: "running" | "completed" | "failed";
  provider: string;
  model: string;
  prompt_id: string;
  prompt_version: string;
  temperature: number | null;
  llm_calls: number;
  reviewed_operations: number;
  elapsed_ms: number;
  warnings: string[];
}

export interface ApiReviewResult {
  spec_id: string;
  findings: ApiReviewFinding[];
  meta: ApiReviewMeta;
  created_at: string;
}

export interface ApiSpec {
  spec_id: string;
  title: string;
  version: string;
  openapi_version: string;
  description: string;
  source_file: string;
  source_format: string;
  source_hash: string;
  size_bytes: number;
  servers: ApiServer[];
  security_schemes: ApiSecurityScheme[];
  operations: ApiOperation[];
  stats: ApiSpecStats;
  ai_review: ApiReviewResult | null;
  warnings: string[];
  created_at: string;
}

export type ApiSpecSummary = Omit<
  ApiSpec,
  "servers" | "security_schemes" | "operations" | "source_hash" | "ai_review"
>;

export interface ExecutionSpec {
  method: string;
  url: string;
  headers: Record<string, string>;
  query: Record<string, string>;
  path_params: Record<string, string>;
  cookies: Record<string, string>;
  body: unknown;
  body_kind: string;
  environment_variables: {
    name: string;
    description: string;
    secret: boolean;
  }[];
}

export interface ApiAssertion {
  kind: "status" | "header" | "json";
  path: string;
  operator: string;
  expected: unknown;
  description: string;
  source_ref: string;
  status: "defined" | "manual";
}

export interface ApiCaseSpec {
  case_id: string;
  spec_id: string;
  operation_id: string;
  title: string;
  method: string;
  path: string;
  category: "positive" | "negative" | "boundary" | "security" | "contract";
  priority: Priority;
  preconditions: string[];
  execution: ExecutionSpec;
  assertions: ApiAssertion[];
  requirement_ids: string[];
  tags: string[];
  source_ref: string;
  warnings: string[];
  created_at: string;
}

export interface ApiCaseCollection {
  spec_id: string;
  operation_id: string | null;
  cases: ApiCaseSpec[];
}

export interface ApiImportResult {
  spec: ApiSpec;
  cases: ApiCaseSpec[];
  warnings: string[];
}

/* ================= 自动化交付与工作收件箱（V2.3） ================= */

export interface ValidationIssue {
  code: string;
  message: string;
  path: string;
}

export interface GeneratedFile {
  path: string;
  content: string;
  media_type: string;
}

export interface AutomationArtifactSummary {
  artifact_id: string;
  spec_id: string;
  spec_title: string;
  parent_artifact_id: string | null;
  source_review_id: string | null;
  revision: number;
  framework: string;
  template_version: string;
  case_count: number;
  operation_count: number;
  file_count: number;
  total_bytes: number;
  status: "validated" | "rejected";
  validation_errors: ValidationIssue[];
  warnings: string[];
  change_summary: string[];
  created_at: string;
}

export interface AutomationArtifact extends Omit<
  AutomationArtifactSummary,
  "case_count" | "operation_count" | "file_count" | "total_bytes"
> {
  case_ids: string[];
  operation_ids: string[];
  files: GeneratedFile[];
}

export interface CaseResult {
  case_id: string | null;
  name: string;
  classname: string;
  status: "passed" | "failed" | "error" | "skipped";
  duration_ms: number;
  operation_id: string | null;
  message: string;
  stdout: string;
  stderr: string;
}

export interface TestRunSummary {
  run_id: string;
  artifact_id: string | null;
  spec_id: string | null;
  source_file: string;
  total: number;
  passed: number;
  failed: number;
  errors: number;
  skipped: number;
  matched: number;
  unmatched: number;
  pass_rate: number;
  duration_ms: number;
  warnings: string[];
  created_at: string;
}

export interface TestRun extends TestRunSummary {
  framework: string;
  source_hash: string;
  cases: CaseResult[];
  unmatched_cases: CaseResult[];
  raw_xml: string;
}

export interface JobEvent {
  event_id: string;
  trace_id: string;
  action: string;
  status: string;
  artifact_id: string | null;
  run_id: string | null;
  work_item_id: string | null;
  message: string;
  created_at: string;
}

export type AutomationAIKind =
  | "operation_gap"
  | "failure_assertion"
  | "fixture_recipe"
  | "script_review";

export interface AIAssertionProposal {
  kind: "status" | "header" | "json";
  path: string;
  operator: string;
  expected: unknown;
  description: string;
  source_ref: string;
}

export interface AIRequestProposal {
  query: Record<string, unknown> | null;
  path_params: Record<string, unknown> | null;
  headers: Record<string, unknown> | null;
  cookies: Record<string, unknown> | null;
  body: unknown;
}

export interface AIApiCaseProposal {
  base_case_id: string;
  operation_id: string;
  title: string;
  category: "positive" | "negative" | "boundary" | "security" | "contract";
  priority: WorkItemPriority;
  request: AIRequestProposal | null;
  assertions: AIAssertionProposal[];
  preconditions: string[];
  tags: string[];
  source_ref: string;
}

export interface AutomationAIFinding {
  finding_id: string;
  category:
    | "operation_coverage"
    | "failure_assertion"
    | "fixture_recipe"
    | "script_review";
  severity: "info" | "warning";
  operation_id: string | null;
  case_id: string | null;
  target: string;
  issue: string;
  suggestion: string;
  rationale: string;
  source_ref: string;
  claim_status: "inferred";
  disposition: "pending" | "accepted" | "rejected";
  proposed_assertion: AIAssertionProposal | null;
  proposed_case: AIApiCaseProposal | null;
}

export interface FixtureEnvironmentVariable {
  name: string;
  description: string;
  secret: boolean;
  placeholder: string;
}

export interface FixtureDefinition {
  name: string;
  purpose: string;
  setup: string[];
  data: Record<string, unknown>;
}

export interface TestDataRow {
  case_id: string;
  title: string;
  data: Record<string, unknown>;
  notes: string;
}

export interface AutomationFixtureRecipe {
  summary: string;
  environment_variables: FixtureEnvironmentVariable[];
  fixtures: FixtureDefinition[];
  test_data: TestDataRow[];
  preconditions: string[];
  execution_notes: string[];
  warnings: string[];
}

export interface AutomationAIMeta {
  requested: boolean;
  used: boolean;
  status: "running" | "completed" | "failed";
  provider: string;
  model: string;
  prompt_id: string;
  prompt_version: string;
  temperature: number | null;
  llm_calls: number;
  elapsed_ms: number;
  warnings: string[];
}

export interface AutomationAIReview {
  review_id: string;
  kind: AutomationAIKind;
  spec_id: string;
  artifact_id: string | null;
  run_id: string | null;
  focus: string;
  status: "running" | "completed" | "failed";
  summary: string;
  findings: AutomationAIFinding[];
  recipe: AutomationFixtureRecipe | null;
  decision: "pending" | "accepted" | "rejected";
  context: Record<string, unknown>;
  meta: AutomationAIMeta;
  applied_artifact_id: string | null;
  applied_at: string | null;
  created_at: string;
  updated_at: string;
}

export type WorkItemType = "note" | "task";
export type WorkItemStatus = "inbox" | "todo" | "doing" | "done" | "archived";
export type WorkItemPriority = "P0" | "P1" | "P2" | "P3";
export type ResourceType =
  | "document"
  | "requirement"
  | "suite"
  | "api_spec"
  | "test_run"
  | "report"
  | "external";

export interface WorkItemLink {
  resource_type: ResourceType;
  resource_id: string;
  label: string;
  href: string;
}

export interface WorkItem {
  work_item_id: string;
  item_type: WorkItemType;
  title: string;
  body: string;
  status: WorkItemStatus;
  priority: WorkItemPriority;
  due_at: string | null;
  remind_at: string | null;
  reminded_at: string | null;
  tags: string[];
  pinned: boolean;
  links: WorkItemLink[];
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface WorkItemCreate {
  item_type?: WorkItemType;
  title: string;
  body?: string;
  status?: WorkItemStatus;
  priority?: WorkItemPriority;
  due_at?: string | null;
  remind_at?: string | null;
  tags?: string[];
  pinned?: boolean;
  links?: WorkItemLink[];
}

export interface WorkItemUpdate {
  title?: string;
  body?: string;
  status?: WorkItemStatus;
  priority?: WorkItemPriority;
  due_at?: string | null;
  remind_at?: string | null;
  tags?: string[];
  pinned?: boolean;
  links?: WorkItemLink[];
}

export interface WorkItemSummary {
  inbox: number;
  today: number;
  upcoming: number;
  overdue: number;
  open_tasks: number;
  completed: number;
  due_reminders: number;
  recent_notes: WorkItem[];
  recent_tasks: WorkItem[];
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
  /** 图片识别通道状态（V2.0 多模态 OCR）。 */
  vision: VisionCapabilities;
  /** 服务端生效的设计引擎上限（界面据此显示默认值）。 */
  limits: Record<string, number>;
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

export interface PromptInfo {
  prompt_id: string;
  version: string;
  task: string;
  input_boundary: string;
  temperature: number;
  model_scope: string;
  change_log: string[];
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
  prompt_id: string;
  prompt_version: string;
  prompt_temperature: number | null;
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

/* ================= v3.0 平台治理 ================= */

export interface ProjectQuota {
  max_documents: number;
  max_suites: number;
  max_jobs: number;
}

export interface Project {
  project_id: string;
  key: string;
  name: string;
  description: string;
  status: "active" | "archived";
  quota: ProjectQuota;
  created_at: string;
  updated_at: string;
}

export interface ProjectContextInfo {
  project: Project;
  actor: string;
  role: "owner" | "admin" | "member" | "viewer";
  auth_enabled: boolean;
  isolation_enabled: boolean;
  storage_backend: string;
}

export interface AuditEvent {
  audit_id: string;
  project_id: string;
  actor: string;
  role: string;
  action: string;
  resource_type: string;
  resource_id: string;
  outcome: string;
  trace_id: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface ExternalRequirement {
  external_id: string;
  title: string;
  body: string;
  status: string;
  url: string;
  version: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface IntegrationHealth {
  name: string;
  label: string;
  implemented: boolean;
  configured: boolean;
  available: boolean;
  message: string;
  degraded_reason: string;
}

export interface IntegrationPullResult {
  integration: string;
  fetched: number;
  created: number;
  updated: number;
  requirements: ExternalRequirement[];
  documents: DocumentSummary[];
  warnings: string[];
  created_at: string;
}

export interface IntegrationPushResult {
  integration: string;
  suite_id: string;
  external_ids: string[];
  message: string;
  warnings: string[];
  created_at: string;
}

export interface ExternalStatus {
  external_id: string;
  status: string;
  title: string;
  updated_at: string;
  url: string;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface Job {
  job_id: string;
  project_id: string;
  kind: string;
  status: JobStatus;
  trace_id: string;
  idempotency_key: string;
  attempt: number;
  max_attempts: number;
  timeout_seconds: number;
  payload_summary: Record<string, unknown>;
  result_summary: Record<string, unknown>;
  error: string;
  created_by: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Schedule {
  schedule_id: string;
  project_id: string;
  name: string;
  job_kind: string;
  interval_seconds: number;
  timezone: string;
  enabled: boolean;
  next_run_at: string | null;
  max_runs: number | null;
  run_count: number;
  last_job_id: string;
  payload_summary: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface AgentRun {
  run_id: string;
  project_id: string;
  agent_kind: string;
  status: string;
  request: string;
  response: string;
  citation_ids: string[];
  tool_call_ids: string[];
  trace_id: string;
  created_by: string;
  started_at: string;
  finished_at: string | null;
  error: string;
}

export interface ToolCall {
  tool_call_id: string;
  project_id: string;
  run_id: string;
  job_id: string;
  tool_name: string;
  status: string;
  arguments_summary: Record<string, unknown>;
  result_summary: Record<string, unknown>;
  error: string;
  trace_id: string;
  started_at: string;
  finished_at: string | null;
}

export interface KnowledgeIndexStats {
  project_id: string;
  sources: number;
  active_sources: number;
  chunks: number;
  indexed: number;
  removed: number;
  degraded_reason: string;
  updated_at: string;
}

export interface KnowledgeCitation {
  citation_id: string;
  source_id: string;
  title: string;
  source_type: string;
  version: string;
  locator: string;
  url: string;
  excerpt: string;
  score: number;
}

export interface KnowledgeSearchResult {
  query: string;
  citations: KnowledgeCitation[];
  total: number;
  degraded_reason: string;
}

export interface AssistantClaim {
  text: string;
  evidence: string;
}

export interface AssistantFactGroup {
  label: string;
  claims: AssistantClaim[];
}

export interface AssistantLink {
  label: string;
  href: string;
  resource_type: string;
  resource_id: string;
}

export interface AssistantWebCitation {
  citation_id: string;
  title: string;
  url: string;
  site_name: string;
  snippet: string;
  summary: string;
  content_excerpt: string;
  published_at: string;
  authority: number;
  rerank_score: number;
  fetched: boolean;
}

export interface AssistantAnswer {
  run_id: string;
  conversation_id: string;
  turn_index: number;
  turn_limit: number;
  context_messages: number;
  status: "answered" | "refused" | "degraded";
  answer: string;
  mode: "deterministic" | "llm_assisted" | "web_assisted";
  current_facts: AssistantFactGroup[];
  knowledge_references: KnowledgeCitation[];
  web_citations: AssistantWebCitation[];
  web_search_used: boolean;
  web_search_status: string;
  model_inferences: AssistantClaim[];
  links: AssistantLink[];
  tool_calls: Record<string, unknown>[];
  warnings: string[];
  degraded_reason: string;
}

export interface AssistantTurn {
  role: "user" | "assistant";
  content: string;
  created_at: string;
  status: "answered" | "refused" | "degraded" | "";
  mode: "deterministic" | "llm_assisted" | "web_assisted" | "";
  knowledge_references: KnowledgeCitation[];
  web_citations: AssistantWebCitation[];
  warnings: string[];
  degraded_reason: string;
}

export interface AssistantConversation {
  conversation_id: string;
  project_id: string;
  title: string;
  turn_count: number;
  web_search_count: number;
  last_web_search_at: string;
  messages: AssistantTurn[];
  created_at: string;
  updated_at: string;
}

export interface AssistantConversationSummary {
  conversation_id: string;
  title: string;
  turn_count: number;
  web_search_count: number;
  updated_at: string;
}

export interface AssistantStatus {
  model_available: boolean;
  model_provider: string;
  model_name: string;
  model_reason: string;
  web_search_available: boolean;
  web_search_provider: string;
  web_search_reason: string;
  max_turns: number;
  context_turns: number;
  context_chars: number;
  rate_limit_per_minute: number;
  web_searches_per_conversation: number;
  web_fetch_limit: number;
  web_fetch_chars: number;
  max_output_tokens: number;
}

export interface ToolCatalogItem {
  name: string;
  description: string;
  readonly: boolean;
}

export interface ModelRouteInfo {
  provider: string;
  model: string;
  task: string;
  strategy: string;
  quality_tier: string;
  cost_tier: string;
  rationale: string;
}

export interface RoutingPolicyInfo {
  configured_strategy: string;
  strategy: string;
  routes: ModelRouteInfo[];
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
    automation_artifacts: number;
    test_runs: number;
    work_items_open: number;
    work_items_overdue: number;
  };
  report: { llm_configured: boolean; thresholds: Record<string, number> };
  recent: {
    documents: DocumentSummary[];
    suites: TestCaseSuiteSummary[];
    reports: ReportSummary[];
    work_items: WorkItem[];
    work_summary: WorkItemSummary;
  };
  capabilities: {
    methods: MethodInfo[];
    export_formats: ExportFormatInfo[];
    integrations: IntegrationInfo[];
    extensions: string[];
  };
}
