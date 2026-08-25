import "server-only";

import type {
  AnalysisNote,
  AnalysisRunResponse,
  AnomalyResult,
  BatteryDischargeAnalysisResult,
  BatteryDischargeEvidence,
  CaseDetail,
  CasesPage,
  CaseSearchResult,
  CaseSummary,
  ChatMessageSummary,
  ChunkSummary,
  ColumnStatistics,
  ConversationDetail,
  ConversationSummary,
  ConversationsPage,
  CostAnalysisResult,
  CostInterval,
  CostRunResponse,
  CostSiteResult,
  DatasetSummary,
  DatasetSummaryStatistics,
  DocumentSummary,
  DocumentUploadResult,
  GreenOpsAnalysisResult,
  GreenOpsComponentName,
  GreenOpsComponentScore,
  GreenOpsComponentStatus,
  GreenOpsRunResponse,
  GreenOpsSiteResult,
  HealthResponse,
  PriceClassificationThreshold,
  PriceThresholdInfo,
  RoleMode,
  ScheduleAnalysisResult,
  ScheduleRecommendation,
  ScheduleRunResponse,
  ScoringSignalFlag,
  TimeseriesPage,
  TimeseriesRow,
  VersionResponse,
} from "./types";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";
const REQUEST_TIMEOUT_MS = 5000;

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function apiFetch(path: string, init: RequestInit = {}): Promise<unknown> {
  const url = `${API_BASE_URL}${path}`;

  let res: Response;
  try {
    res = await fetch(url, {
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      ...init,
    });
  } catch (cause) {
    if (cause instanceof Error && cause.name === "TimeoutError") {
      throw new Error(
        `API request timed out after ${REQUEST_TIMEOUT_MS}ms: ${path}`,
      );
    }
    throw new Error(
      `Failed to reach backend at ${url}: ${(cause as Error).message}`,
    );
  }

  if (!res.ok) {
    throw new ApiError(
      `API request failed: ${path} returned HTTP ${res.status}`,
      res.status,
    );
  }

  try {
    return await res.json();
  } catch {
    throw new Error(`API response is not valid JSON: ${path}`);
  }
}

function isHealthResponse(data: unknown): data is HealthResponse {
  return (
    typeof data === "object" &&
    data !== null &&
    typeof (data as Record<string, unknown>).status === "string"
  );
}

function isVersionResponse(data: unknown): data is VersionResponse {
  return (
    typeof data === "object" &&
    data !== null &&
    typeof (data as Record<string, unknown>).version === "string"
  );
}

export async function getHealth(): Promise<HealthResponse> {
  const data = await apiFetch("/health");
  if (!isHealthResponse(data)) {
    throw new Error(
      "API response schema mismatch: /health did not return { status: string }",
    );
  }
  return data;
}

export async function getVersion(): Promise<VersionResponse> {
  const data = await apiFetch("/version");
  if (!isVersionResponse(data)) {
    throw new Error(
      "API response schema mismatch: /version did not return { version: string }",
    );
  }
  return data;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isNullableNumber(value: unknown): value is number | null {
  return value === null || Number.isFinite(value);
}

function isNullableBoolean(value: unknown): value is boolean | null {
  return value === null || typeof value === "boolean";
}

function isDatasetSummary(data: unknown): data is DatasetSummary {
  if (typeof data !== "object" || data === null) return false;
  const d = data as Record<string, unknown>;
  return (
    typeof d.id === "number" &&
    isNullableString(d.name) &&
    isNullableString(d.file_name) &&
    isNullableString(d.description) &&
    isNullableNumber(d.row_count) &&
    isNullableString(d.start_time) &&
    isNullableString(d.end_time) &&
    isNullableString(d.created_at)
  );
}

export async function getDatasets(): Promise<DatasetSummary[]> {
  const data = await apiFetch("/datasets");
  if (!Array.isArray(data) || !data.every(isDatasetSummary)) {
    throw new Error(
      "API response schema mismatch: /datasets did not return DatasetSummary[]",
    );
  }
  return data;
}

export async function getDataset(datasetId: number): Promise<DatasetSummary> {
  const data = await apiFetch(`/datasets/${datasetId}`);
  if (!isDatasetSummary(data)) {
    throw new Error(
      `API response schema mismatch: /datasets/${datasetId} did not return DatasetSummary`,
    );
  }
  return data;
}

function isColumnStatistics(value: unknown): value is ColumnStatistics {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    isNullableNumber(v.min) && isNullableNumber(v.mean) && isNullableNumber(v.max)
  );
}

