"use client";

import { useState, useTransition } from "react";

import { runAnalysis } from "./actions";

export default function RunAnalysisButton({
  datasetId,
}: {
  datasetId: number;
}) {
  const [isPending, startTransition] = useTransition();
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleClick = () => {
    setErrorMessage(null);
    startTransition(async () => {
      const result = await runAnalysis(datasetId);
      if (!result.ok) {
        setErrorMessage(
          result.status === 422
            ? "此資料集列數超過 MVP 分析上限（50,000 筆），暫不支援自動診斷。"
            : "分析執行失敗，請稍後再試。",
        );
      }
    });
  };

  return (
    <div className="mt-4">
      <button
        type="button"
        disabled={isPending}
        onClick={handleClick}
        className="rounded-md border border-black/10 px-3 py-1.5 text-sm hover:bg-foreground/5 disabled:opacity-50 dark:border-white/10"
      >
        {isPending ? "分析中..." : "執行分析"}
      </button>
      {errorMessage && (
        <p className="mt-2 text-sm text-red-600">{errorMessage}</p>
      )}
    </div>
  );
}
