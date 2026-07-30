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
