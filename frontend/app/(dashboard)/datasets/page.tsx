import Link from "next/link";

import PageShell from "@/components/layout/PageShell";
import EmptyState from "@/components/ui/EmptyState";
import { getDatasets } from "@/lib/api/client";

export const dynamic = "force-dynamic";

function formatCell(value: string | number | null): string {
  return value === null ? "—" : String(value);
}

function formatDate(value: string | null): string {
  if (value === null) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-Hant");
}

export default async function DatasetsPage() {
  const datasets = await getDatasets();

  return (
    <PageShell title="Datasets" description="能源時間序列資料集列表">
      {datasets.length === 0 ? (
        <EmptyState message="目前沒有任何資料集。" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-black/10 dark:border-white/10">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-black/10 dark:border-white/10">
              <tr>
                <th className="px-3 py-2 font-medium">ID</th>
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">File</th>
                <th className="px-3 py-2 font-medium">Row Count</th>
                <th className="px-3 py-2 font-medium">Start</th>
                <th className="px-3 py-2 font-medium">End</th>
                <th className="px-3 py-2 font-medium">Created</th>
                <th className="px-3 py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map((dataset) => (
                <tr
                  key={dataset.id}
                  className="border-b border-black/5 last:border-0 dark:border-white/5"
                >
                  <td className="px-3 py-2">{dataset.id}</td>
                  <td className="px-3 py-2">{formatCell(dataset.name)}</td>
                  <td className="px-3 py-2">{formatCell(dataset.file_name)}</td>
                  <td className="px-3 py-2">{formatCell(dataset.row_count)}</td>
                  <td className="px-3 py-2">{formatDate(dataset.start_time)}</td>
                  <td className="px-3 py-2">{formatDate(dataset.end_time)}</td>
                  <td className="px-3 py-2">{formatDate(dataset.created_at)}</td>
                  <td className="px-3 py-2">
                    <Link
                      href={`/datasets/${dataset.id}`}
                      className="inline-block rounded-md border border-black/10 px-3 py-1.5 text-sm hover:bg-foreground/5 dark:border-white/10"
                    >
                      查看圖表
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageShell>
  );
}
