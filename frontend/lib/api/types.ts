export interface HealthResponse {
  status: string;
}

export interface VersionResponse {
  version: string;
}

export interface DatasetSummary {
  id: number;
  name: string | null;
  file_name: string | null;
  description: string | null;
  row_count: number | null;
  start_time: string | null;
  end_time: string | null;
  created_at: string | null;
}

export interface ColumnStatistics {
  min: number | null;
  mean: number | null;
  max: number | null;
}

export interface DatasetSummaryStatistics {
  dataset_id: number;
  row_count: number;
  site_count: number;
  start_time: string | null;
  end_time: string | null;
  columns: Record<string, ColumnStatistics>;
}

export interface TimeseriesRow {
  id: number;
  dataset_id: number;
  timestamp: string | null;
  site_id: string | null;
  pv_forecast_kw: number | null;
  pv_actual_kw: number | null;
  load_kw: number | null;
  load_forecast_kw: number | null;
  battery_soc: number | null;
  battery_power_kw: number | null;
  battery_temperature: number | null;
  electricity_price: number | null;
  contract_capacity_kw: number | null;
  grid_import_kw: number | null;
  grid_export_kw: number | null;
  weather_condition: string | null;
  ghi: number | null;
  temperature: number | null;
  humidity: number | null;
  ems_mode: string | null;
  equipment_status: string | null;
  battery_soh: number | null;
  battery_cycle_count: number | null;
  battery_equivalent_cycle: number | null;
  battery_health_status: string | null;
  battery_is_second_life: boolean | null;
  battery_rated_capacity_kwh: number | null;
  battery_available_capacity_kwh: number | null;
}

export interface TimeseriesPage {
  dataset_id: number;
  total: number;
  limit: number;
  offset: number;
  items: TimeseriesRow[];
}

export interface PriceThresholdInfo {
  mode: string;
  threshold: number | null;
  non_null_sample_count: number;
  distinct_price_count: number;
  reason: string | null;
}

export interface BatteryDischargeEvidence {
  electricity_price: number | null;
  high_price_threshold: number | null;
  price_threshold_mode: string;
  grid_import_kw: number | null;
  contract_capacity_kw: number | null;
  contract_capacity_ratio: number | null;
  battery_soc: number | null;
  battery_power_kw: number | null;
  non_null_price_sample_count: number;
  distinct_price_count: number;
}

export interface AnomalyResult {
  anomaly_type: string;
  severity: string;
  timestamp: string | null;
  evidence: BatteryDischargeEvidence;
  suggested_actions: string[];
}

export interface BatteryDischargeAnalysisResult {
  rule: string;
  rule_version: string;
  price_threshold: PriceThresholdInfo;
  input_row_count: number;
  evaluated_row_count: number;
  flagged_row_count: number;
  anomalies: AnomalyResult[];
}

export interface AnalysisRunResponse {
  analysis_run_id: number;
  dataset_id: number;
  analysis_type: string;
  rule_version: string;
  created_at: string;
  result: BatteryDischargeAnalysisResult;
}

// Step 13 -- Cost Estimation (Sub-step 13.5). Mirrors backend/app/schemas.py.
export interface AnalysisNote {
  type: string;
  count: number;
  sample_timestamps: string[];
  site_id: string | null;
}

export interface ScoringSignalFlag {
  signal: string;
  interval_start: string;
  interval_end: string;
}

export interface CostInterval {
  site_id: string;
  interval_start: string;
  interval_end: string;
  duration_hours: number;
  energy_kwh: number;
  estimated_cost: number;
  battery_arbitrage: number | null;
}

export interface CostSiteResult {
  site_id: string;
  row_count: number;
  interval_count: number;
  intervals: CostInterval[];
  total_energy_cost: number;
  total_arbitrage_saving: number;
  over_contract_penalty_flags: ScoringSignalFlag[];
  warnings: AnalysisNote[];
  limitations: AnalysisNote[];
}

export interface CostAnalysisResult {
  rule: string;
  rule_version: string;
  max_expected_interval_hours: number;
  site_count: number;
  per_site: CostSiteResult[];
  dataset_aggregate: CostSiteResult;
}

export interface CostRunResponse {
  analysis_run_id: number;
  dataset_id: number;
  analysis_type: string;
  rule_version: string;
  created_at: string;
  result: CostAnalysisResult;
}

// Step 13 -- Green Operations Index (Sub-step 13.6). Mirrors backend/app/schemas.py.
export type GreenOpsComponentName =
  | "pv_utilization"
  | "battery_operation"
  | "grid_dependency"
  | "battery_health";

export type GreenOpsComponentStatus = "computed" | "insufficient_data";

export interface GreenOpsComponentScore {
  component: GreenOpsComponentName;
  max_score: number;
  score: number | null;
  status: GreenOpsComponentStatus;
  eligible_duration_hours: number | null;
  flagged_duration_hours: number | null;
  penalty_reasons: string[];
}

export interface GreenOpsSiteResult {
  site_id: string;
  components: GreenOpsComponentScore[];
  second_life_bonus: number | null;
  total_score: number | null;
  warnings: AnalysisNote[];
}

export interface GreenOpsAnalysisResult {
  rule: string;
  rule_version: string;
  max_expected_interval_hours: number;
  site_count: number;
  per_site: GreenOpsSiteResult[];
  dataset_aggregate: GreenOpsSiteResult;
}

export interface GreenOpsRunResponse {
  analysis_run_id: number;
  dataset_id: number;
  analysis_type: string;
  rule_version: string;
  created_at: string;
  result: GreenOpsAnalysisResult;
}

