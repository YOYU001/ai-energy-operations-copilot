import Link from "next/link";
import { notFound } from "next/navigation";

import CostAnalysisForm from "@/app/(dashboard)/datasets/[id]/CostAnalysisForm";
import GreenOpsAnalysisForm from "@/app/(dashboard)/datasets/[id]/GreenOpsAnalysisForm";
import RunScheduleButton from "@/app/(dashboard)/datasets/[id]/RunScheduleButton";
import BatteryScheduleOverlay from "@/components/charts/BatteryScheduleOverlay";
import BatteryScheduleTable from "@/components/charts/BatteryScheduleTable";
import ChartSection from "@/components/charts/ChartSection";
import {
  CostAggregateSummary,
  CostComparisonBarChart,
} from "@/components/charts/CostComparisonChart";
import {
  GreenOpsAggregateSummary,
  GreenOpsScoreBarChart,
} from "@/components/charts/GreenOpsChart";
import type { TimeSeriesDatum } from "@/components/charts/TimeSeriesChart";
import PageShell from "@/components/layout/PageShell";
import EmptyState from "@/components/ui/EmptyState";
import {
  ApiError,
  getDataset,
  getDatasetCost,
  getDatasetGreenOperationsIndex,
  getDatasetSchedule,
  getDatasetSummary,
  getDatasetTimeseries,
} from "@/lib/api/client";
import type {
  CostRunResponse,
  DatasetSummary,
  GreenOpsRunResponse,
  ScheduleRunResponse,
  TimeseriesRow,
} from "@/lib/api/types";

export const dynamic = "force-dynamic";

