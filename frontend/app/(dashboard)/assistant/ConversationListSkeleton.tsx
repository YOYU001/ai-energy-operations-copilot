// Step 12 Frontend Slice 2: first skeleton primitive in this codebase --
// used only while the conversation list is loading (route-level
// loading.tsx) or briefly refetching client-side. Deliberately minimal
// (pulsing bars), matching this project's existing plain, unadorned UI
// style rather than a fully custom shimmer animation.
export default function ConversationListSkeleton() {
  return (
    <div className="flex flex-col gap-2" aria-hidden="true">
      {Array.from({ length: 6 }).map((_, index) => (
        <div key={index} className="h-8 animate-pulse rounded-md bg-foreground/10" />
      ))}
    </div>
  );
}
