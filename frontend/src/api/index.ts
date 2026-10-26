import { del, downloadFile, get, post, put, upload, uploadWithFields } from "./client";

import type {
  AnalyzeRequest,
  AnalyzeResponse,
  ApiCaseCollection,
  ApiImportResult,
  ApiOperation,
  ApiReviewResult,
  ApiSpec,
  ApiSpecSummary,
  AutomationArtifact,
  AutomationArtifactSummary,
  BatchDeleteResult,
  CoverageReport,
  DocumentSummary,
  ExportFormatInfo,
  GenerateResult,
  HealthInfo,
  IntegrationInfo,
  JobEvent,
  LLMConfigInfo,
  LLMConfigPayload,
  LLMModelList,
  LLMTestResult,
  MethodInfo,
  MetricsResult,
  PlatformOverview,
  PromptInfo,
  ReportDetail,
  ReportListResponse,
  ReportLLMTestResult,
  ReportMetrics,
  ReportStatus,
  RequirementDoc,
  SampleDataset,
  TestCaseSuite,
  TestCaseSuiteSummary,
  TestRun,
  TestRunSummary,
  ThresholdView,
  TrendPoint,
  VisionConfigInfo,
  VisionConfigPayload,
  VisionTestResult,
  WorkItem,
  WorkItemCreate,
  WorkItemSummary,
  WorkItemUpdate,
} from "./types";

export interface GeneratePayload {
  doc_id?: string | null;
  text?: string | null;
  title?: string;
  methods: string[];
  use_llm: boolean;
  use_llm_in_design: boolean;
  max_items: number;
  /** 单条需求用例上限；省略则用服务端默认值（/health 的 limits）。 */
  max_cases_per_requirement?: number;
  /**
   * 生成阶段大模型的参与方式（仅在 use_llm_in_design=true 时生效）：
   * scenario=只让场景法补充；review=六种方法都覆盖，模型复核并给意见；enhance=review + 补充用例。
   */
  llm_design_mode?: string;
}

export interface ReportListQuery {
  limit?: number;
  offset?: number;
  q?: string;
  verdict?: string;
}

