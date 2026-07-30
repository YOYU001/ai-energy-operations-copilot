import Link from "next/link";

export default function SearchForm({ query }: { query: string }) {
  return (
    <form action="/cases" className="flex gap-2">
      <input
        type="text"
        name="q"
        defaultValue={query}
        placeholder="搜尋案件（例如：電池未依預期放電）"
        aria-label="搜尋案件"
        className="w-full rounded-md border border-black/10 bg-transparent px-3 py-1.5 text-sm dark:border-white/10"
      />
      <button
        type="submit"
        className="shrink-0 rounded-md border border-black/10 px-3 py-1.5 text-sm hover:bg-foreground/5 dark:border-white/10"
      >
        搜尋
      </button>
      {query && (
        <Link
          href="/cases"
          className="shrink-0 rounded-md border border-black/10 px-3 py-1.5 text-sm hover:bg-foreground/5 dark:border-white/10"
        >
          清除
        </Link>
      )}
    </form>
  );
}
