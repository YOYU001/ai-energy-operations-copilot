import Link from "next/link";

import ConfidenceBadge from "@/components/ui/ConfidenceBadge";
import type { CaseSearchResult } from "@/lib/api/types";

function formatCell(value: string | null): string {
  return value === null || value === "" ? "—" : value;
}

export default function SimilarCasesList({
  results,
}: {
  results: CaseSearchResult[];
}) {
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
            <span className="text-xs text-foreground/60">
              {r.symptoms_similarity}
            </span>
          </div>
          <p className="mt-1 line-clamp-2 text-foreground/70">
            {formatCell(r.symptoms)}
          </p>
          {(r.matches.length > 0 || r.differs.length > 0) && (
            <div className="mt-2 flex flex-wrap gap-1 text-xs">
              {r.matches.map((m) => (
                <span
                  key={`match-${m}`}
                  className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-emerald-700 dark:bg-emerald-400/10 dark:text-emerald-400"
                >
                  {m}
                </span>
              ))}
              {r.differs.map((d) => (
                <span
                  key={`differ-${d}`}
                  className="rounded-full bg-foreground/10 px-2 py-0.5 text-foreground/60"
                >
                  {d}
                </span>
              ))}
            </div>
          )}
        </Link>
      ))}
    </div>
  );
}
