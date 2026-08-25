"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { runScheduleAnalysis } from "@/app/(dashboard)/datasets/[id]/actions";

export default function RunScheduleButton({
  datasetId,
}: {
  datasetId: number;
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleClick = () => {
    setErrorMessage(null);
    startTransition(async () => {
      const result = await runScheduleAnalysis(datasetId);
      if (!result.ok) {
        setErrorMessage(
          result.status === 422
            ? "此資料集列數超過 MVP 分析上限，暫不支援自動排程建議。"
            : "儲能排程建議執行失敗，請稍後再試。",
        );
        return;
      }
      router.refresh();
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
        {isPending ? "分析中..." : "執行儲能排程建議"}
      </button>
      {errorMessage && (
        <p role="alert" className="mt-2 text-sm text-red-600 dark:text-red-400">
          {errorMessage}
        </p>
      )}
    </div>
  );
}
