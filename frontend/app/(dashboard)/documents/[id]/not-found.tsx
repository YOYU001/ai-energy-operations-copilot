import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-8">
      <p className="text-sm font-medium">找不到這份文件</p>
      <p className="mt-1 text-sm text-foreground/70">
        這份文件可能已被刪除，或網址中的 ID 不正確。
      </p>
      <Link
        href="/documents"
        className="mt-4 inline-block rounded-md border border-black/10 px-3 py-1.5 text-sm hover:bg-foreground/5 dark:border-white/10"
      >
        回到 Documents 列表
      </Link>
    </div>
  );
}