function isColumnStatisticsRecord(
  value: unknown,
): value is Record<string, ColumnStatistics> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  return Object.values(value as Record<string, unknown>).every(
    isColumnStatistics,
  );
}

function isDatasetSummaryStatistics(
  data: unknown,
): data is DatasetSummaryStatistics {
  if (typeof data !== "object" || data === null) return false;
  const d = data as Record<string, unknown>;
  return (
    typeof d.dataset_id === "number" &&
    typeof d.row_count === "number" &&
    typeof d.site_count === "number" &&
    isNullableString(d.start_time) &&
    isNullableString(d.end_time) &&
    isColumnStatisticsRecord(d.columns)
  );
}

export async function getDatasetSummary(
  datasetId: number,
): Promise<DatasetSummaryStatistics> {
  const data = await apiFetch(`/datasets/${datasetId}/summary`);
  if (!isDatasetSummaryStatistics(data)) {
    throw new Error(
      `API response schema mismatch: /datasets/${datasetId}/summary did not return DatasetSummaryStatistics`,
    );
  }
  return data;
}

function isTimeseriesRow(data: unknown): data is TimeseriesRow {
  if (typeof data !== "object" || data === null) return false;
  const d = data as Record<string, unknown>;
  return (
    typeof d.id === "number" &&
    typeof d.dataset_id === "number" &&
    isNullableString(d.timestamp) &&
    isNullableString(d.site_id) &&
    isNullableNumber(d.pv_forecast_kw) &&
    isNullableNumber(d.pv_actual_kw) &&
    isNullableNumber(d.load_kw) &&
    isNullableNumber(d.load_forecast_kw) &&
    isNullableNumber(d.battery_soc) &&
    isNullableNumber(d.battery_power_kw) &&
    isNullableNumber(d.battery_temperature) &&
    isNullableNumber(d.electricity_price) &&
    isNullableNumber(d.contract_capacity_kw) &&
    isNullableNumber(d.grid_import_kw) &&
    isNullableNumber(d.grid_export_kw) &&
    isNullableString(d.weather_condition) &&
    isNullableNumber(d.ghi) &&
    isNullableNumber(d.temperature) &&
    isNullableNumber(d.humidity) &&
    isNullableString(d.ems_mode) &&
    isNullableString(d.equipment_status) &&
    isNullableNumber(d.battery_soh) &&
    isNullableNumber(d.battery_cycle_count) &&
    isNullableNumber(d.battery_equivalent_cycle) &&
    isNullableString(d.battery_health_status) &&
    isNullableBoolean(d.battery_is_second_life) &&
    isNullableNumber(d.battery_rated_capacity_kwh) &&
    isNullableNumber(d.battery_available_capacity_kwh)
  );
}

function isTimeseriesPage(data: unknown): data is TimeseriesPage {
  if (typeof data !== "object" || data === null) return false;
  const d = data as Record<string, unknown>;
  return (
    typeof d.dataset_id === "number" &&
    typeof d.total === "number" &&
    typeof d.limit === "number" &&
    typeof d.offset === "number" &&
    Array.isArray(d.items) &&
    d.items.every(isTimeseriesRow)
  );
}

export async function getDatasetTimeseries(
  datasetId: number,
): Promise<TimeseriesPage> {
  const data = await apiFetch(`/datasets/${datasetId}/timeseries?limit=1000`);
  if (!isTimeseriesPage(data)) {
    throw new Error(
      `API response schema mismatch: /datasets/${datasetId}/timeseries did not return TimeseriesPage`,
    );
  }
  return data;
}

function isPriceThresholdInfo(value: unknown): value is PriceThresholdInfo {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.mode === "string" &&
    isNullableNumber(v.threshold) &&
    typeof v.non_null_sample_count === "number" &&
    typeof v.distinct_price_count === "number" &&
    isNullableString(v.reason)
  );
}

