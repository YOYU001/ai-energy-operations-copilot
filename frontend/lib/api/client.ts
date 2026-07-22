import "server-only";

import type {
  ColumnStatistics,
  DatasetSummary,
  DatasetSummaryStatistics,
  HealthResponse,
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

async function apiFetch(path: string): Promise<unknown> {
  const url = `${API_BASE_URL}${path}`;

  let res: Response;
  try {
    res = await fetch(url, {
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
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
