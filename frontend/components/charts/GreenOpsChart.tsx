"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type {
  GreenOpsComponentName,
  GreenOpsComponentScore,
  GreenOpsSiteResult,
} from "@/lib/api/types";

const INSUFFICIENT_COLOR = "transparent";
// One consistent green for every computed score -- per user decision (a):
// independent parameter, no red/yellow/green score-threshold semantics, to
// avoid introducing a rating scale the backend rules don't define.
const BAR_COLOR = "#22c55e";

// Explicit display order: pv_utilization -> battery_operation ->
// grid_dependency -> battery_health. Not backend array order, not
// alphabetical -- a fixed rank mapping so sortedComponents() is stable.
export const COMPONENT_ORDER: Record<GreenOpsComponentName, number> = {
  pv_utilization: 0,
  battery_operation: 1,
  grid_dependency: 2,
  battery_health: 3,
};

export const COMPONENT_LABELS: Record<GreenOpsComponentName, string> = {
  pv_utilization: "PV 利用率",
  battery_operation: "電池操作",
  grid_dependency: "電網依賴度",
  battery_health: "電池健康度",
};

// Copies before sorting -- Array.prototype.sort mutates its receiver, and
// components is a prop, so it must never be mutated in place.
export function sortedComponents(
  components: GreenOpsComponentScore[],
): GreenOpsComponentScore[] {
  return [...components].sort(
    (a, b) => COMPONENT_ORDER[a.component] - COMPONENT_ORDER[b.component],
  );
}

interface GreenOpsChartDatum {
  component: GreenOpsComponentName;
  label: string;
  // Percentage of max_score, 0-100 -- NOT the raw score, which only ranges
  // up to each component's own max_score (20 or 25). Plotting raw scores
  // against a shared 0-100 domain would visually compress every bar.
  percentage: number | null; // null -> insufficient data, no bar drawn
  raw_score: number | null;
  max_score: number;
  insufficient: boolean;
}

function toChartDatum(c: GreenOpsComponentScore): GreenOpsChartDatum {
  const insufficient = c.status === "insufficient_data";
  return {
    component: c.component,
    label: COMPONENT_LABELS[c.component],
    percentage: insufficient ? null : ((c.score as number) / c.max_score) * 100,
    raw_score: insufficient ? null : c.score,
    max_score: c.max_score,
    insufficient,
  };
}

function formatScore(value: number): string {
  return value.toLocaleString("zh-Hant", { maximumFractionDigits: 2 });
}

function GreenOpsTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: GreenOpsChartDatum }>;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const datum = payload[0].payload;
  return (
    <div className="rounded-md border border-black/10 bg-background p-2 text-xs shadow-sm dark:border-white/10">
      <p className="font-medium">{datum.label}</p>
      <p>
        {datum.insufficient
          ? "資料不足"
          : `分數：${formatScore(datum.raw_score as number)} / ${formatScore(datum.max_score)}（${formatScore(datum.percentage as number)}%）`}
      </p>
    </div>
  );
}

export function GreenOpsScoreBarChart({
  siteId,
  components,
}: {
  siteId: string;
  components: GreenOpsComponentScore[];
}) {
  const data = sortedComponents(components).map(toChartDatum);
  const insufficientComponents = data.filter((d) => d.insufficient);

  const summaryText = data
    .map((d) =>
      d.insufficient
        ? `${d.label}：資料不足`
        : `${d.label}：${formatScore(d.raw_score as number)} / ${formatScore(d.max_score)}`,
    )
    .join("；");

  return (
    <div>
      <div
        role="img"
        aria-label={`${siteId} Green Operations Index 分項分數長條圖（百分比）。${summaryText}`}
      >
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={data}>
            <CartesianGrid
              strokeDasharray="3 3"
              className="stroke-black/10 dark:stroke-white/10"
            />
            <XAxis dataKey="label" tick={{ fontSize: 12 }} />
            <YAxis
              domain={[0, 100]}
              tick={{ fontSize: 12 }}
              label={{ value: "分項達成率 (%)", angle: -90, position: "insideLeft" }}
            />
            <Tooltip content={<GreenOpsTooltip />} />
            <Bar
              dataKey="percentage"
              isAnimationActive={false}
              name="Score (% of max)"
            >
              {data.map((d) => (
                <Cell
                  key={d.component}
                  fill={d.insufficient ? INSUFFICIENT_COLOR : BAR_COLOR}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {insufficientComponents.length > 0 && (
        <ul className="mt-2 text-xs text-foreground/60">
          {insufficientComponents.map((d) => (
            <li key={d.component}>
              {d.label}：資料不足以計算此分項
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function GreenOpsComponentGrid({
  components,
}: {
  components: GreenOpsComponentScore[];
}) {
  return (
    <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
      {sortedComponents(components).map((c) => (
        <div key={c.component}>
          <dt className="text-foreground/60">{COMPONENT_LABELS[c.component]}</dt>
          <dd>
            {c.status === "insufficient_data"
              ? "資料不足"
              : `${formatScore(c.score as number)} / ${formatScore(c.max_score)}`}
          </dd>
          {c.penalty_reasons.length > 0 && (
            <dd className="text-xs text-foreground/50">
              {c.penalty_reasons.join("、")}
            </dd>
          )}
        </div>
      ))}
    </dl>
  );
}

export function GreenOpsAggregateSummary({
  aggregate,
  siteCount,
}: {
  aggregate: GreenOpsSiteResult;
  siteCount: number;
}) {
  return (
    <div className="mt-4 rounded-lg border border-black/10 p-4 text-sm dark:border-white/10">
      <p className="font-medium">資料集彙總</p>
      <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
        <div>
          <dt className="text-foreground/60">總分</dt>
          <dd>
            {aggregate.total_score === null
              ? "資料不足"
              : `${formatScore(aggregate.total_score)} / 100`}
          </dd>
        </div>
        <div>
          <dt className="text-foreground/60">Second-life 加分</dt>
          <dd>
            {aggregate.second_life_bonus === null
              ? "資料不足"
              : formatScore(aggregate.second_life_bonus)}
          </dd>
        </div>
        <div>
          <dt className="text-foreground/60">站點數</dt>
          <dd>{siteCount}</dd>
        </div>
      </dl>
      {aggregate.warnings.length > 0 && (
        <ul className="mt-2 text-xs text-foreground/60">
          {aggregate.warnings.map((w, index) => (
            <li key={index}>
              {w.type}（{w.count} 筆{w.site_id ? `，site: ${w.site_id}` : ""}）
            </li>
          ))}
        </ul>
      )}
      <div className="mt-4">
        <GreenOpsComponentGrid components={aggregate.components} />
      </div>
    </div>
  );
}