function isBatteryDischargeEvidence(
  value: unknown,
): value is BatteryDischargeEvidence {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    isNullableNumber(v.electricity_price) &&
    isNullableNumber(v.high_price_threshold) &&
    typeof v.price_threshold_mode === "string" &&
    isNullableNumber(v.grid_import_kw) &&
    isNullableNumber(v.contract_capacity_kw) &&
    isNullableNumber(v.contract_capacity_ratio) &&
    isNullableNumber(v.battery_soc) &&
    isNullableNumber(v.battery_power_kw) &&
    typeof v.non_null_price_sample_count === "number" &&
    typeof v.distinct_price_count === "number"
  );
}

function isAnomalyResult(value: unknown): value is AnomalyResult {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.anomaly_type === "string" &&
    typeof v.severity === "string" &&
    isNullableString(v.timestamp) &&
    isBatteryDischargeEvidence(v.evidence) &&
    Array.isArray(v.suggested_actions) &&
    v.suggested_actions.every((action) => typeof action === "string")
  );
}

function isBatteryDischargeAnalysisResult(
  value: unknown,
): value is BatteryDischargeAnalysisResult {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.rule === "string" &&
    typeof v.rule_version === "string" &&
    isPriceThresholdInfo(v.price_threshold) &&
    typeof v.input_row_count === "number" &&
    typeof v.evaluated_row_count === "number" &&
    typeof v.flagged_row_count === "number" &&
    Array.isArray(v.anomalies) &&
    v.anomalies.every(isAnomalyResult)
  );
}

function isAnalysisRunResponse(value: unknown): value is AnalysisRunResponse {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.analysis_run_id === "number" &&
    typeof v.dataset_id === "number" &&
    typeof v.analysis_type === "string" &&
    typeof v.rule_version === "string" &&
    typeof v.created_at === "string" &&
    isBatteryDischargeAnalysisResult(v.result)
  );
}

export async function getDatasetAnalysis(
  datasetId: number,
): Promise<AnalysisRunResponse> {
  const data = await apiFetch(`/datasets/${datasetId}/analysis`);
  if (!isAnalysisRunResponse(data)) {
    throw new Error(
      `API response schema mismatch: /datasets/${datasetId}/analysis did not return AnalysisRunResponse`,
    );
  }
  return data;
}

export async function postDatasetAnalysis(
  datasetId: number,
): Promise<AnalysisRunResponse> {
  const data = await apiFetch(`/datasets/${datasetId}/analysis`, {
    method: "POST",
  });
  if (!isAnalysisRunResponse(data)) {
    throw new Error(
      `API response schema mismatch: /datasets/${datasetId}/analysis (POST) did not return AnalysisRunResponse`,
    );
  }
  return data;
}

// ---------------------------------------------------------------------------
// Step 13 -- Battery Scheduling (Sub-step 13.4)
// ---------------------------------------------------------------------------

function isPriceClassificationThreshold(
  value: unknown,
): value is PriceClassificationThreshold {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.mode === "string" &&
    isNullableNumber(v.low_threshold) &&
    isNullableNumber(v.high_threshold) &&
    typeof v.non_null_sample_count === "number" &&
    typeof v.distinct_price_count === "number" &&
    isNullableString(v.reason)
  );
}

function isScheduleRecommendation(value: unknown): value is ScheduleRecommendation {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    isNullableString(v.timestamp) &&
    typeof v.action === "string" &&
    typeof v.reason === "string" &&
    typeof v.price_classification === "string" &&
    Array.isArray(v.warnings) &&
    v.warnings.every((w) => typeof w === "string")
  );
}

function isScheduleAnalysisResult(value: unknown): value is ScheduleAnalysisResult {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.rule === "string" &&
    typeof v.rule_version === "string" &&
    isPriceClassificationThreshold(v.price_threshold) &&
    typeof v.input_row_count === "number" &&
    typeof v.evaluated_row_count === "number" &&
    Array.isArray(v.recommendations) &&
    v.recommendations.every(isScheduleRecommendation)
  );
}

function isScheduleRunResponse(value: unknown): value is ScheduleRunResponse {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.analysis_run_id === "number" &&
    typeof v.dataset_id === "number" &&
    typeof v.analysis_type === "string" &&
    typeof v.rule_version === "string" &&
    typeof v.created_at === "string" &&
    isScheduleAnalysisResult(v.result)
  );
}

