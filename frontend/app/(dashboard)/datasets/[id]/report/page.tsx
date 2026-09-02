import Link from "next/link";
import { notFound } from "next/navigation";

import RunReportButton from "@/app/(dashboard)/datasets/[id]/report/RunReportButton";
import PageShell from "@/components/layout/PageShell";
import EmptyState from "@/components/ui/EmptyState";
import { ApiError, getDataset, getDatasetReport } from "@/lib/api/client";
import type {
  AnalysisReportRunResponse,
  DatasetSummary,
  ReportSection,
  ReportSectionStatus,
} from "@/lib/api/types";

export const dynamic = "force-dynamic";

function parseDatasetId(raw: string): number | null {
  if (!/^\d+$/.test(raw)) return null;
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

const STATUS_LABEL: Record<ReportSectionStatus, string> = {
  included: "已包含",
  not_run: "尚未執行",
  manual_lookup: "手動查詢",
};

function formatDateTime(value: string | null): string {
  if (value === null) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-Hant");
}

async function loadDataset(id: number): Promise<DatasetSummary> {
  try {
    return await getDataset(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
}

async function loadReport(id: number): Promise<AnalysisReportRunResponse | null> {
  try {
    return await getDatasetReport(id);
  } catch (error) {
    // loadDataset() already confirmed the dataset exists, so a 404 here
    // means "no report generated yet", not "dataset missing".
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

function SectionCard({ section }: { section: ReportSection }) {
  return (
    <section className="mt-6 rounded-lg border border-black/10 p-4 dark:border-white/10">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">{section.title}</h2>
        <span className="rounded-full border border-black/10 px-2 py-0.5 text-xs text-foreground/70 dark:border-white/10">
          {STATUS_LABEL[section.status]}
        </span>
        {section.source_created_at !== null && (
          <span className="text-xs text-foreground/50">
            資料來源時間：{formatDateTime(section.source_created_at)}
          </span>
        )}
      </div>
      {section.summary_points.length > 0 && (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-foreground/80">
          {section.summary_points.map((point, index) => (
            <li key={index}>{point}</li>
          ))}
        </ul>
      )}
      {section.note && (
        <p className="mt-3 text-sm text-foreground/60">{section.note}</p>
      )}
    </section>
  );
}

export default async function DatasetReportPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id: rawId } = await params;
  const datasetId = parseDatasetId(rawId);
  if (datasetId === null) {
    notFound();
  }

  const dataset = await loadDataset(datasetId);
  const reportRun = await loadReport(datasetId);
  const pageTitle = `${dataset.name ?? `Dataset ${datasetId}`}｜分析報告`;

  const backLink = (
    <p className="mb-4 text-sm">
      <Link href={`/datasets/${datasetId}`} className="text-foreground/70 underline">
        ← 回到資料集圖表
      </Link>
    </p>
  );

  if (reportRun === null) {
    return (
      <PageShell title={pageTitle} description="整合各項分析結果的完整報告">
        {backLink}
        <EmptyState message="尚未產生分析報告。此報告會彙整已執行的資料集概況、異常診斷、儲能排程建議、成本估算與綠能營運指數。" />
        <RunReportButton datasetId={datasetId} hasExistingReport={false} />
      </PageShell>
    );
  }

  const report = reportRun.result;

  return (
    <PageShell
      title={pageTitle}
      description={`快照產生時間：${formatDateTime(report.generated_at)}`}
    >
      {backLink}

      <p className="text-sm text-foreground/70">
        資料筆數 {report.row_count.toLocaleString("zh-Hant")} 筆／場域 {report.site_count} 個
        {report.start_time && report.end_time
          ? `／時間範圍 ${formatDateTime(report.start_time)} ~ ${formatDateTime(report.end_time)}`
          : ""}
      </p>

      {report.key_findings.length > 0 && (
        <section className="mt-6 rounded-lg border border-black/10 p-4 dark:border-white/10">
          <h2 className="text-sm font-semibold">重點摘要</h2>
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-foreground/80">
            {report.key_findings.map((finding, index) => (
              <li key={index}>{finding}</li>
            ))}
          </ul>
        </section>
      )}

      {report.sections.map((section) => (
        <SectionCard key={section.key} section={section} />
      ))}

      {report.suggested_actions.length > 0 && (
        <section className="mt-6 rounded-lg border border-black/10 p-4 dark:border-white/10">
          <h2 className="text-sm font-semibold">建議行動</h2>
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-foreground/80">
            {report.suggested_actions.map((action, index) => (
              <li key={index}>{action}</li>
            ))}
          </ul>
        </section>
      )}

      {report.limitations.length > 0 && (
        <section className="mt-6 rounded-lg border border-dashed border-black/10 p-4 text-sm text-foreground/60 dark:border-white/10">
          <h2 className="text-sm font-semibold text-foreground/80">限制與注意事項</h2>
          <ul className="mt-3 list-disc space-y-1 pl-5">
            {report.limitations.map((limitation, index) => (
              <li key={index}>{limitation.detail}</li>
            ))}
          </ul>
        </section>
      )}

      <RunReportButton datasetId={datasetId} hasExistingReport={true} />
    </PageShell>
  );
}
