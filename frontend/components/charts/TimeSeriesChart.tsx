"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export interface TimeSeriesDatum {
  timestamp: string | null;
  [seriesKey: string]: string | number | null;
}

export interface TimeSeriesSeries {
  dataKey: string;
  label: string;
  color: string;
  unit?: string;
}

export interface TimeSeriesReferenceLine {
  value: number;
  label: string;
}

export interface TimeSeriesChartProps {
  data: TimeSeriesDatum[];
  series: TimeSeriesSeries[];
  yAxisLabel: string;
  referenceLines?: TimeSeriesReferenceLine[];
  emptyMessage?: string;
}

function formatAxisTick(iso: string | null): string {
  if (iso === null) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getMonth() + 1)}/${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatTooltipLabel(iso: string | null): string {
  if (iso === null) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-Hant");
}

function isValidNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function seriesHasValidData(data: TimeSeriesDatum[], dataKey: string): boolean {
  return data.some((point) => isValidNumber(point[dataKey]));
}

function summarizeSeries(data: TimeSeriesDatum[], s: TimeSeriesSeries): string {
  const values = data.map((point) => point[s.dataKey]).filter(isValidNumber);
  if (values.length === 0) return `${s.label}：無有效資料`;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const unitSuffix = s.unit ? ` ${s.unit}` : "";
  return `${s.label}：範圍 ${min}${unitSuffix} 至 ${max}${unitSuffix}`;
}

export default function TimeSeriesChart({
  data,
  series,
  yAxisLabel,
  referenceLines = [],
  emptyMessage = "此資料集缺少繪圖所需的有效資料。",
}: TimeSeriesChartProps) {
  const availableSeries = series.filter((s) =>
    seriesHasValidData(data, s.dataKey),
  );
  const missingSeries = series.filter(
    (s) => !seriesHasValidData(data, s.dataKey),
  );

  if (availableSeries.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-black/10 p-8 text-center text-sm text-foreground/60 dark:border-white/10">
        {emptyMessage}
      </div>
    );
  }

  const unitByLabel = new Map(series.map((s) => [s.label, s.unit]));
  const chartSummary = series.map((s) => summarizeSeries(data, s)).join("；");

  return (
    <div role="img" aria-label={`折線圖：${yAxisLabel}。${chartSummary}`}>
      {missingSeries.length > 0 && (
        <p className="mb-2 text-xs text-foreground/60">
          缺少以下欄位的有效資料：
          {missingSeries.map((s) => s.label).join("、")}
        </p>
      )}
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data}>
          <CartesianGrid
            strokeDasharray="3 3"
            className="stroke-black/10 dark:stroke-white/10"
          />
          <XAxis
            dataKey="timestamp"
            tickFormatter={formatAxisTick}
            tick={{ fontSize: 12 }}
          />
          <YAxis
            label={{ value: yAxisLabel, angle: -90, position: "insideLeft" }}
            tick={{ fontSize: 12 }}
          />
          <Tooltip
            labelFormatter={(label: unknown) =>
              formatTooltipLabel(typeof label === "string" ? label : null)
            }
            formatter={(value: unknown, name: unknown) => {
              if (!isValidNumber(value)) return [String(value), String(name)];
              const unit = unitByLabel.get(String(name));
              return [`${value}${unit ? ` ${unit}` : ""}`, String(name)];
            }}
          />
          {availableSeries.length > 1 && <Legend />}
          {availableSeries.map((s) => (
            <Line
              key={s.dataKey}
              type="monotone"
              dataKey={s.dataKey}
              name={s.label}
              stroke={s.color}
              strokeWidth={2}
              dot={false}
              connectNulls={false}
            />
          ))}
          {referenceLines.map((ref) => (
            <ReferenceLine
              key={`${ref.label}-${ref.value}`}
              y={ref.value}
              stroke="var(--foreground)"
              strokeOpacity={0.35}
              strokeDasharray="4 4"
              label={{
                value: ref.label,
                position: "insideTopRight",
                fill: "var(--foreground)",
                fillOpacity: 0.6,
                fontSize: 11,
              }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
