"use client";

export default function Error({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
      <p className="text-sm font-medium text-red-600">無法讀取對話列表</p>
      <p className="text-sm text-foreground/70">
        請確認 backend 是否已啟動（`uvicorn app.main:app --reload --app-dir
        backend`）。
      </p>
      <p className="text-xs text-foreground/50">{error.message}</p>
      <button
        type="button"
        onClick={() => unstable_retry()}
        className="mt-2 rounded-md border border-black/10 px-3 py-1.5 text-sm hover:bg-foreground/5 dark:border-white/10"
      >
        重試
      </button>
    </div>
  );
}
