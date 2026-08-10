"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState, useTransition } from "react";

import { runCostAnalysis } from "@/app/(dashboard)/datasets/[id]/actions";

const PARAM_NAME = "max_expected_interval_hours";

export default function CostAnalysisForm({
  datasetId,
  initialValue,
}: {
  datasetId: number;
  initialValue: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [inputValue, setInputValue] = useState(initialValue);
  const [isPending, startTransition] = useTransition();
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErrorMessage(null);

    const trimmed = inputValue.trim();
    const parsed = Number(trimmed);
    if (trimmed === "" || !Number.isFinite(parsed) || parsed <= 0) {
      setErrorMessage("請輸入大於 0 的有效數字。");
      return;
    }

    startTransition(async () => {
      const outcome = await runCostAnalysis(datasetId, parsed);
      if (!outcome.ok) {
        setErrorMessage(
          outcome.status === 422
            ? "此資料集列數超過 MVP 分析上限，或參數不合法。"
            : "成本分析執行失敗，請稍後再試。",
        );
        return;
      }

      // Canonicalize the same way the backend does conceptually (repr of the
      // parsed float) -- JS has a single number type, so String(Number(x))
      // already collapses "6", "6.0", "6e0" to the same "6".
      const canonical = String(parsed);
      const currentValue = searchParams.get(PARAM_NAME);
      const nextParams = new URLSearchParams(searchParams.toString());
      nextParams.set(PARAM_NAME, canonical);
      const nextUrl = `${pathname}?${nextParams.toString()}`;

      if (currentValue === canonical) {
        // URL would be unchanged -- router.replace to an identical URL is a
        // no-op in the App Router, so force the Server Component to re-fetch
        // explicitly instead.
        router.refresh();
      } else {
        router.replace(nextUrl);
      }
    });
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-end"
    >
      <div className="flex flex-col gap-1">
        <label
          htmlFor="max-expected-interval-hours"
          className="text-xs text-foreground/60"
        >
          最大預期時間間隔（小時）
        </label>
        <input
          id="max-expected-interval-hours"
          name={PARAM_NAME}
          type="number"
          step="any"
          // Deliberately no `min="0"` -- that HTML5 constraint blocks
          // submission via the browser's own native validation UI before
          // our onSubmit handler ever runs, which would silently swallow
          // our own errorMessage state for negative/zero input. `required`
          // is kept (empty-field blocking is fine to leave to the browser),
          // but numeric-range validation is handled entirely in JS below so
          // the same visible error message always appears.
          required
          value={inputValue}
          onChange={(event) => setInputValue(event.target.value)}
          placeholder="例如：6（僅為範例，不會自動帶入）"
          aria-describedby="max-expected-interval-hours-hint"
          className="rounded-md border border-black/10 px-3 py-1.5 text-sm dark:border-white/10 dark:bg-transparent"
        />
        <p
          id="max-expected-interval-hours-hint"
          className="text-xs text-foreground/50"
        >
          暫定分析參數，待 real-world data profiling 後校準。
        </p>
      </div>
      <button
        type="submit"
        disabled={isPending}
        className="rounded-md border border-black/10 px-3 py-1.5 text-sm hover:bg-foreground/5 disabled:opacity-50 dark:border-white/10"
      >
        {isPending ? "分析中..." : "執行成本分析"}
      </button>
      {errorMessage && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {errorMessage}
        </p>
      )}
    </form>
  );
}
