import Link from "next/link";

import PageShell from "@/components/layout/PageShell";
import { getCases, searchCases } from "@/lib/api/client";

import CasesList from "./CasesList";
import SearchForm from "./SearchForm";
import SearchResultsList from "./SearchResultsList";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 10;

function parseOffset(raw: string | undefined): number {
  if (!raw) return 0;
  const parsed = Number(raw);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : 0;
}

export default async function CasesPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; offset?: string }>;
}) {
  const { q, offset: offsetRaw } = await searchParams;
  const query = (q ?? "").trim();
  const offset = parseOffset(offsetRaw);

  return (
    <PageShell title="Case Similarity" description="相似案件搜尋">
      <SearchForm query={query} />

      <div className="mt-6">
        {query ? (
          <SearchResults query={query} />
        ) : (
          <DefaultCasesList offset={offset} />
        )}
      </div>
    </PageShell>
  );
}

async function SearchResults({ query }: { query: string }) {
  const results = await searchCases({ query });
  return <SearchResultsList results={results} />;
}

async function DefaultCasesList({ offset }: { offset: number }) {
  const page = await getCases(PAGE_SIZE, offset);
  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < page.total;

  return (
    <>
      <CasesList cases={page.items} />
      {(hasPrev || hasNext) && (
        <div className="mt-4 flex items-center justify-between text-sm">
          {hasPrev ? (
            <Link
              href={`/cases?offset=${Math.max(0, offset - PAGE_SIZE)}`}
              className="rounded-md border border-black/10 px-3 py-1.5 hover:bg-foreground/5 dark:border-white/10"
            >
              上一頁
            </Link>
          ) : (
            <span />
          )}
          <span className="text-foreground/60">
            共 {page.total} 筆，第 {Math.floor(offset / PAGE_SIZE) + 1} 頁
          </span>
          {hasNext ? (
            <Link
              href={`/cases?offset=${offset + PAGE_SIZE}`}
              className="rounded-md border border-black/10 px-3 py-1.5 hover:bg-foreground/5 dark:border-white/10"
            >
              下一頁
            </Link>
          ) : (
            <span />
          )}
        </div>
      )}
    </>
  );
}
