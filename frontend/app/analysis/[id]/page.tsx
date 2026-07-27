import { notFound } from "next/navigation";

import RunAnalysisButton from "./RunAnalysisButton";
import PageShell from "@/components/layout/PageShell";
import EmptyState from "@/components/ui/EmptyState";
import { ApiError, getDataset, getDatasetAnalysis } from "@/lib/api/client";
import type { AnalysisRunResponse, DatasetSummary } from "@/lib/api/types";

export const dynamic = "force-dynamic";

export function parseDatasetId(raw: string): number | null {
  if (!/^\d+$/.test(raw)) return null;
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
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

async function loadAnalysis(id: number): Promise<AnalysisRunResponse | null> {
  try {
    return await getDatasetAnalysis(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

function formatDateTime(value: string | null): string {
  if (value === null) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-Hant");
}

function formatNumber(value: number | null): string {
  return value === null ? "—" : String(value);
}

export default async function AnalysisDetailPage({
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
  const analysis = await loadAnalysis(datasetId);

  const pageTitle = dataset.name ?? `Dataset ${datasetId}`;

  if (analysis === null) {
    return (
      <PageShell title={pageTitle} description="異常診斷結果">
        <EmptyState message="這個資料集尚未執行過異常診斷。" />
        <RunAnalysisButton datasetId={datasetId} />
      </PageShell>
    );
  }

  const { result } = analysis;

  return (
    <PageShell title={pageTitle} description="異常診斷結果">
      <section className="mb-6 rounded-lg border border-black/10 p-4 text-sm dark:border-white/10">
        <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
          <div>
            <dt className="text-foreground/60">分析類型</dt>
            <dd>{analysis.analysis_type}</dd>
          </div>
          <div>
            <dt className="text-foreground/60">規則版本</dt>
            <dd>{analysis.rule_version}</dd>
          </div>
          <div>
            <dt className="text-foreground/60">執行時間</dt>
            <dd>{formatDateTime(analysis.created_at)}</dd>
          </div>
          <div>
            <dt className="text-foreground/60">電價門檻模式</dt>
            <dd>{result.price_threshold.mode}</dd>
          </div>
          <div>
            <dt className="text-foreground/60">門檻值</dt>
            <dd>{formatNumber(result.price_threshold.threshold)}</dd>
          </div>
          <div>
            <dt className="text-foreground/60">輸入列數</dt>
            <dd>{result.input_row_count}</dd>
          </div>
          <div>
            <dt className="text-foreground/60">可評估列數</dt>
            <dd>{result.evaluated_row_count}</dd>
          </div>
          <div>
            <dt className="text-foreground/60">觸發異常列數</dt>
            <dd>{result.flagged_row_count}</dd>
          </div>
        </dl>
        {result.price_threshold.reason && (
          <p className="mt-3 text-xs text-foreground/50">
            {result.price_threshold.reason}
          </p>
        )}
      </section>

      {result.anomalies.length === 0 ? (
        <EmptyState message="目前沒有符合此規則的異常。" />
      ) : (
        <div className="space-y-4">
          {result.anomalies.map((anomaly, index) => (
            <section
              key={index}
              className="rounded-lg border border-black/10 p-4 text-sm dark:border-white/10"
            >
              <div className="flex items-center justify-between">
                <p className="font-medium">{anomaly.anomaly_type}</p>
                <span className="rounded-full border border-black/10 px-2 py-0.5 text-xs dark:border-white/10">
                  {anomaly.severity}
                </span>
              </div>
              <p className="mt-1 text-xs text-foreground/60">
                {formatDateTime(anomaly.timestamp)}
              </p>

              <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
                <div>
                  <dt className="text-foreground/60">電價</dt>
                  <dd>{formatNumber(anomaly.evidence.electricity_price)}</dd>
                </div>
                <div>
                  <dt className="text-foreground/60">電價門檻</dt>
                  <dd>
                    {formatNumber(anomaly.evidence.high_price_threshold)}
                  </dd>
                </div>
                <div>
                  <dt className="text-foreground/60">門檻模式</dt>
                  <dd>{anomaly.evidence.price_threshold_mode}</dd>
                </div>
                <div>
                  <dt className="text-foreground/60">電網用電 (kW)</dt>
                  <dd>{formatNumber(anomaly.evidence.grid_import_kw)}</dd>
                </div>
                <div>
                  <dt className="text-foreground/60">契約容量 (kW)</dt>
                  <dd>
                    {formatNumber(anomaly.evidence.contract_capacity_kw)}
                  </dd>
                </div>
                <div>
                  <dt className="text-foreground/60">契約容量比例</dt>
                  <dd>
                    {formatNumber(anomaly.evidence.contract_capacity_ratio)}
                  </dd>
                </div>
                <div>
                  <dt className="text-foreground/60">電池 SOC</dt>
                  <dd>{formatNumber(anomaly.evidence.battery_soc)}</dd>
                </div>
                <div>
                  <dt className="text-foreground/60">電池功率 (kW)</dt>
                  <dd>{formatNumber(anomaly.evidence.battery_power_kw)}</dd>
                </div>
                <div>
                  <dt className="text-foreground/60">非 null 電價樣本數</dt>
                  <dd>{anomaly.evidence.non_null_price_sample_count}</dd>
                </div>
                <div>
                  <dt className="text-foreground/60">電價不同值數量</dt>
                  <dd>{anomaly.evidence.distinct_price_count}</dd>
                </div>
              </dl>

              <div className="mt-3">
                <p className="text-foreground/60">建議動作</p>
                <ul className="mt-1 list-disc pl-5">
                  {anomaly.suggested_actions.map((action) => (
                    <li key={action}>{action}</li>
                  ))}
                </ul>
              </div>
            </section>
          ))}
        </div>
      )}
    </PageShell>
  );
}
