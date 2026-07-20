import "server-only";

import type { DatasetSummary, HealthResponse, VersionResponse } from "./types";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";
const REQUEST_TIMEOUT_MS = 5000;

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
    throw new Error(`API request failed: ${path} returned HTTP ${res.status}`);
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
  return value === null || typeof value === "number";
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