export const api = {
  /* ---------- 平台 ---------- */
  health: () => get<HealthInfo>("/health"),
  overview: () => get<PlatformOverview>("/overview"),
  integrations: () => get<IntegrationInfo[]>("/integrations"),

  /* ---------- 大模型（两条链路共用） ---------- */
  llmConfig: () => get<LLMConfigInfo>("/llm/config"),
  saveLlmConfig: (payload: LLMConfigPayload) =>
    put<LLMConfigInfo>("/llm/config", payload),
  resetLlmConfig: () => del<LLMConfigInfo>("/llm/config"),
  testLlmConfig: (payload: LLMConfigPayload) =>
    post<LLMTestResult>("/llm/config/test", payload),
  llmModels: (provider?: string, baseUrl?: string) =>
    get<LLMModelList>("/llm/models", {
      ...(provider ? { provider } : {}),
      ...(baseUrl ? { base_url: baseUrl } : {}),
    }),
  prompts: () => get<PromptInfo[]>("/llm/prompts"),

  /* ---------- 图片识别（V2.0 多模态 OCR） ---------- */
  visionConfig: () => get<VisionConfigInfo>("/vision/config"),
  saveVisionConfig: (payload: VisionConfigPayload) =>
    put<VisionConfigInfo>("/vision/config", payload),
  resetVisionConfig: () => del<VisionConfigInfo>("/vision/config"),
  testVisionConfig: () => post<VisionTestResult>("/vision/config/test"),

  /* ---------- 用例生成域 ---------- */
  methods: () => get<MethodInfo[]>("/testcases/methods"),
  exportFormats: () => get<ExportFormatInfo[]>("/export/formats"),

  /* ---------- 接口测试资产（V2.2） ---------- */
  apiSpecs: (limit = 30) => get<ApiSpecSummary[]>("/api-specs", { limit }),
  apiSpec: (specId: string) =>
    get<ApiSpec>(`/api-specs/${encodeURIComponent(specId)}`),
  apiOperations: (specId: string) =>
    get<ApiOperation[]>(`/api-specs/${encodeURIComponent(specId)}/operations`),
  apiOperation: (specId: string, operationId: string) =>
    get<ApiOperation>(
      `/api-specs/${encodeURIComponent(specId)}/operations/${encodeURIComponent(operationId)}`,
    ),
  apiCases: (specId: string, operationId?: string) =>
    get<ApiCaseCollection>(`/api-specs/${encodeURIComponent(specId)}/cases`, {
      ...(operationId ? { operation_id: operationId } : {}),
    }),
  reviewApiSpec: (specId: string) =>
    post<ApiReviewResult>(`/api-specs/${encodeURIComponent(specId)}/review`),
  importApiSpec: (file: File) => upload<ApiImportResult>("/api-specs/import", file),
  exportApiPostman: (specId: string) =>
    downloadFile(`/api-specs/${encodeURIComponent(specId)}/export/postman`),
  deleteApiSpec: (specId: string) =>
    del<{ deleted: boolean; spec_id: string; deleted_cases: number }>(
      `/api-specs/${encodeURIComponent(specId)}`,
    ),

  /* ---------- 自动化交付（V2.3） ---------- */
  automationArtifacts: (specId?: string, limit = 30) =>
    get<AutomationArtifactSummary[]>("/automation/artifacts", {
      limit,
      ...(specId ? { spec_id: specId } : {}),
    }),
  automationArtifact: (artifactId: string) =>
    get<AutomationArtifact>(`/automation/artifacts/${encodeURIComponent(artifactId)}`),
  createAutomationArtifact: (specId: string, caseIds: string[] = []) =>
    post<AutomationArtifact>("/automation/artifacts", {
      spec_id: specId,
      case_ids: caseIds,
    }),
  downloadAutomationArtifact: (artifactId: string) =>
    downloadFile(`/automation/artifacts/${encodeURIComponent(artifactId)}/download`),
  importJunitRun: (file: File, artifactId?: string) =>
    uploadWithFields<TestRun>(
      "/automation/runs/import",
      file,
      artifactId ? { artifact_id: artifactId } : {},
    ),
  testRuns: (query: { artifactId?: string; specId?: string; limit?: number } = {}) =>
    get<TestRunSummary[]>("/automation/runs", {
      limit: query.limit ?? 30,
      ...(query.artifactId ? { artifact_id: query.artifactId } : {}),
      ...(query.specId ? { spec_id: query.specId } : {}),
    }),
  testRun: (runId: string) =>
    get<TestRun>(`/automation/runs/${encodeURIComponent(runId)}`),
  testRunReportSource: (runId: string) =>
    get<{ test_data: string; suggested_title: string }>(
      `/automation/runs/${encodeURIComponent(runId)}/report-source`,
    ),
  createRunFollowUp: (
    runId: string,
    payload: { priority?: "P0" | "P1" | "P2" | "P3"; remind_at?: string | null } = {},
  ) =>
    post<WorkItem>(`/automation/runs/${encodeURIComponent(runId)}/follow-up`, payload),
  jobEvents: (query: { runId?: string; artifactId?: string; limit?: number } = {}) =>
    get<JobEvent[]>("/automation/events", {
      limit: query.limit ?? 100,
      ...(query.runId ? { run_id: query.runId } : {}),
      ...(query.artifactId ? { artifact_id: query.artifactId } : {}),
    }),

  /* ---------- 工作事项（V2.3） ---------- */
  workItems: (
    query: {
      view?: string;
      q?: string;
      status?: string;
      priority?: string;
      tag?: string;
      limit?: number;
    } = {},
  ) =>
    get<WorkItem[]>("/work-items", {
      limit: query.limit ?? 200,
      view: query.view ?? "all",
      ...(query.q ? { q: query.q } : {}),
      ...(query.status ? { status: query.status } : {}),
      ...(query.priority ? { priority: query.priority } : {}),
      ...(query.tag ? { tag: query.tag } : {}),
    }),
  workItem: (workItemId: string) =>
    get<WorkItem>(`/work-items/${encodeURIComponent(workItemId)}`),
  createWorkItem: (payload: WorkItemCreate) => post<WorkItem>("/work-items", payload),
  updateWorkItem: (workItemId: string, payload: WorkItemUpdate) =>
    put<WorkItem>(`/work-items/${encodeURIComponent(workItemId)}`, payload),
  completeWorkItem: (workItemId: string) =>
    post<WorkItem>(`/work-items/${encodeURIComponent(workItemId)}/complete`),
  archiveWorkItem: (workItemId: string) =>
    post<WorkItem>(`/work-items/${encodeURIComponent(workItemId)}/archive`),
  deleteWorkItem: (workItemId: string) =>
    del<{ deleted: boolean }>(`/work-items/${encodeURIComponent(workItemId)}`),
  workItemSummary: () => get<WorkItemSummary>("/work-items/summary"),
  dueWorkItemReminders: () => get<WorkItem[]>("/work-items/reminders/due"),
  ackWorkItemReminders: (ids: string[]) =>
    post<WorkItem[]>("/work-items/reminders/ack", { ids }),

  documents: (limit = 20) => get<DocumentSummary[]>("/documents", { limit }),
  document: (docId: string) => get<DocumentSummary>(`/documents/${docId}`),
  recognizeDocumentImages: (docId: string) =>
    post<DocumentSummary>(`/documents/${encodeURIComponent(docId)}/images/recognize`),
  /** 文档内图片的直链（缩略图用；同名接口直接回二进制，故不能走 JSON 包装）。 */
  documentImageUrl: (docId: string, filename: string) =>
    `/api/v1/documents/${encodeURIComponent(docId)}/images/${encodeURIComponent(filename)}`,
  uploadDocument: (file: File) => upload<DocumentSummary>("/documents/upload", file),
  downloadDocument: (docId: string) =>
    downloadFile(`/documents/${encodeURIComponent(docId)}/download`),
  deleteDocument: (docId: string) =>
    del<{ deleted: boolean; doc_id: string }>(`/documents/${encodeURIComponent(docId)}`),
  batchDeleteDocuments: (ids: string[]) =>
    post<BatchDeleteResult>("/documents/batch-delete", { ids }),

  requirement: (docId: string) => get<RequirementDoc>(`/requirements/${docId}`),
  parseRequirement: (payload: {
    doc_id?: string | null;
    text?: string | null;
    title: string;
    use_llm: boolean;
    max_items: number;
  }) => post<RequirementDoc>("/requirements/parse", payload),
  deleteRequirement: (docId: string) =>
    del<{ deleted: boolean }>(`/requirements/${encodeURIComponent(docId)}`),
  generateFromRequirement: (
    docId: string,
    methods: string[],
    useLlmInDesign: boolean,
  ) =>
    post<TestCaseSuite>(`/requirements/${docId}/testcases`, undefined, {
      methods: methods.join(","),
      use_llm_in_design: useLlmInDesign,
    }),

  suites: (limit = 20, docId?: string) =>
    get<TestCaseSuiteSummary[]>("/testcases/suites", {
      limit,
      ...(docId ? { doc_id: docId } : {}),
    }),
  suite: (suiteId: string) => get<TestCaseSuite>(`/testcases/${suiteId}`),
  suiteCoverage: (suiteId: string) =>
    get<CoverageReport>(`/testcases/${encodeURIComponent(suiteId)}/coverage`),
  deleteSuite: (suiteId: string) =>
    del<{ deleted: boolean }>(`/testcases/${encodeURIComponent(suiteId)}`),
  batchDeleteSuites: (ids: string[]) =>
    post<BatchDeleteResult>("/testcases/batch-delete", { ids }),

  generate: (payload: GeneratePayload) =>
    post<GenerateResult>("/pipeline/generate", payload),

  exportSuite: (suiteId: string, format: string) =>
    downloadFile(`/export/${encodeURIComponent(suiteId)}/${format}`),

  /* ---------- 测试报告域 ---------- */
  reportStatus: () => get<ReportStatus>("/report/status"),
  reportMetrics: (testData: string) =>
    post<MetricsResult>("/report/metrics", { test_data: testData }),
  reportSamples: () => get<SampleDataset[]>("/report/samples"),
  analyzeReport: (payload: AnalyzeRequest) =>
    post<AnalyzeResponse>("/report/analyze", payload),
  probeReport: () => post<ReportLLMTestResult>("/report/probe"),

  reports: (query: ReportListQuery = {}) =>
    get<ReportListResponse>("/report/reports", query as Record<string, unknown>),
  report: (id: string) => get<ReportDetail>(`/report/reports/${encodeURIComponent(id)}`),
  deleteReport: (id: string) =>
    del<{ deleted: boolean }>(`/report/reports/${encodeURIComponent(id)}`),
  batchDeleteReports: (ids: string[]) =>
    post<BatchDeleteResult>("/report/reports/batch-delete", { ids }),
  trends: (limit = 12) => get<TrendPoint[]>("/report/trends", { limit }),
  exportReport: (id: string, format: string) =>
    downloadFile(`/report/reports/${encodeURIComponent(id)}/export?format=${format}`),

  thresholds: () => get<ThresholdView>("/report/thresholds"),
  saveThresholds: (payload: Record<string, number | boolean>) =>
    put<ThresholdView>("/report/thresholds", payload),
  resetThresholds: () => del<ThresholdView>("/report/thresholds"),
};

