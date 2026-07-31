"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import EmptyState from "@/components/ui/EmptyState";
import StatusBadge from "@/components/ui/StatusBadge";
import type { DocumentSummary } from "@/lib/api/types";

const POLL_INTERVAL_MS = 3000;

function formatCell(value: string | number | null): string {
  return value === null ? "—" : String(value);
}

function formatDate(value: string | null): string {
  if (value === null) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-Hant");
}

export default function DocumentsList({
  documents,
}: {
  documents: DocumentSummary[];
}) {
  const router = useRouter();
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const hasProcessing = documents.some((d) => d.status === "processing");

  useEffect(() => {
    // Only poll while at least one document is still processing; the
    // moment none are, this effect's cleanup (or the next run with
    // hasProcessing=false) clears the interval -- no permanent background
    // polling, no new endpoint/WebSocket.
    if (!hasProcessing) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return;
    }

    intervalRef.current = setInterval(() => {
      router.refresh();
    }, POLL_INTERVAL_MS);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [hasProcessing, router]);

  if (documents.length === 0) {
    return <EmptyState message="目前沒有任何文件，請先上傳 PDF。" />;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-black/10 dark:border-white/10">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-black/10 dark:border-white/10">
          <tr>
            <th className="px-3 py-2 font-medium">File</th>
            <th className="px-3 py-2 font-medium">Uploaded</th>
            <th className="px-3 py-2 font-medium">Pages</th>
            <th className="px-3 py-2 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {documents.map((doc) => (
            <tr
              key={doc.id}
              className="border-b border-black/5 last:border-0 dark:border-white/5"
            >
              <td className="px-3 py-2">
                <Link
                  href={`/documents/${doc.id}`}
                  className="underline hover:no-underline"
                >
                  {formatCell(doc.file_name)}
                </Link>
              </td>
              <td className="px-3 py-2">{formatDate(doc.uploaded_at)}</td>
              <td className="px-3 py-2">{formatCell(doc.total_pages)}</td>
              <td className="px-3 py-2">
                <StatusBadge status={doc.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
