import Link from "next/link";
import { notFound } from "next/navigation";

import PageShell from "@/components/layout/PageShell";
import EmptyState from "@/components/ui/EmptyState";
import StatusBadge from "@/components/ui/StatusBadge";
import { ApiError, getDocument, getDocumentChunks } from "@/lib/api/client";
import type { ChunkSummary, DocumentSummary } from "@/lib/api/types";

import ChunkList from "./ChunkList";
import ProcessingAutoRefresh from "./ProcessingAutoRefresh";

export const dynamic = "force-dynamic";

export function parseDocumentId(raw: string): number | null {
  if (!/^\d+$/.test(raw)) return null;
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

async function loadDocument(id: number): Promise<DocumentSummary> {
  try {
    return await getDocument(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}

function formatCell(value: string | number | null): string {
  return value === null ? "—" : String(value);
}

function formatDateTime(value: string | null): string {
  if (value === null) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-Hant");
}

export default async function DocumentDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id: rawId } = await params;
  const documentId = parseDocumentId(rawId);
  if (documentId === null) {
    notFound();
  }

  const doc = await loadDocument(documentId);

  // A "processing"/"failed" document never has any active chunks of its own
  // (cutover -- the only thing that ever sets is_active=true -- only runs
  // after full ingestion success), so there is nothing gradable to fetch;
  // skip the call rather than showing a confusing "empty chunks" state on
  // top of the processing/failed messaging below.
  let chunks: ChunkSummary[] = [];
  if (doc.status === "ready") {
    chunks = await getDocumentChunks(documentId);
  }

  const pageTitle = doc.title ?? doc.file_name ?? `Document ${documentId}`;

  return (
    <PageShell title={pageTitle} description="文件詳細資料與 chunk 檢視">
      <section className="mb-6 rounded-lg border border-black/10 p-4 text-sm dark:border-white/10">
        <div className="mb-3">
          <StatusBadge status={doc.status} />
        </div>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
          <div>
            <dt className="text-foreground/60">檔名</dt>
            <dd>{formatCell(doc.file_name)}</dd>
          </div>
          <div>
            <dt className="text-foreground/60">上傳時間</dt>
            <dd>{formatDateTime(doc.uploaded_at)}</dd>
          </div>
          <div>
            <dt className="text-foreground/60">總頁數</dt>
            <dd>{formatCell(doc.total_pages)}</dd>
          </div>
          <div>
            <dt className="text-foreground/60">檔案類型</dt>
            <dd>{formatCell(doc.file_type)}</dd>
          </div>
          <div>
            <dt className="text-foreground/60">來源</dt>
            <dd>{formatCell(doc.source_type)}</dd>
          </div>
          {doc.supersedes_document_id !== null && (
            <div>
              <dt className="text-foreground/60">取代文件</dt>
              <dd>
                <Link
                  href={`/documents/${doc.supersedes_document_id}`}
                  className="underline hover:no-underline"
                >
                  #{doc.supersedes_document_id}
                </Link>
              </dd>
            </div>
          )}
        </dl>
      </section>

      {doc.status === "processing" && (
        <>
          <div className="rounded-lg border border-dashed border-black/10 p-6 text-sm text-foreground/70 dark:border-white/10">
            文件仍在處理中，尚未產生可顯示的 chunks，請稍候。此頁面會自動重新整理。
          </div>
          <ProcessingAutoRefresh />
        </>
      )}

      {doc.status === "failed" && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-6 text-sm text-red-700 dark:text-red-400">
          此文件處理失敗，目前可能沒有可用的 active chunks。
        </div>
      )}

      {doc.status === "ready" &&
        (chunks.length === 0 ? (
          <EmptyState message="此文件目前沒有可顯示的 active chunks。" />
        ) : (
          <ChunkList chunks={chunks} />
        ))}
    </PageShell>
  );
}
