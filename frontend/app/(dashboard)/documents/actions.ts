"use server";

import { revalidatePath } from "next/cache";

import { ApiError, uploadDocument } from "@/lib/api/client";

export type UploadDocumentResult =
  | { ok: true; documentId: number; fileName: string; status: string }
  | { ok: false; status: number | null };

export async function uploadDocumentAction(
  formData: FormData,
): Promise<UploadDocumentResult> {
  // Server Actions serialize thrown errors, so ApiError's class identity (and
  // .status) would be lost by the time it reaches the client. Catch it here,
  // server-side, and hand back a plain structured result instead of throwing
  // -- same pattern as app/analysis/[id]/actions.ts.
  try {
    const result = await uploadDocument(formData);
    revalidatePath("/documents");
    return {
      ok: true,
      documentId: result.document_id,
      fileName: result.file_name,
      status: result.status,
    };
  } catch (error) {
    if (error instanceof ApiError) {
      return { ok: false, status: error.status };
    }
    return { ok: false, status: null };
  }
}