export async function getDatasetSchedule(
  datasetId: number,
): Promise<ScheduleRunResponse> {
  const data = await apiFetch(`/datasets/${datasetId}/schedule`);
  if (!isScheduleRunResponse(data)) {
    throw new Error(
      `API response schema mismatch: /datasets/${datasetId}/schedule did not return ScheduleRunResponse`,
    );
  }
  return data;
}

export async function postDatasetSchedule(
  datasetId: number,
): Promise<ScheduleRunResponse> {
  const data = await apiFetch(`/datasets/${datasetId}/schedule`, {
    method: "POST",
  });
  if (!isScheduleRunResponse(data)) {
    throw new Error(
      `API response schema mismatch: /datasets/${datasetId}/schedule (POST) did not return ScheduleRunResponse`,
    );
  }
  return data;
}

// ---------------------------------------------------------------------------
// Step 13 -- Cost Estimation (Sub-step 13.5)
// ---------------------------------------------------------------------------

function isAnalysisNote(value: unknown): value is AnalysisNote {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.type === "string" &&
    typeof v.count === "number" &&
    Array.isArray(v.sample_timestamps) &&
    v.sample_timestamps.every((t) => typeof t === "string") &&
    isNullableString(v.site_id)
  );
}

function isScoringSignalFlag(value: unknown): value is ScoringSignalFlag {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.signal === "string" &&
    typeof v.interval_start === "string" &&
    typeof v.interval_end === "string"
  );
}

function isCostInterval(value: unknown): value is CostInterval {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.site_id === "string" &&
    typeof v.interval_start === "string" &&
    typeof v.interval_end === "string" &&
    typeof v.duration_hours === "number" &&
    typeof v.energy_kwh === "number" &&
    typeof v.estimated_cost === "number" &&
    (v.battery_arbitrage === null || typeof v.battery_arbitrage === "number")
  );
}

function isCostSiteResult(value: unknown): value is CostSiteResult {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.site_id === "string" &&
    typeof v.row_count === "number" &&
    typeof v.interval_count === "number" &&
    Array.isArray(v.intervals) &&
    v.intervals.every(isCostInterval) &&
    typeof v.total_energy_cost === "number" &&
    typeof v.total_arbitrage_saving === "number" &&
    Array.isArray(v.over_contract_penalty_flags) &&
    v.over_contract_penalty_flags.every(isScoringSignalFlag) &&
    Array.isArray(v.warnings) &&
    v.warnings.every(isAnalysisNote) &&
    Array.isArray(v.limitations) &&
    v.limitations.every(isAnalysisNote)
  );
}

function isCostAnalysisResult(value: unknown): value is CostAnalysisResult {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.rule === "string" &&
    typeof v.rule_version === "string" &&
    typeof v.max_expected_interval_hours === "number" &&
    typeof v.site_count === "number" &&
    Array.isArray(v.per_site) &&
    v.per_site.every(isCostSiteResult) &&
    isCostSiteResult(v.dataset_aggregate)
  );
}

function isCostRunResponse(value: unknown): value is CostRunResponse {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.analysis_run_id === "number" &&
    typeof v.dataset_id === "number" &&
    typeof v.analysis_type === "string" &&
    typeof v.rule_version === "string" &&
    typeof v.created_at === "string" &&
    isCostAnalysisResult(v.result)
  );
}

export async function getDatasetCost(
  datasetId: number,
  maxExpectedIntervalHours: number,
): Promise<CostRunResponse> {
  const data = await apiFetch(
    `/datasets/${datasetId}/cost?max_expected_interval_hours=${encodeURIComponent(String(maxExpectedIntervalHours))}`,
  );
  if (!isCostRunResponse(data)) {
    throw new Error(
      `API response schema mismatch: /datasets/${datasetId}/cost did not return CostRunResponse`,
    );
  }
  return data;
}

export async function postDatasetCost(
  datasetId: number,
  maxExpectedIntervalHours: number,
): Promise<CostRunResponse> {
  const data = await apiFetch(
    `/datasets/${datasetId}/cost?max_expected_interval_hours=${encodeURIComponent(String(maxExpectedIntervalHours))}`,
    { method: "POST" },
  );
  if (!isCostRunResponse(data)) {
    throw new Error(
      `API response schema mismatch: /datasets/${datasetId}/cost (POST) did not return CostRunResponse`,
    );
  }
  return data;
}

