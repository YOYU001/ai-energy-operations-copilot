"use server";

import { revalidatePath } from "next/cache";

import { ApiError, postDatasetAnalysis } from "@/lib/api/client";

export type RunAnalysisResult = { ok: true } | { ok: false; status: number | null };

export async function runAnalysis(datasetId: number): Promise<RunAnalysisResult> {
  // Server Actions serialize thrown errors, so ApiError's class identity (and
  // .status) would be lost by the time it reaches the client. Catch it here,
  // server-side, and hand back a plain structured result instead of throwing.
  try {
    await postDatasetAnalysis(datasetId);
  } catch (error) {
    if (error instanceof ApiError) {
      return { ok: false, status: error.status };
    }
    return { ok: false, status: null };
  }

  revalidatePath(`/analysis/${datasetId}`);
  return { ok: true };
}
