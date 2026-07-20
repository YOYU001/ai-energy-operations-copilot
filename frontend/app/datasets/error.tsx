"use client";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-8">
      <p className="text-sm font-medium text-red-600">無法讀取資料集</p>
      <p className="mt-1 text-sm text-foreground/70">
        請確認 backend 是否已啟動（`uvicorn app.main:app --reload --app-dir
        backend`）。
      </p>
      <p className="mt-1 text-xs text-foreground/50">{error.message}</p>
      <button
        type="button"
        onClick={() => reset()}
        className="mt-4 rounded-md border border-black/10 px-3 py-1.5 text-sm hover:bg-foreground/5 dark:border-white/10"
      >
        重試
      </button>
    </div>
  );
}