// ---------------------------------------------------------------------------
// Step 13 -- Green Operations Index (Sub-step 13.6)
// ---------------------------------------------------------------------------

const GREEN_OPS_COMPONENT_NAMES: readonly GreenOpsComponentName[] = [
  "pv_utilization",
  "battery_operation",
  "grid_dependency",
  "battery_health",
];

function isGreenOpsComponentName(value: unknown): value is GreenOpsComponentName {
  return (
    typeof value === "string" &&
    (GREEN_OPS_COMPONENT_NAMES as readonly string[]).includes(value)
  );
}

function isGreenOpsComponentStatus(value: unknown): value is GreenOpsComponentStatus {
  return value === "computed" || value === "insufficient_data";
}

function isGreenOpsComponentScore(value: unknown): value is GreenOpsComponentScore {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;

  if (!isGreenOpsComponentName(v.component)) return false;
  if (typeof v.max_score !== "number") return false;
  if (!isGreenOpsComponentStatus(v.status)) return false;
  if (!Array.isArray(v.penalty_reasons)) return false;
  if (!v.penalty_reasons.every((r) => typeof r === "string")) return false;

  const nullableNumberFields = [v.score, v.eligible_duration_hours, v.flagged_duration_hours];
  if (!nullableNumberFields.every((f) => f === null || typeof f === "number")) {
    return false;
  }

  // status <-> score null-consistency. Per backend _score_component /
  // _aggregate_component: score === null is the ONLY reliable invariant of
  // "insufficient_data" -- eligible/flagged duration hours may independently
  // be null (zero valid intervals at all, _evaluate_site's `if not intervals`
  // branch) OR a real float such as 0.0 (intervals exist but none eligible,
  // or an aggregate mixing computed and insufficient per-site components).
  // "computed" guarantees all three are non-null.
  if (v.status === "insufficient_data" && v.score !== null) return false;
  if (
    v.status === "computed" &&
    (v.score === null || v.eligible_duration_hours === null || v.flagged_duration_hours === null)
  ) {
    return false;
  }

  return true;
}

function isGreenOpsSiteResult(value: unknown): value is GreenOpsSiteResult {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.site_id === "string" &&
    Array.isArray(v.components) &&
    v.components.every(isGreenOpsComponentScore) &&
    (v.second_life_bonus === null || typeof v.second_life_bonus === "number") &&
    (v.total_score === null || typeof v.total_score === "number") &&
    Array.isArray(v.warnings) &&
    v.warnings.every(isAnalysisNote)
  );
}

function isGreenOpsAnalysisResult(value: unknown): value is GreenOpsAnalysisResult {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.rule === "string" &&
    typeof v.rule_version === "string" &&
    typeof v.max_expected_interval_hours === "number" &&
    typeof v.site_count === "number" &&
    Array.isArray(v.per_site) &&
    v.per_site.every(isGreenOpsSiteResult) &&
    isGreenOpsSiteResult(v.dataset_aggregate)
  );
}

function isGreenOpsRunResponse(value: unknown): value is GreenOpsRunResponse {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.analysis_run_id === "number" &&
    typeof v.dataset_id === "number" &&
    typeof v.analysis_type === "string" &&
    typeof v.rule_version === "string" &&
    typeof v.created_at === "string" &&
    isGreenOpsAnalysisResult(v.result)
  );
}

export async function getDatasetGreenOperationsIndex(
  datasetId: number,
  maxExpectedIntervalHours: number,
): Promise<GreenOpsRunResponse> {
  const data = await apiFetch(
    `/datasets/${datasetId}/green-operations-index?max_expected_interval_hours=${encodeURIComponent(String(maxExpectedIntervalHours))}`,
  );
  if (!isGreenOpsRunResponse(data)) {
    throw new Error(
      `API response schema mismatch: /datasets/${datasetId}/green-operations-index did not return GreenOpsRunResponse`,
    );
  }
  return data;
}

export async function postDatasetGreenOperationsIndex(
  datasetId: number,
  maxExpectedIntervalHours: number,
): Promise<GreenOpsRunResponse> {
  const data = await apiFetch(
    `/datasets/${datasetId}/green-operations-index?max_expected_interval_hours=${encodeURIComponent(String(maxExpectedIntervalHours))}`,
    { method: "POST" },
  );
  if (!isGreenOpsRunResponse(data)) {
    throw new Error(
      `API response schema mismatch: /datasets/${datasetId}/green-operations-index (POST) did not return GreenOpsRunResponse`,
    );
  }
  return data;
}

