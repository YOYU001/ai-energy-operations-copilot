"use client";

import { useState } from "react";

import type { ScheduleRecommendation } from "@/lib/api/types";

const ACTION_LABELS: Record<string, string> = {
  charge: "充電 (charge)",
  discharge: "放電 (discharge)",
  idle: "待機 (idle)",
  hold: "保持 (hold)",
};

const PRICE_LABELS: Record<string, string> = {
  low: "低價 (low)",
  neutral: "中性 (neutral)",
  high: "高價 (high)",
};

const COLLAPSED_ROW_LIMIT = 20;

// Deliberately not toLocaleString("zh-Hant") -- this runs inside a "use
// client" component's unconditional render (server AND client, unlike
// TimeSeriesChart's Tooltip labelFormatter which only ever runs client-side
// on hover). Server-side Node's ICU data can format the same Date
// differently from the browser's, which React flags as a hydration
// mismatch. A manually-built string is deterministic on both sides.
function formatTimestamp(iso: string | null): string {
  if (iso === null) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}/${pad(date.getMonth() + 1)}/${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export default function BatteryScheduleTable({
  recommendations,
}: {
  recommendations: ScheduleRecommendation[];
}) {
  const [expanded, setExpanded] = useState(false);

  if (recommendations.length === 0) {
    return (
      <p className="text-sm text-foreground/60">此排程建議結果沒有任何列可顯示。</p>
    );
  }

  const visibleRows = expanded
    ? recommendations
    : recommendations.slice(0, COLLAPSED_ROW_LIMIT);
  const hiddenCount = recommendations.length - visibleRows.length;

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-xs">
          <thead>
            <tr className="border-b border-black/10 text-foreground/60 dark:border-white/10">
              <th className="py-1.5 pr-4 font-medium">Timestamp</th>
              <th className="py-1.5 pr-4 font-medium">建議動作</th>
              <th className="py-1.5 pr-4 font-medium">電價分類</th>
              <th className="py-1.5 pr-4 font-medium">原因 (reason)</th>
              <th className="py-1.5 font-medium">警告</th>
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((rec, index) => (
              <tr
                key={index}
                className="border-b border-black/5 last:border-0 dark:border-white/5"
              >
                <td className="py-1.5 pr-4 whitespace-nowrap">
                  {formatTimestamp(rec.timestamp)}
                </td>
                <td className="py-1.5 pr-4 whitespace-nowrap">
                  {ACTION_LABELS[rec.action] ?? rec.action}
                </td>
                <td className="py-1.5 pr-4 whitespace-nowrap">
                  {PRICE_LABELS[rec.price_classification] ?? rec.price_classification}
                </td>
                <td className="py-1.5 pr-4">{rec.reason}</td>
                <td className="py-1.5">
                  {rec.warnings.length > 0 ? rec.warnings.join("、") : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {hiddenCount > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          aria-expanded={expanded}
          className="mt-2 rounded-md border border-black/10 px-3 py-1 text-xs hover:bg-foreground/5 dark:border-white/10"
        >
          展開其餘 {hiddenCount} 筆
        </button>
      )}
      {expanded && recommendations.length > COLLAPSED_ROW_LIMIT && (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          aria-expanded={expanded}
          className="mt-2 rounded-md border border-black/10 px-3 py-1 text-xs hover:bg-foreground/5 dark:border-white/10"
        >
          收合
        </button>
      )}
    </div>
  );
}
