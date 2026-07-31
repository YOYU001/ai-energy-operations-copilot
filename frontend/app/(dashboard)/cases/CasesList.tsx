import Link from "next/link";

import EmptyState from "@/components/ui/EmptyState";
import type { CaseSummary } from "@/lib/api/types";

function formatCell(value: string | null): string {
  return value === null || value === "" ? "—" : value;
}

export default function CasesList({ cases }: { cases: CaseSummary[] }) {
  if (cases.length === 0) {
    return <EmptyState message="目前沒有任何案件記錄。" />;
  }

  return (
    <div className="space-y-2">
      {cases.map((c) => (
        <Link
          key={c.case_id}
          href={`/cases/${encodeURIComponent(c.case_id)}`}
          className="block rounded-lg border border-black/10 p-4 text-sm hover:bg-foreground/5 dark:border-white/10"
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{c.case_id}</span>
            <span className="inline-block rounded-full border border-black/10 px-2 py-0.5 text-xs dark:border-white/10">
              {formatCell(c.event_type)}
            </span>
            {c.severity && (
              <span className="text-xs text-foreground/60">
                嚴重程度：{c.severity}
              </span>
            )}
          </div>
          <p className="mt-1 line-clamp-2 text-foreground/70">
            {formatCell(c.symptoms)}
          </p>
          {c.tags && (
            <p className="mt-1 text-xs text-foreground/50">{c.tags}</p>
          )}
        </Link>
      ))}
    </div>
  );
}