function isDocumentSummary(data: unknown): data is DocumentSummary {
  if (typeof data !== "object" || data === null) return false;
  const d = data as Record<string, unknown>;
  return (
    typeof d.id === "number" &&
    isNullableString(d.title) &&
    isNullableString(d.file_name) &&
    isNullableString(d.file_type) &&
    isNullableString(d.source_type) &&
    isNullableString(d.uploaded_at) &&
    typeof d.status === "string" &&
    isNullableNumber(d.total_pages) &&
    isNullableNumber(d.supersedes_document_id)
  );
}

export async function getDocuments(): Promise<DocumentSummary[]> {
  const data = await apiFetch("/documents");
  if (!Array.isArray(data) || !data.every(isDocumentSummary)) {
    throw new Error(
      "API response schema mismatch: /documents did not return DocumentSummary[]",
    );
  }
  return data;
}

export async function getDocument(documentId: number): Promise<DocumentSummary> {
  const data = await apiFetch(`/documents/${documentId}`);
  if (!isDocumentSummary(data)) {
    throw new Error(
      `API response schema mismatch: /documents/${documentId} did not return DocumentSummary`,
    );
  }
  return data;
}

function isDocumentUploadResult(data: unknown): data is DocumentUploadResult {
  if (typeof data !== "object" || data === null) return false;
  const d = data as Record<string, unknown>;
  return (
    typeof d.document_id === "number" &&
    typeof d.file_name === "string" &&
    typeof d.status === "string"
  );
}

export async function uploadDocument(
  formData: FormData,
): Promise<DocumentUploadResult> {
  // Do not set a Content-Type header here: fetch derives the correct
  // multipart/form-data boundary from the FormData body itself, and a
  // manually-set header would be missing that boundary and break parsing.
  const data = await apiFetch("/documents/upload", {
    method: "POST",
    body: formData,
  });
  if (!isDocumentUploadResult(data)) {
    throw new Error(
      "API response schema mismatch: /documents/upload did not return DocumentUploadResult",
    );
  }
  return data;
}

function isChunkSummary(data: unknown): data is ChunkSummary {
  if (typeof data !== "object" || data === null) return false;
  const d = data as Record<string, unknown>;
  return (
    typeof d.chunk_id === "string" &&
    typeof d.strategy_name === "string" &&
    typeof d.chunk_type === "string" &&
    typeof d.content === "string" &&
    typeof d.page_index_start === "number" &&
    typeof d.page_index_end === "number" &&
    typeof d.pdf_page_number_start === "number" &&
    typeof d.pdf_page_number_end === "number" &&
    isNullableString(d.section_title) &&
    isNullableString(d.table_title) &&
    isNullableString(d.embedding_provider) &&
    isNullableString(d.embedding_model) &&
    isNullableNumber(d.embedding_dimensions) &&
    isNullableString(d.embedding_model_version) &&
    isNullableString(d.embedded_at) &&
    typeof d.is_active === "boolean"
  );
}

export async function getDocumentChunks(
  documentId: number,
): Promise<ChunkSummary[]> {
  const data = await apiFetch(`/documents/${documentId}/chunks`);
  if (!Array.isArray(data) || !data.every(isChunkSummary)) {
    throw new Error(
      `API response schema mismatch: /documents/${documentId}/chunks did not return ChunkSummary[]`,
    );
  }
  return data;
}

function isCaseSummary(data: unknown): data is CaseSummary {
  if (typeof data !== "object" || data === null) return false;
  const d = data as Record<string, unknown>;
  return (
    typeof d.case_id === "string" &&
    isNullableString(d.event_type) &&
    isNullableString(d.symptoms) &&
    isNullableString(d.tags) &&
    isNullableString(d.severity) &&
    typeof d.created_at === "string" &&
    typeof d.updated_at === "string"
  );
}

function isCasesPage(data: unknown): data is CasesPage {
  if (typeof data !== "object" || data === null) return false;
  const d = data as Record<string, unknown>;
  return (
    typeof d.total === "number" &&
    typeof d.limit === "number" &&
    typeof d.offset === "number" &&
    Array.isArray(d.items) &&
    d.items.every(isCaseSummary)
  );
}

