export default function EmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-dashed border-black/10 p-8 text-center text-sm text-foreground/60 dark:border-white/10">
      {message}
    </div>
  );
}
