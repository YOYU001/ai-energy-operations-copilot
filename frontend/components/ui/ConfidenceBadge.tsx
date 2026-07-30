const CONFIDENCE_STYLES: Record<string, string> = {
  high: "bg-emerald-500/10 text-emerald-700 dark:bg-emerald-400/10 dark:text-emerald-400",
  medium:
    "bg-amber-500/10 text-amber-700 dark:bg-amber-400/10 dark:text-amber-400",
  low: "bg-red-500/10 text-red-700 dark:bg-red-400/10 dark:text-red-400",
};

const CONFIDENCE_LABELS: Record<string, string> = {
  high: "高相關",
  medium: "中相關",
  low: "低相關",
};

export default function ConfidenceBadge({ confidence }: { confidence: string }) {
  const style =
    CONFIDENCE_STYLES[confidence] ??
    "bg-foreground/10 text-foreground/70 dark:bg-foreground/10";
  const label = CONFIDENCE_LABELS[confidence] ?? confidence;

  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${style}`}
    >
      {label}
    </span>
  );
}
