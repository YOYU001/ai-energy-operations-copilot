import PageShell from "@/components/layout/PageShell";
import { getHealth, getVersion } from "@/lib/api/client";

export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  const [health, version] = await Promise.all([getHealth(), getVersion()]);

  return (
    <PageShell title="Overview" description="Backend 連線狀態與系統概覽">
      <div className="rounded-lg border border-black/10 p-4 dark:border-white/10">
        <p className="text-sm font-medium">已連線</p>
        <p className="mt-1 text-sm text-foreground/70">
          status: {health.status}
        </p>
        <p className="text-sm text-foreground/70">
          version: {version.version}
        </p>
      </div>
    </PageShell>
  );
}
