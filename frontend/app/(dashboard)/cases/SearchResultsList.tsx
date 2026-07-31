import Link from "next/link";

import ConfidenceBadge from "@/components/ui/ConfidenceBadge";
import EmptyState from "@/components/ui/EmptyState";
import type { CaseSearchResult } from "@/lib/api/types";

function formatCell(value: string | null): string {
  return value === null || value === "" ? "—" : value;
}

export default function SearchResultsList({
  results,
}: {
  results: CaseSearchResult[];
}) {
  if (results.length === 0) {
    return <EmptyState message="沒有符合搜尋內容的案件，請嘗試其他描述。" />;
  }

  return (
    <div className="space-y-2">
      {results.map((r) => (
        <Link
          key={r.case_id}
          href={`/cases/${encodeURIComponent(r.case_id)}`}
          className="block rounded-lg border border-black/10 p-4 text-sm hover:bg-foreground/5 dark:border-white/10"
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{r.case_id}</span>
            <span className="inline-block rounded-full border border-black/10 px-2 py-0.5 text-xs dark:border-white/10">
              {formatCell(r.event_type)}
            </span>
            <ConfidenceBadge confidence={r.confidence} />
            <span className="text-xs text-foreground/60">
              final_score：{r.final_score.toFixed(3)}
            </span>
          </div>
          <p className="mt-1 line-clamp-2 text-foreground/70">
            {formatCell(r.symptoms)}
          </p>
          {r.tags && (
            <p className="mt-1 text-xs text-foreground/50">{r.tags}</p>
          )}
        </Link>
      ))}
    </div>
  );
}