export async function getCases(
  limit?: number,
  offset?: number,
): Promise<CasesPage> {
  const params = new URLSearchParams();
  if (limit !== undefined) params.set("limit", String(limit));
  if (offset !== undefined) params.set("offset", String(offset));
  const query = params.size > 0 ? `?${params.toString()}` : "";
  const data = await apiFetch(`/cases${query}`);
  if (!isCasesPage(data)) {
    throw new Error(
      "API response schema mismatch: /cases did not return CasesPage",
    );
  }
  return data;
}

function isCaseDetail(data: unknown): data is CaseDetail {
  if (typeof data !== "object" || data === null) return false;
  const d = data as Record<string, unknown>;
  return (
    typeof d.case_id === "string" &&
    isNullableString(d.site_id) &&
    isNullableString(d.event_time) &&
    isNullableString(d.event_type) &&
    isNullableString(d.symptoms) &&
    isNullableString(d.root_cause) &&
    isNullableString(d.operator_action) &&
    isNullableString(d.resolution_result) &&
    isNullableString(d.severity) &&
    isNullableString(d.tags) &&
    isNullableNumber(d.related_dataset_id) &&
    isNullableString(d.related_time_range) &&
    isNullableString(d.embedding_provider) &&
    isNullableString(d.embedding_model) &&
    isNullableNumber(d.embedding_dimensions) &&
    isNullableString(d.embedding_model_version) &&
    isNullableString(d.embedded_at) &&
    typeof d.created_at === "string" &&
    typeof d.updated_at === "string"
  );
}

export async function getCase(caseId: string): Promise<CaseDetail> {
  const data = await apiFetch(`/cases/${encodeURIComponent(caseId)}`);
  if (!isCaseDetail(data)) {
    throw new Error(
      `API response schema mismatch: /cases/${caseId} did not return CaseDetail`,
    );
  }
  return data;
}

function isCaseSearchResult(data: unknown): data is CaseSearchResult {
  if (typeof data !== "object" || data === null) return false;
  const d = data as Record<string, unknown>;
  return (
    typeof d.case_id === "string" &&
    isNullableString(d.event_type) &&
    isNullableString(d.symptoms) &&
    isNullableString(d.tags) &&
    isNullableString(d.severity) &&
    typeof d.semantic_score === "number" &&
    typeof d.event_type_match === "boolean" &&
    typeof d.tags_boost === "number" &&
    typeof d.final_score === "number" &&
    typeof d.confidence === "string" &&
    typeof d.case_similarity === "string" &&
    Array.isArray(d.matches) &&
    d.matches.every((m) => typeof m === "string") &&
    Array.isArray(d.differs) &&
    d.differs.every((m) => typeof m === "string")
  );
}

export async function getSimilarCases(
  caseId: string,
  topK?: number,
): Promise<CaseSearchResult[]> {
  const query = topK !== undefined ? `?top_k=${topK}` : "";
  const data = await apiFetch(
    `/cases/${encodeURIComponent(caseId)}/similar${query}`,
  );
  if (!Array.isArray(data) || !data.every(isCaseSearchResult)) {
    throw new Error(
      `API response schema mismatch: /cases/${caseId}/similar did not return CaseSearchResult[]`,
    );
  }
  return data;
}

export async function searchCases(payload: {
  query: string;
  event_type?: string | null;
  tags?: string | null;
  top_k?: number;
}): Promise<CaseSearchResult[]> {
  const data = await apiFetch("/cases/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!Array.isArray(data) || !data.every(isCaseSearchResult)) {
    throw new Error(
      "API response schema mismatch: /cases/search did not return CaseSearchResult[]",
    );
  }
  return data;
}

// Step 12 Frontend Slice 1: conversation/message JSON calls -- no
// streaming here. These are only ever called from the new Route Handlers
// under app/api/assistant/ (still server-side, same server-only
// boundary as every function above), never directly from a client
// component. The two SSE POSTs (send message, regenerate) are proxied
// with a raw passthrough fetch in the Route Handlers themselves, not
// through apiFetch (which hardcodes res.json() and a 5s timeout -- both
// wrong for a long-lived stream).

