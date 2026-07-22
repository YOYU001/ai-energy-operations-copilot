import TimeSeriesChart, { type TimeSeriesChartProps } from "./TimeSeriesChart";

export default function ChartSection({
  title,
  description,
  ...chartProps
}: {
  title: string;
  description?: string;
} & TimeSeriesChartProps) {
  return (
    <section className="mb-8">
      <h2 className="text-sm font-semibold">{title}</h2>
      {description && (
        <p className="mt-1 text-xs text-foreground/60">{description}</p>
      )}
      <div className="mt-3">
        <TimeSeriesChart {...chartProps} />
      </div>
    </section>
  );
}