// Step 13 -- Battery Scheduling (Sub-step 13.4). Mirrors backend/app/schemas.py.
// Unlike CostAnalysisResult / GreenOpsAnalysisResult, this API takes no
// max_expected_interval_hours parameter and has no per-site breakdown --
// recommendations is a flat list spanning the whole dataset regardless of
// site_id (see backend/app/services/battery_scheduling.py).

// Mirrors backend's PriceClassificationThreshold -- deliberately distinct
// from PriceThresholdInfo above (that one backs the Step 9 anomaly rule and
// only ever answers "is this high"; this one carries a separate
// low/high pair for the low/neutral/high classification Battery Scheduling
// uses).
export interface PriceClassificationThreshold {
  mode: string; // "insufficient_data" | "no_distinguishable_peak" | "discrete_tou_max" | "percentile"
  low_threshold: number | null;
  high_threshold: number | null;
  non_null_sample_count: number;
  distinct_price_count: number;
  reason: string | null;
}

export interface ScheduleRecommendation {
  timestamp: string | null;
  action: string; // "charge" | "discharge" | "idle" | "hold"
  reason: string;
  price_classification: string; // "low" | "neutral" | "high"
  warnings: string[];
}

export interface ScheduleAnalysisResult {
  rule: string;
  rule_version: string;
  price_threshold: PriceClassificationThreshold;
  input_row_count: number;
  evaluated_row_count: number;
  recommendations: ScheduleRecommendation[];
}

export interface ScheduleRunResponse {
  analysis_run_id: number;
  dataset_id: number;
  analysis_type: string;
  rule_version: string;
  created_at: string;
  result: ScheduleAnalysisResult;
}

// Step 14 -- Analysis Report. Mirrors backend/app/schemas.py's
// ReportSection / ReportLimitation / AnalysisReportResult. A snapshot that
// composes the already-run sub-analyses; sections whose sub-analysis has
// not run carry status "not_run", similar cases is always "manual_lookup".
export type ReportSectionStatus = "included" | "not_run" | "manual_lookup";

export interface ReportSection {
  key: string;
  title: string;
  status: ReportSectionStatus;
  source_analysis_run_id: number | null;
  source_created_at: string | null;
  summary_points: string[];
  note: string | null;
}

export interface ReportLimitation {
  kind: string; // "section_not_run" | "snapshot_staleness" | "data_quality"
  detail: string;
}

export interface AnalysisReportResult {
  rule: string;
  rule_version: string;
  dataset_id: number;
  dataset_name: string | null;
  generated_at: string;
  row_count: number;
  site_count: number;
  start_time: string | null;
  end_time: string | null;
  key_findings: string[];
  sections: ReportSection[];
  suggested_actions: string[];
  limitations: ReportLimitation[];
}

export interface AnalysisReportRunResponse {
  analysis_run_id: number;
  dataset_id: number;
  analysis_type: string;
  rule_version: string;
  created_at: string;
  result: AnalysisReportResult;
}

export interface DocumentSummary {
  id: number;
  title: string | null;
  file_name: string | null;
  file_type: string | null;
  source_type: string | null;
  uploaded_at: string | null;
  status: string;
  total_pages: number | null;
  supersedes_document_id: number | null;
}

export interface DocumentUploadResult {
  document_id: number;
  file_name: string;
  status: string;
}

export interface ChunkSummary {
  chunk_id: string;
  strategy_name: string;
  chunk_type: string;
  content: string;
  page_index_start: number;
  page_index_end: number;
  pdf_page_number_start: number;
  pdf_page_number_end: number;
  section_title: string | null;
  table_title: string | null;
  embedding_provider: string | null;
  embedding_model: string | null;
  embedding_dimensions: number | null;
  embedding_model_version: string | null;
  embedded_at: string | null;
  is_active: boolean;
}

export interface CaseSummary {
  case_id: string;
  event_type: string | null;
  symptoms: string | null;
  tags: string | null;
  severity: string | null;
  created_at: string;
  updated_at: string;
}

export interface CasesPage {
  total: number;
  limit: number;
  offset: number;
  items: CaseSummary[];
}

export interface CaseDetail {
  case_id: string;
  site_id: string | null;
  event_time: string | null;
  event_type: string | null;
  symptoms: string | null;
  root_cause: string | null;
  operator_action: string | null;
  resolution_result: string | null;
  severity: string | null;
  tags: string | null;
  related_dataset_id: number | null;
  related_time_range: string | null;
  embedding_provider: string | null;
  embedding_model: string | null;
  embedding_dimensions: number | null;
  embedding_model_version: string | null;
  embedded_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CaseSearchResult {
  case_id: string;
  event_type: string | null;
  symptoms: string | null;
  tags: string | null;
  severity: string | null;
  semantic_score: number;
  event_type_match: boolean;
  tags_boost: number;
  final_score: number;
  confidence: string;
  case_similarity: string;
  matches: string[];
  differs: string[];
}

// Step 12: mirrors backend/app/schemas.py's RoleMode Literal and the
// conversation/message response models field-for-field.
export type RoleMode = "operator" | "engineer" | "executive" | "training";

export interface ConversationSummary {
  id: number;
  title: string | null;
  role_mode: RoleMode | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationsPage {
  total: number;
  limit: number;
  offset: number;
  items: ConversationSummary[];
}

export interface ChatMessageSummary {
  id: number;
  role: string;
  content: string;
  status: string;
  parent_user_message_id: number | null;
  attempt_number: number;
  is_active: boolean;
  provider: string | null;
  model: string | null;
  finish_reason: string | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface ConversationDetail {
  conversation: ConversationSummary;
  messages: ChatMessageSummary[];
}
