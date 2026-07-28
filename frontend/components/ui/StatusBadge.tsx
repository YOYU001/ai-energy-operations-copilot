const STATUS_STYLES: Record<string, string> = {
  processing:
    "bg-amber-500/10 text-amber-700 dark:bg-amber-400/10 dark:text-amber-400",
  ready:
    "bg-emerald-500/10 text-emerald-700 dark:bg-emerald-400/10 dark:text-emerald-400",
  failed: "bg-red-500/10 text-red-700 dark:bg-red-400/10 dark:text-red-400",
};

const STATUS_LABELS: Record<string, string> = {
  processing: "處理中",
  ready: "已就緒",
  failed: "失敗",
};

export default function StatusBadge({ status }: { status: string }) {
  const style =
    STATUS_STYLES[status] ??
    "bg-foreground/10 text-foreground/70 dark:bg-foreground/10";
  const label = STATUS_LABELS[status] ?? status;

  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${style}`}
    >
      {label}
    </span>
  );
}
