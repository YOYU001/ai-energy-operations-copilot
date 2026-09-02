"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { runAnalysisReport } from "@/app/(dashboard)/datasets/[id]/report/actions";

export default function RunReportButton({
  datasetId,
  hasExistingReport,
}: {
  datasetId: number;
  hasExistingReport: boolean;
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleClick = () => {
    setErrorMessage(null);
    startTransition(async () => {
      const result = await runAnalysisReport(datasetId, hasExistingReport);
      if (!result.ok) {
        setErrorMessage(
          result.status === 404
            ? "找不到此資料集，無法產生報告。"
            : "分析報告產生失敗，請稍後再試。",
        );
        return;
      }
      router.refresh();
    });
  };

  const label = hasExistingReport ? "重新產生報告" : "產生分析報告";

  return (
    <div className="mt-4">
      <button
        type="button"
        disabled={isPending}
        onClick={handleClick}
        className="rounded-md border border-black/10 px-3 py-1.5 text-sm hover:bg-foreground/5 disabled:opacity-50 dark:border-white/10"
      >
        {isPending ? "產生中..." : label}
      </button>
      {hasExistingReport && (
        <p className="mt-2 text-xs text-foreground/60">
          「重新產生報告」會依目前已執行的各項子分析重新擷取快照。
        </p>
      )}
      {errorMessage && (
        <p role="alert" className="mt-2 text-sm text-red-600 dark:text-red-400">
          {errorMessage}
        </p>
      )}
    </div>
  );
}
