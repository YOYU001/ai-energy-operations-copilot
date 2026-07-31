import { notFound } from "next/navigation";

import ChartSection from "@/components/charts/ChartSection";
import type { TimeSeriesDatum } from "@/components/charts/TimeSeriesChart";
import PageShell from "@/components/layout/PageShell";
import EmptyState from "@/components/ui/EmptyState";
import {
  ApiError,
  getDataset,
  getDatasetSummary,
  getDatasetTimeseries,
} from "@/lib/api/client";
import type { DatasetSummary, TimeseriesRow } from "@/lib/api/types";

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

export default async function DatasetChartsPage({
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
  const [summary, timeseries] = await Promise.all([
    getDatasetSummary(datasetId),
    getDatasetTimeseries(datasetId),
  ]);

  const pageTitle = dataset.name ?? `Dataset ${datasetId}`;

  if (summary.site_count > 1) {
    return (
      <PageShell title={pageTitle} description="資料集圖表">
        <div className="rounded-lg border border-dashed border-black/10 p-6 text-sm text-foreground/70 dark:border-white/10">
          此資料集包含 {summary.site_count} 個不同場域，圖表僅支援單一場域，暫不顯示。
        </div>
      </PageShell>
    );
  }

  if (timeseries.total === 0) {
    return (
      <PageShell title={pageTitle} description="資料集圖表">
        <EmptyState message="此資料集沒有時間序列資料。" />
      </PageShell>
    );
  }

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

  return (
    <PageShell
      title={pageTitle}
      description={`資料集圖表（共 ${timeseries.total} 筆）`}
    >
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
    </PageShell>
  );
}
