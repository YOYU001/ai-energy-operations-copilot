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
