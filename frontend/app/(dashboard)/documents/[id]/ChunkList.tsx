import type { ChunkSummary } from "@/lib/api/types";

function pageRangeLabel(chunk: ChunkSummary): string {
  if (chunk.pdf_page_number_start === chunk.pdf_page_number_end) {
    return `第 ${chunk.pdf_page_number_start} 頁`;
  }
  return `第 ${chunk.pdf_page_number_start}–${chunk.pdf_page_number_end} 頁`;
}

function formatDateTime(value: string | null): string {
  if (value === null) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-Hant");
}

function formatCell(value: string | number | null): string {
  return value === null ? "—" : String(value);
}

// Server Component: no client JS needed. <details>/<summary> gives compact,
// expandable cards for free -- chunk counts can run into the hundreds
// (e.g. a 120-page PDF), so a single flat table or all-expanded view would
// be unusable; this lets a reviewer scan the summary line and only expand
// the chunks they actually want to inspect.
export default function ChunkList({ chunks }: { chunks: ChunkSummary[] }) {
  return (
    <div className="space-y-2">
      {chunks.map((chunk) => (
        <details
          key={chunk.chunk_id}
          className="rounded-lg border border-black/10 dark:border-white/10"
        >
          <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 px-4 py-3 text-sm">
            <span className="inline-block rounded-full border border-black/10 px-2 py-0.5 text-xs dark:border-white/10">
              {chunk.chunk_type}
            </span>
            <span className="text-foreground/70">{pageRangeLabel(chunk)}</span>
            {chunk.section_title && (
              <span className="text-foreground/60">
                · {chunk.section_title}
              </span>
            )}
            {chunk.table_title && (
              <span className="text-foreground/60">· {chunk.table_title}</span>
            )}
          </summary>

          <div className="border-t border-black/10 px-4 py-3 text-sm dark:border-white/10">
            <p className="whitespace-pre-wrap text-foreground/80">
              {chunk.content}
            </p>

            <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-1 text-xs text-foreground/60 sm:grid-cols-3">
              <div>
                <dt>chunk_id</dt>
                <dd className="truncate font-mono">{chunk.chunk_id}</dd>
              </div>
              <div>
                <dt>strategy_name</dt>
                <dd>{chunk.strategy_name}</dd>
              </div>
              <div>
                <dt>embedding_provider</dt>
                <dd>{formatCell(chunk.embedding_provider)}</dd>
              </div>
              <div>
                <dt>embedding_model</dt>
                <dd>{formatCell(chunk.embedding_model)}</dd>
              </div>
              <div>
                <dt>embedding_dimensions</dt>
                <dd>{formatCell(chunk.embedding_dimensions)}</dd>
              </div>
              <div>
                <dt>embedded_at</dt>
                <dd>{formatDateTime(chunk.embedded_at)}</dd>
              </div>
            </dl>
          </div>
        </details>
      ))}
    </div>
  );
}
