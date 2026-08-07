"use server";

import {
  ApiError,
  postDatasetCost,
  postDatasetGreenOperationsIndex,
} from "@/lib/api/client";
import type { CostRunResponse, GreenOpsRunResponse } from "@/lib/api/types";

export type RunCostAnalysisResult =
  | { ok: true; result: CostRunResponse }
  | { ok: false; status: number | null };

export async function runCostAnalysis(
  datasetId: number,
  maxExpectedIntervalHours: number,
): Promise<RunCostAnalysisResult> {
  // Server Actions serialize thrown errors, so ApiError's class identity (and
  // .status) would be lost by the time it reaches the client -- same
  // rationale as analysis/[id]/actions.ts's runAnalysis. URL navigation
  // after success is the CLIENT's job (CostAnalysisForm), not this action's:
  // useRouter() is a client-only hook and must not be called from here.
  try {
    const result = await postDatasetCost(datasetId, maxExpectedIntervalHours);
    return { ok: true, result };
  } catch (error) {
    if (error instanceof ApiError) {
      return { ok: false, status: error.status };
    }
    return { ok: false, status: null };
  }
}

export type RunGreenOpsAnalysisResult =
  | { ok: true; result: GreenOpsRunResponse }
  | { ok: false; status: number | null };

export async function runGreenOpsAnalysis(
  datasetId: number,
  maxExpectedIntervalHours: number,
): Promise<RunGreenOpsAnalysisResult> {
  try {
    const result = await postDatasetGreenOperationsIndex(datasetId, maxExpectedIntervalHours);
    return { ok: true, result };
  } catch (error) {
    if (error instanceof ApiError) {
      return { ok: false, status: error.status };
    }
    return { ok: false, status: null };
  }
}