function isRoleMode(value: unknown): value is RoleMode {
  return (
    value === "operator" ||
    value === "engineer" ||
    value === "executive" ||
    value === "training"
  );
}

function isNullableRoleMode(value: unknown): value is RoleMode | null {
  return value === null || isRoleMode(value);
}

function isConversationSummary(data: unknown): data is ConversationSummary {
  if (typeof data !== "object" || data === null) return false;
  const d = data as Record<string, unknown>;
  return (
    typeof d.id === "number" &&
    isNullableString(d.title) &&
    isNullableRoleMode(d.role_mode) &&
    typeof d.created_at === "string" &&
    typeof d.updated_at === "string"
  );
}

function isConversationsPage(data: unknown): data is ConversationsPage {
  if (typeof data !== "object" || data === null) return false;
  const d = data as Record<string, unknown>;
  return (
    typeof d.total === "number" &&
    typeof d.limit === "number" &&
    typeof d.offset === "number" &&
    Array.isArray(d.items) &&
    d.items.every(isConversationSummary)
  );
}

export async function getConversations(
  limit?: number,
  offset?: number,
): Promise<ConversationsPage> {
  const params = new URLSearchParams();
  if (limit !== undefined) params.set("limit", String(limit));
  if (offset !== undefined) params.set("offset", String(offset));
  const query = params.size > 0 ? `?${params.toString()}` : "";
  const data = await apiFetch(`/conversations${query}`);
  if (!isConversationsPage(data)) {
    throw new Error(
      "API response schema mismatch: /conversations did not return ConversationsPage",
    );
  }
  return data;
}

export async function createConversation(
  roleMode?: RoleMode | null,
): Promise<ConversationSummary> {
  const data = await apiFetch("/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role_mode: roleMode ?? null }),
  });
  if (!isConversationSummary(data)) {
    throw new Error(
      "API response schema mismatch: POST /conversations did not return ConversationSummary",
    );
  }
  return data;
}

function isChatMessageSummary(data: unknown): data is ChatMessageSummary {
  if (typeof data !== "object" || data === null) return false;
  const d = data as Record<string, unknown>;
  return (
    typeof d.id === "number" &&
    typeof d.role === "string" &&
    typeof d.content === "string" &&
    typeof d.status === "string" &&
    isNullableNumber(d.parent_user_message_id) &&
    typeof d.attempt_number === "number" &&
    typeof d.is_active === "boolean" &&
    isNullableString(d.provider) &&
    isNullableString(d.model) &&
    isNullableString(d.finish_reason) &&
    isNullableString(d.error_message) &&
    typeof d.created_at === "string" &&
    isNullableString(d.completed_at)
  );
}

function isConversationDetail(data: unknown): data is ConversationDetail {
  if (typeof data !== "object" || data === null) return false;
  const d = data as Record<string, unknown>;
  return (
    isConversationSummary(d.conversation) &&
    Array.isArray(d.messages) &&
    d.messages.every(isChatMessageSummary)
  );
}

export async function getConversation(
  conversationId: number,
): Promise<ConversationDetail> {
  const data = await apiFetch(`/conversations/${conversationId}`);
  if (!isConversationDetail(data)) {
    throw new Error(
      `API response schema mismatch: /conversations/${conversationId} did not return ConversationDetail`,
    );
  }
  return data;
}

export async function updateConversation(
  conversationId: number,
  payload: { title?: string | null; role_mode?: RoleMode | null },
): Promise<ConversationSummary> {
  const data = await apiFetch(`/conversations/${conversationId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!isConversationSummary(data)) {
    throw new Error(
      `API response schema mismatch: PATCH /conversations/${conversationId} did not return ConversationSummary`,
    );
  }
  return data;
}

export async function archiveConversation(
  conversationId: number,
): Promise<void> {
  await apiFetch(`/conversations/${conversationId}`, { method: "DELETE" });
}

export async function getConversationMessages(
  conversationId: number,
): Promise<ChatMessageSummary[]> {
  const data = await apiFetch(`/conversations/${conversationId}/messages`);
  if (!Array.isArray(data) || !data.every(isChatMessageSummary)) {
    throw new Error(
      `API response schema mismatch: /conversations/${conversationId}/messages did not return ChatMessageSummary[]`,
    );
  }
  return data;
}
