// Step 12 Frontend Slice 3: route-level loading.tsx fallback shown while
// switching between conversations. Alternates alignment to loosely mirror
// the user/assistant bubble layout of the real MessageList.
export default function MessageListSkeleton() {
  return (
    <div className="flex flex-col gap-3" aria-hidden="true">
      {Array.from({ length: 5 }).map((_, index) => (
        <div key={index} className={`flex ${index % 2 === 0 ? "justify-start" : "justify-end"}`}>
          <div className="h-10 w-2/3 max-w-sm animate-pulse rounded-lg bg-foreground/10" />
        </div>
      ))}
    </div>
  );
}
