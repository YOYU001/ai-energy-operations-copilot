import ConversationListSkeleton from "./ConversationListSkeleton";

export default function Loading() {
  return (
    <div className="flex h-full">
      <div className="hidden w-64 flex-col gap-3 border-r border-black/10 px-3 py-4 dark:border-white/10 md:flex">
        <div className="h-8 animate-pulse rounded-md bg-foreground/10" />
        <ConversationListSkeleton />
      </div>
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-foreground/60">載入中...</p>
      </div>
    </div>
  );
}
