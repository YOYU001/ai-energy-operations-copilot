"use client";

import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { TimeSeriesDatum } from "@/components/charts/TimeSeriesChart";
import type { ScheduleRecommendation } from "@/lib/api/types";

type ActionShape = "triangle-up" | "triangle-down" | "circle" | "square";

interface ActionStyle {
  color: string;
  label: string;
  shape: ActionShape;
}

// Color-blind-friendly palette (Okabe-Ito derived) + a distinct shape per
// action, so the encoding never relies on hue alone.
const ACTION_STYLE: Record<string, ActionStyle> = {
  charge: { color: "#0072B2", label: "充電 (charge)", shape: "triangle-up" },
  discharge: { color: "#D55E00", label: "放電 (discharge)", shape: "triangle-down" },
  idle: { color: "#6B7280", label: "待機 (idle)", shape: "circle" },
  hold: { color: "#CC79A7", label: "保持 (hold)", shape: "square" },
};

const ACTION_ORDER = ["charge", "discharge", "idle", "hold"];

export interface ScheduleActionPoint {
  timestamp: string;
  battery_power_kw: number;
  action: string;
}

function isValidNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

// Only an index-aligned, timestamp-exact match may produce a marker (Step
// 13 Battery Scheduling frontend decision, 2026-08-14): the schedule API's
// recommendations array shares the same ORDER BY as the chart's timeseries
// query, but that positional coupling is never trusted blindly -- every
// point is re-verified by comparing timestamps before it is allowed onto
// the chart.
export function alignRecommendations(
  data: TimeSeriesDatum[],
  recommendations: ScheduleRecommendation[],
): { points: ScheduleActionPoint[]; alignedCount: number; failedCount: number } {
  const points: ScheduleActionPoint[] = [];
  let failedCount = 0;

  for (let i = 0; i < data.length; i++) {
    const rec = recommendations[i];
    const datum = data[i];
    if (rec === undefined || rec.timestamp !== datum.timestamp) {
      failedCount += 1;
      continue;
    }
    const value = datum.battery_power_kw;
    if (isValidNumber(value) && datum.timestamp !== null) {
      points.push({ timestamp: datum.timestamp, battery_power_kw: value, action: rec.action });
    }
  }

  return { points, alignedCount: data.length - failedCount, failedCount };
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

function shapePath(shape: ActionShape, cx: number, cy: number, size: number) {
  switch (shape) {
    case "triangle-up":
      return (
        <polygon points={`${cx},${cy - size} ${cx - size},${cy + size} ${cx + size},${cy + size}`} />
      );
    case "triangle-down":
      return (
        <polygon points={`${cx},${cy + size} ${cx - size},${cy - size} ${cx + size},${cy - size}`} />
      );
    case "circle":
      return <circle cx={cx} cy={cy} r={size} />;
    case "square":
      return <rect x={cx - size} y={cy - size} width={size * 2} height={size * 2} />;
    default:
      return null;
  }
}

function renderActionMarker(props: {
  cx?: number;
  cy?: number;
  payload?: ScheduleActionPoint;
}) {
  const { cx, cy, payload } = props;
  if (cx === undefined || cy === undefined || !payload) return null;
  const style = ACTION_STYLE[payload.action];
  if (!style) return null;
  return (
    <g fill={style.color} stroke="none">
      {shapePath(style.shape, cx, cy, 5)}
    </g>
  );
}

function ActionLegendSwatch({ shape, color }: { shape: ActionShape; color: string }) {
  return (
    <svg width={12} height={12} viewBox="-6 -6 12 12" aria-hidden="true">
      <g fill={color} stroke="none">
        {shapePath(shape, 0, 0, 5)}
      </g>
    </svg>
  );
}

export default function BatteryScheduleOverlay({
  data,
  recommendations,
  isTruncated,
  totalRecommendations,
}: {
  data: TimeSeriesDatum[];
  recommendations: ScheduleRecommendation[];
  isTruncated: boolean;
  totalRecommendations: number;
}) {
  const { points, alignedCount, failedCount } = alignRecommendations(data, recommendations);

  if (alignedCount === 0) {
    // 100% alignment failure -- fall back to the plain line, no markers.
    return (
      <div>
        <div
          role="img"
          aria-label="折線圖：Battery Power（無法疊加排程建議標記）"
        >
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={data}>
              <CartesianGrid
                strokeDasharray="3 3"
                className="stroke-black/10 dark:stroke-white/10"
              />
              <XAxis dataKey="timestamp" tickFormatter={formatAxisTick} tick={{ fontSize: 12 }} />
              <YAxis
                label={{ value: "kW", angle: -90, position: "insideLeft" }}
                tick={{ fontSize: 12 }}
              />
              <Tooltip
                labelFormatter={(label: unknown) =>
                  formatTooltipLabel(typeof label === "string" ? label : null)
                }
              />
              <ReferenceLine
                y={0}
                stroke="var(--foreground)"
                strokeOpacity={0.35}
                strokeDasharray="4 4"
                label={{
                  value: "待機 (0 kW)",
                  position: "insideTopRight",
                  fill: "var(--foreground)",
                  fillOpacity: 0.6,
                  fontSize: 11,
                }}
              />
              <Line
                type="monotone"
                dataKey="battery_power_kw"
                name="Battery Power"
                stroke="#3b82f6"
                strokeWidth={2}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-2 text-xs text-foreground/60">
          此資料集的排程建議與圖表時間序列的 timestamp 全數對齊失敗，無法在圖上標示建議動作；下方明細表仍可查看完整的排程建議內容。
        </p>
      </div>
    );
  }

  return (
    <div>
      <div
        role="img"
        aria-label={`折線圖：Battery Power，疊加 ${points.length} 筆排程建議標記（充電/放電/待機/保持）`}
      >
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart data={data}>
            <CartesianGrid
              strokeDasharray="3 3"
              className="stroke-black/10 dark:stroke-white/10"
            />
            <XAxis dataKey="timestamp" tickFormatter={formatAxisTick} tick={{ fontSize: 12 }} />
            <YAxis
              label={{ value: "kW", angle: -90, position: "insideLeft" }}
              tick={{ fontSize: 12 }}
            />
            <Tooltip
              labelFormatter={(label: unknown) =>
                formatTooltipLabel(typeof label === "string" ? label : null)
              }
            />
            <ReferenceLine
              y={0}
              stroke="var(--foreground)"
              strokeOpacity={0.35}
              strokeDasharray="4 4"
              label={{
                value: "待機 (0 kW)",
                position: "insideTopRight",
                fill: "var(--foreground)",
                fillOpacity: 0.6,
                fontSize: 11,
              }}
            />
            <Line
              type="monotone"
              dataKey="battery_power_kw"
              name="Battery Power"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
            <Scatter
              data={points}
              dataKey="battery_power_kw"
              shape={renderActionMarker}
              isAnimationActive={false}
              legendType="none"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-2 flex flex-wrap gap-3 text-xs text-foreground/70">
        {ACTION_ORDER.map((action) => {
          const style = ACTION_STYLE[action];
          return (
            <span key={action} className="inline-flex items-center gap-1.5">
              <ActionLegendSwatch shape={style.shape} color={style.color} />
              {style.label}
            </span>
          );
        })}
      </div>

      <p className="mt-2 text-xs text-foreground/60">
        {isTruncated
          ? `圖表僅疊加前 ${data.length} 筆資料的排程建議標記（資料集共 ${totalRecommendations} 筆建議，完整內容請見下方明細表）。`
          : `已疊加 ${alignedCount} 筆資料點的排程建議標記。`}
        {failedCount > 0 &&
          ` 另有 ${failedCount} 筆因 timestamp 對齊失敗未顯示標記。`}
      </p>
    </div>
  );
}