export { ApiError, saveBlob } from "./client";
export { http } from "./client";
export type * from "./types";

/* ============================================================
   SSE：报告流式生成
   事件顺序 meta → metrics → delta* → done | error
   ============================================================ */
export interface StreamHandlers {
  onMeta?: (payload: Record<string, unknown>) => void;
  onMetrics?: (payload: ReportMetrics) => void;
  onDelta?: (text: string) => void;
  onDone?: (payload: Record<string, unknown>) => void;
  onError?: (detail: string, status?: number) => void;
}

export async function streamAnalyze(
  payload: AnalyzeRequest,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/api/v1/report/analyze/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
  } catch (err) {
    if ((err as Error)?.name === "AbortError") return;
    handlers.onError?.("无法连接服务端，请确认后端已启动（python run.py）。");
    return;
  }

  if (!response.ok || !response.body) {
    let detail = `请求失败（HTTP ${response.status}）。`;
    try {
      const body = await response.json();
      detail = body?.message || body?.detail || detail;
    } catch {
      /* 保持默认文案 */
    }
    handlers.onError?.(detail, response.status);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let event = "";
  let finished = false;

  const dispatch = (name: string, raw: string) => {
    if (!raw) return;
    let data: unknown;
    try {
      data = JSON.parse(raw);
    } catch {
      return;
    }
    if (name === "meta") handlers.onMeta?.(data as Record<string, unknown>);
    else if (name === "metrics") handlers.onMetrics?.(data as ReportMetrics);
    else if (name === "delta") {
      handlers.onDelta?.((data as { text?: string }).text ?? "");
    } else if (name === "done") {
      finished = true;
      handlers.onDone?.(data as Record<string, unknown>);
    } else if (name === "error") {
      finished = true;
      const payloadError = data as { detail?: string; status?: number };
      handlers.onError?.(payloadError.detail || "生成失败。", payloadError.status);
    }
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let index = buffer.indexOf("\n");
      while (index !== -1) {
        const line = buffer.slice(0, index).replace(/\r$/, "");
        buffer = buffer.slice(index + 1);
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dispatch(event, line.slice(5).trim());
        index = buffer.indexOf("\n");
      }
    }
  } catch (err) {
    if ((err as Error)?.name !== "AbortError") {
      handlers.onError?.("流式响应中断，请重试。");
    }
    return;
  }

  if (!finished && !signal?.aborted) {
    handlers.onError?.("连接提前结束，未收到完成信号，请重试。");
  }
}