export function parseDatasetId(raw: string): number | null {
  if (!/^\d+$/.test(raw)) return null;
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

export function getDistinctContractCapacities(
  items: Pick<TimeseriesRow, "contract_capacity_kw">[],
): number[] {
  const values = new Set<number>();
  for (const item of items) {
    if (item.contract_capacity_kw !== null) {
      values.add(item.contract_capacity_kw);
    }
  }
  return Array.from(values);
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

const MAX_EXPECTED_INTERVAL_HOURS_PARAM = "max_expected_interval_hours";

// Parses the URL's max_expected_interval_hours query param. Returns null
// for anything not a finite positive number (missing, non-numeric, NaN,
// Infinity, 0, negative) -- per Step 13 Sub-step 13.5 decision, an invalid
// or absent URL param means "no persisted parameter to restore," not "use
// some fallback value."
function parseMaxExpectedIntervalHours(
  raw: string | string[] | undefined,
): number | null {
  if (typeof raw !== "string") return null;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed <= 0) return null;
  return parsed;
}

async function loadCost(
  datasetId: number,
  maxExpectedIntervalHours: number | null,
): Promise<CostRunResponse | null> {
  if (maxExpectedIntervalHours === null) return null;
  try {
    return await getDatasetCost(datasetId, maxExpectedIntervalHours);
  } catch (error) {
    // Safe to read as "no cost run yet for this parameter, not the dataset
    // being missing" ONLY because loadDataset() above already confirmed
    // the dataset exists (and calls notFound() itself if it doesn't) before
    // this function is ever reached.
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

const GREEN_OPS_MAX_EXPECTED_INTERVAL_HOURS_PARAM = "green_ops_max_expected_interval_hours";

async function loadGreenOps(
  datasetId: number,
  maxExpectedIntervalHours: number | null,
): Promise<GreenOpsRunResponse | null> {
  if (maxExpectedIntervalHours === null) return null;
  try {
    return await getDatasetGreenOperationsIndex(datasetId, maxExpectedIntervalHours);
  } catch (error) {
    // Same rationale as loadCost() -- loadDataset() already confirmed the
    // dataset exists before this function is ever reached.
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

// Unlike loadCost/loadGreenOps, this takes no parameter -- the schedule
// endpoint has no max_expected_interval_hours (backend/app/schemas.py's
// ScheduleAnalysisResult), so it is always attempted once reachable rather
// than gated behind a URL query param.
async function loadSchedule(datasetId: number): Promise<ScheduleRunResponse | null> {
  try {
    return await getDatasetSchedule(datasetId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

export default async function DatasetChartsPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { id: rawId } = await params;
  const datasetId = parseDatasetId(rawId);
  if (datasetId === null) {
    notFound();
  }

  const dataset = await loadDataset(datasetId);
  const [summary, timeseries, resolvedSearchParams] = await Promise.all([
    getDatasetSummary(datasetId),
    getDatasetTimeseries(datasetId),
    searchParams,
  ]);

  const requestedMaxExpectedIntervalHours = parseMaxExpectedIntervalHours(
    resolvedSearchParams[MAX_EXPECTED_INTERVAL_HOURS_PARAM],
  );
  const requestedGreenOpsMaxExpectedIntervalHours = parseMaxExpectedIntervalHours(
    resolvedSearchParams[GREEN_OPS_MAX_EXPECTED_INTERVAL_HOURS_PARAM],
  );
  const [costRun, greenOpsRun] = await Promise.all([
    loadCost(datasetId, requestedMaxExpectedIntervalHours),
    loadGreenOps(datasetId, requestedGreenOpsMaxExpectedIntervalHours),
  ]);
  const costFormInitialValue =
    requestedMaxExpectedIntervalHours !== null
      ? String(requestedMaxExpectedIntervalHours)
      : "";
  const greenOpsFormInitialValue =
    requestedGreenOpsMaxExpectedIntervalHours !== null
      ? String(requestedGreenOpsMaxExpectedIntervalHours)
      : "";

  const costSection = (
    <section className="mt-8">
      <h2 className="text-sm font-semibold">
        Cost Comparison（示範用合成資料）
      </h2>
      <p className="mt-1 text-xs text-foreground/60">
        資料集依 site 分組的成本比較。輸入下方參數並執行以查看結果。
      </p>
      <CostAnalysisForm
        datasetId={datasetId}
        initialValue={costFormInitialValue}
      />
      {costRun === null ? (
        <div className="mt-4">
          <EmptyState message="尚未執行過成本分析，或此參數組合尚無結果。" />
        </div>
      ) : (
        <div className="mt-4">
          <CostComparisonBarChart perSite={costRun.result.per_site} />
          <CostAggregateSummary
            aggregate={costRun.result.dataset_aggregate}
            siteCount={costRun.result.site_count}
          />
        </div>
      )}
    </section>
  );

  const greenOpsSection = (
    <section className="mt-8">
      <h2 className="text-sm font-semibold">
        Green Operations Index（示範用合成資料）
      </h2>
      <p className="mt-1 text-xs text-foreground/60">
        資料集依 site 分組的綠能營運指數（0–100 分，四個分項組成 + second-life 加分）。輸入下方參數並執行以查看結果。
      </p>
      <GreenOpsAnalysisForm
        datasetId={datasetId}
        initialValue={greenOpsFormInitialValue}
      />
      {greenOpsRun === null ? (
        <div className="mt-4">
          <EmptyState message="尚未執行過綠能營運指數分析，或此參數組合尚無結果。" />
        </div>
      ) : (
        <div className="mt-4 space-y-6">
          {greenOpsRun.result.per_site.map((site) => (
            <div key={site.site_id}>
              <p className="text-sm font-medium">
                {site.site_id}：
                {site.total_score === null
                  ? "資料不足"
                  : `${site.total_score.toLocaleString("zh-Hant", { maximumFractionDigits: 2 })} / 100`}
              </p>
              {site.warnings.length > 0 && (
                <ul className="mt-1 text-xs text-foreground/60">
                  {site.warnings.map((w, index) => (
                    <li key={index}>
                      {w.type}（{w.count} 筆）
                    </li>
                  ))}
                </ul>
              )}
              <GreenOpsScoreBarChart siteId={site.site_id} components={site.components} />
            </div>
          ))}
          <GreenOpsAggregateSummary
            aggregate={greenOpsRun.result.dataset_aggregate}
            siteCount={greenOpsRun.result.site_count}
          />
        </div>
      )}
    </section>
  );

  const pageTitle = dataset.name ?? `Dataset ${datasetId}`;

  const reportLink = (
    <p className="mb-4 text-sm">
      <Link
        href={`/datasets/${datasetId}/report`}
        className="text-foreground/70 underline"
      >
        查看分析報告 →
      </Link>
    </p>
  );

  // Battery Scheduling's rule (backend/app/services/battery_scheduling.py)
  // evaluates every row independently and never groups by site_id --
  // ScheduleRecommendation carries no site_id field at all (unlike
  // Cost/Green Ops' per_site breakdown). A multi-site dataset would mix
  // recommendations from different sites into one undifferentiated list, so
  // this section deliberately does not offer to run it there (Step 13
  // Battery Scheduling frontend decision, 2026-08-14).
  const scheduleSectionHeader = (
    <h2 className="text-sm font-semibold">
      Battery Scheduling（示範用合成資料）
    </h2>
  );

  if (summary.site_count > 1) {
    const scheduleSection = (
      <section className="mt-8">
        {scheduleSectionHeader}
        <div className="mt-4 rounded-lg border border-dashed border-black/10 p-6 text-sm text-foreground/70 dark:border-white/10">
          此規則目前不支援按場域拆分：此資料集包含 {summary.site_count}{" "}
          個不同場域，暫不提供排程建議。
        </div>
      </section>
    );
    return (
      <PageShell title={pageTitle} description="資料集圖表">
        {reportLink}
        <div className="rounded-lg border border-dashed border-black/10 p-6 text-sm text-foreground/70 dark:border-white/10">
          此資料集包含 {summary.site_count} 個不同場域，圖表僅支援單一場域，暫不顯示。
        </div>
        {costSection}
        {greenOpsSection}
        {scheduleSection}
      </PageShell>
    );
  }

  if (timeseries.total === 0) {
    const scheduleSection = (
      <section className="mt-8">
        {scheduleSectionHeader}
        <div className="mt-4">
          <EmptyState message="此資料集沒有時間序列資料，無法執行排程建議。" />
        </div>
      </section>
    );
    return (
      <PageShell title={pageTitle} description="資料集圖表">
        {reportLink}
        <EmptyState message="此資料集沒有時間序列資料。" />
        {costSection}
        {greenOpsSection}
        {scheduleSection}
      </PageShell>
    );
  }

  const scheduleRun = await loadSchedule(datasetId);

  const data: TimeSeriesDatum[] = timeseries.items.map((row) => ({
    timestamp: row.timestamp,
    battery_power_kw: row.battery_power_kw,
    battery_soc: row.battery_soc,
    grid_import_kw: row.grid_import_kw,
    contract_capacity_kw: row.contract_capacity_kw,
    electricity_price: row.electricity_price,
    pv_forecast_kw: row.pv_forecast_kw,
    pv_actual_kw: row.pv_actual_kw,
  }));

  const isTruncated = timeseries.total > timeseries.items.length;
  const distinctContractCapacities = getDistinctContractCapacities(
    timeseries.items,
  );
  const contractCapacityReferenceLines =
    distinctContractCapacities.length === 1
      ? [
          {
            value: distinctContractCapacities[0],
            label: "契約容量 (contract capacity)",
          },
        ]
      : [];

  const batteryPowerSection =
    scheduleRun === null ? (
      <ChartSection
        title="Battery Power"
        data={data}
        series={[
          {
            dataKey: "battery_power_kw",
            label: "Battery Power",
            color: "#3b82f6",
            unit: "kW",
          },
        ]}
        yAxisLabel="kW"
        referenceLines={[{ value: 0, label: "待機 (0 kW)" }]}
      />
    ) : (
      <section className="mb-8">
        <h2 className="text-sm font-semibold">Battery Power</h2>
        <p className="mt-1 text-xs text-foreground/60">
          疊加 Battery Scheduling 建議動作（充電／放電／待機／保持）。
        </p>
        <div className="mt-3">
          <BatteryScheduleOverlay
            data={data}
            recommendations={scheduleRun.result.recommendations}
            isTruncated={isTruncated}
            totalRecommendations={scheduleRun.result.recommendations.length}
          />
        </div>
      </section>
    );

  const scheduleSection = (
    <section className="mt-8">
      <h2 className="text-sm font-semibold">
        Battery Scheduling（示範用合成資料）
      </h2>
      <p className="mt-1 text-xs text-foreground/60">
        逐列儲能充放電建議（charge / discharge / idle /
        hold）。主要結果已疊加於上方 Battery Power 圖表，以下為完整明細。
      </p>
      {scheduleRun === null ? (
        <div className="mt-4">
          <EmptyState message="尚未執行過儲能排程建議。" />
          <RunScheduleButton datasetId={datasetId} />
        </div>
      ) : (
        <div className="mt-4">
          <BatteryScheduleTable recommendations={scheduleRun.result.recommendations} />
        </div>
      )}
    </section>
  );

  return (
    <PageShell
      title={pageTitle}
      description={`資料集圖表（共 ${timeseries.total} 筆）`}
    >
      {reportLink}
      {isTruncated && (
        <p className="mb-4 text-xs text-foreground/60">
          此資料集共 {timeseries.total}{" "}
          筆資料，圖表僅顯示 API 回傳的前 1000
          筆資料（後端已依 timestamp 升序排序後回傳）。以下圖表與契約容量檢查僅基於這前
          1000 筆資料，非整份 dataset。
        </p>
      )}

      {distinctContractCapacities.length > 1 && (
        <p className="mb-4 text-xs text-foreground/60">
          偵測到 contract_capacity_kw 在
          {isTruncated ? "前 1000 筆資料中" : "本資料集中"}出現{" "}
          {distinctContractCapacities.length} 個不同數值（例如：
          {distinctContractCapacities.slice(0, 3).join("、")}
          {distinctContractCapacities.length > 3 ? " 等" : ""}
          ），為避免誤導不顯示參考線。
        </p>
      )}

      {batteryPowerSection}

      <ChartSection
        title="Battery SOC"
        data={data}
        series={[
          {
            dataKey: "battery_soc",
            label: "Battery SOC",
            color: "#3b82f6",
            unit: "%",
          },
        ]}
        yAxisLabel="%"
        referenceLines={[{ value: 30, label: "SOC 30% 參考線" }]}
      />

      <ChartSection
        title="Grid Import vs Contract Capacity"
        data={data}
        series={[
          {
            dataKey: "grid_import_kw",
            label: "Grid Import",
            color: "#3b82f6",
            unit: "kW",
          },
        ]}
        yAxisLabel="kW"
        referenceLines={contractCapacityReferenceLines}
      />

      <ChartSection
        title="Electricity Price"
        data={data}
        series={[
          {
            dataKey: "electricity_price",
            label: "Electricity Price",
            color: "#3b82f6",
          },
        ]}
        yAxisLabel="Electricity Price"
      />

      <ChartSection
        title="PV Forecast vs Actual"
        data={data}
        series={[
          {
            dataKey: "pv_forecast_kw",
            label: "PV Forecast",
            color: "#3b82f6",
            unit: "kW",
          },
          {
            dataKey: "pv_actual_kw",
            label: "PV Actual",
            color: "#ea580c",
            unit: "kW",
          },
        ]}
        yAxisLabel="kW"
      />

      {costSection}
      {greenOpsSection}
      {scheduleSection}
    </PageShell>
  );
}
