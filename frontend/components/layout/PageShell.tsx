export default function PageShell({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-8">
      <h1 className="text-xl font-semibold">{title}</h1>
      {description && (
        <p className="mt-1 text-sm text-foreground/70">{description}</p>
      )}
      <div className="mt-6">{children}</div>
    </div>
  );
}
