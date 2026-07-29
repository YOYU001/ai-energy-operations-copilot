import Link from "next/link";
import { notFound } from "next/navigation";

import PageShell from "@/components/layout/PageShell";
import EmptyState from "@/components/ui/EmptyState";
import { ApiError, getCase, getSimilarCases } from "@/lib/api/client";
import type { CaseDetail, CaseSearchResult } from "@/lib/api/types";

import SimilarCasesList from "./SimilarCasesList";

export const dynamic = "force-dynamic";

function formatCell(value: string | number | null): string {
  return value === null ? "—" : String(value);
}

function formatDateTime(value: string | null): string {
  if (value === null) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-Hant");
}

async function loadCase(caseId: string): Promise<CaseDetail> {
  try {
    return await getCase(caseId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}

async function loadSimilarCases(
  caseId: string,
): Promise<{ results: CaseSearchResult[] | null }> {
  try {
    return { results: await getSimilarCases(caseId) };
  } catch (error) {
    // CaseHasNoEmbedding -> 422: a real, expected state (case predates
    // embedding or embedding failed), not a page-level error.
    if (error instanceof ApiError && error.status === 422) {
      return { results: null };
    }
    throw error;
  }
}

export default async function CaseDetailPage({
  params,
}: {
  params: Promise<{ case_id: string }>;
}) {
  const { case_id: caseId } = await params;
  const c = await loadCase(caseId);
  const { results: similar } = await loadSimilarCases(caseId);

  return (
    <PageShell title={c.case_id} description="案件詳細資料與相似案例">
      <section className="mb-6 rounded-lg border border-black/10 p-4 text-sm dark:border-white/10">
        <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
          <div className="min-w-0">
            <dt className="text-foreground/60">場域</dt>
            <dd>{formatCell(c.site_id)}</dd>
          </div>
          <div className="min-w-0">
            <dt className="text-foreground/60">事件時間</dt>
            <dd>{formatDateTime(c.event_time)}</dd>
          </div>
          <div className="min-w-0">
            <dt className="text-foreground/60">事件類型</dt>
            <dd className="break-words">{formatCell(c.event_type)}</dd>
          </div>
          <div className="min-w-0">
            <dt className="text-foreground/60">嚴重程度</dt>
            <dd>{formatCell(c.severity)}</dd>
          </div>
          <div className="min-w-0">
            <dt className="text-foreground/60">標籤</dt>
            <dd>{formatCell(c.tags)}</dd>
          </div>
          {c.related_dataset_id !== null && (
            <div className="min-w-0">
              <dt className="text-foreground/60">關聯 Dataset</dt>
              <dd>
                <Link
                  href={`/datasets/${c.related_dataset_id}`}
                  className="underline hover:no-underline"
                >
                  #{c.related_dataset_id}
                  {c.related_time_range && ` (${c.related_time_range})`}
                </Link>
              </dd>
            </div>
          )}
        </dl>
      </section>

      <section className="mb-6 space-y-4">
        <div>
          <h2 className="text-sm font-medium text-foreground/60">問題症狀</h2>
          <p className="mt-1 whitespace-pre-wrap text-sm">
            {formatCell(c.symptoms)}
          </p>
        </div>
        <div>
          <h2 className="text-sm font-medium text-foreground/60">根本原因</h2>
          <p className="mt-1 whitespace-pre-wrap text-sm">
            {formatCell(c.root_cause)}
          </p>
        </div>
        <div>
          <h2 className="text-sm font-medium text-foreground/60">處理方式</h2>
          <p className="mt-1 whitespace-pre-wrap text-sm">
            {formatCell(c.operator_action)}
          </p>
        </div>
        <div>
          <h2 className="text-sm font-medium text-foreground/60">處理結果</h2>
          <p className="mt-1 whitespace-pre-wrap text-sm">
            {formatCell(c.resolution_result)}
          </p>
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-medium text-foreground/60">
          相似案例
        </h2>
        {similar === null ? (
          <div className="rounded-lg border border-dashed border-black/10 p-6 text-sm text-foreground/70 dark:border-white/10">
            此案件尚無 embedding，無法計算相似案例。
          </div>
        ) : similar.length === 0 ? (
          <EmptyState message="目前沒有相似案例。" />
        ) : (
          <SimilarCasesList results={similar} />
        )}
      </section>
    </PageShell>
  );
}
