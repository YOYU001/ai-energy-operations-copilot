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

import type { CostSiteResult } from "@/lib/api/types";

const INSUFFICIENT_COLOR = "transparent";
const BAR_COLOR = "#3b82f6";

interface CostChartDatum {
  site_id: string;
  total_energy_cost: number | null; // null -> insufficient data, no bar drawn
  interval_count: number;
  total_arbitrage_saving: number;
  insufficient: boolean;
}

function isInsufficient(site: CostSiteResult): boolean {
  return site.interval_count === 0;
}

function toChartDatum(site: CostSiteResult): CostChartDatum {
  const insufficient = isInsufficient(site);
  return {
    site_id: site.site_id,
    // null, not 0 -- a real 0-height bar would visually claim "this site's
    // cost is zero," which is not something interval_count === 0 can prove
    // (docs/step13_rules_and_api_design.md's cost-estimation blocker: this
    // API cannot distinguish a genuine zero from missing-data-defaulted-to-zero,
    // but it CAN reliably tell "zero valid intervals" apart from "at least
    // one," which is exactly what interval_count captures).
    total_energy_cost: insufficient ? null : site.total_energy_cost,
    interval_count: site.interval_count,
    total_arbitrage_saving: site.total_arbitrage_saving,
    insufficient,
  };
}

function formatCost(value: number): string {
  return value.toLocaleString("zh-Hant", { maximumFractionDigits: 2 });
}

function CostTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: CostChartDatum }>;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const datum = payload[0].payload;
  return (
    <div className="rounded-md border border-black/10 bg-background p-2 text-xs shadow-sm dark:border-white/10">
      <p className="font-medium">{datum.site_id}</p>
      <p>
        {datum.insufficient
          ? "資料不足"
          : `成本：${formatCost(datum.total_energy_cost as number)}`}
      </p>
      <p>有效區間數：{datum.interval_count}</p>
      {!datum.insufficient && (
        <p>電池套利淨額：{formatCost(datum.total_arbitrage_saving)}</p>
      )}
    </div>
  );
}

export function CostComparisonBarChart({
  perSite,
}: {
  perSite: CostSiteResult[];
}) {
  const data = perSite.map(toChartDatum);
  const insufficientSites = data.filter((d) => d.insufficient);

  const summaryText = data
    .map((d) =>
      d.insufficient
        ? `${d.site_id}：資料不足`
        : `${d.site_id}：${formatCost(d.total_energy_cost as number)}（成本單位，依原始 electricity_price 尺度）`,
    )
    .join("；");

  return (
    <div>
      <div role="img" aria-label={`Cost Comparison 長條圖。${summaryText}`}>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={data}>
            <CartesianGrid
              strokeDasharray="3 3"
              className="stroke-black/10 dark:stroke-white/10"
            />
            <XAxis dataKey="site_id" tick={{ fontSize: 12 }} />
            <YAxis
              label={{
                value: "成本單位（依原始 electricity_price 尺度）",
                angle: -90,
                position: "insideLeft",
              }}
              tick={{ fontSize: 12 }}
            />
            <Tooltip content={<CostTooltip />} />
            <Bar
              dataKey="total_energy_cost"
              isAnimationActive={false}
              name="Total Energy Cost"
            >
              {data.map((d) => (
                <Cell
                  key={d.site_id}
                  fill={d.insufficient ? INSUFFICIENT_COLOR : BAR_COLOR}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {insufficientSites.length > 0 && (
        <ul className="mt-2 text-xs text-foreground/60">
          {insufficientSites.map((d) => (
            <li key={d.site_id}>
              {d.site_id}：資料不足（沒有可計算成本的有效時間區間）
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function CostAggregateSummary({
  aggregate,
  siteCount,
}: {
  aggregate: CostSiteResult;
  siteCount: number;
}) {
  const insufficient = isInsufficient(aggregate);

  return (
    <div className="mt-4 rounded-lg border border-black/10 p-4 text-sm dark:border-white/10">
      <p className="font-medium">資料集彙總</p>
      <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
        <div>
          <dt className="text-foreground/60">總成本</dt>
          <dd>
            {insufficient
              ? "資料不足"
              : formatCost(aggregate.total_energy_cost)}
          </dd>
        </div>
        <div>
          <dt className="text-foreground/60">電池套利淨額</dt>
          <dd>
            {insufficient
              ? "資料不足"
              : formatCost(aggregate.total_arbitrage_saving)}
          </dd>
        </div>
        <div>
          <dt className="text-foreground/60">站點數</dt>
          <dd>{siteCount}</dd>
        </div>
        <div>
          <dt className="text-foreground/60">有效區間數（加總）</dt>
          <dd>{aggregate.interval_count}</dd>
        </div>
      </dl>
    </div>
  );
}
