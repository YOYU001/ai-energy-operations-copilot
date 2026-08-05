import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
      <p className="text-sm font-medium">找不到這個對話</p>
      <p className="text-sm text-foreground/70">
        這個對話可能已被刪除，或網址中的對話 ID 不正確。
      </p>
      <Link
        href="/assistant"
        className="rounded-md border border-black/10 px-3 py-1.5 text-sm hover:bg-foreground/5 dark:border-white/10"
      >
        回到 AI Assistant
      </Link>
    </div>
  );
}
