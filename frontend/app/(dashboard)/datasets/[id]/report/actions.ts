"use server";

import { ApiError, postDatasetReport } from "@/lib/api/client";
import type { AnalysisReportRunResponse } from "@/lib/api/types";

export type RunAnalysisReportResult =
  | { ok: true; result: AnalysisReportRunResponse }
  | { ok: false; status: number | null };

export async function runAnalysisReport(
  datasetId: number,
  refresh: boolean,
): Promise<RunAnalysisReportResult> {
  // Server Actions serialize thrown errors, so ApiError's class identity
  // (and .status) would be lost by the time it reaches the client -- same
  // rationale as datasets/[id]/actions.ts. router.refresh() after success
  // is the client's job (RunReportButton), not this action's.
  try {
    const result = await postDatasetReport(datasetId, refresh);
    return { ok: true, result };
  } catch (error) {
    if (error instanceof ApiError) {
      return { ok: false, status: error.status };
    }
    return { ok: false, status: null };
  }
}
