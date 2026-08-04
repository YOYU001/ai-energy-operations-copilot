import MessageListSkeleton from "./MessageListSkeleton";

// Step 12 Frontend Slice 3: suspense fallback for this route segment only
// -- the conversation sidebar (AssistantShell, in the parent layout) is
// not part of this boundary and stays mounted while this shows.
export default function Loading() {
  return (
    <div className="flex h-full flex-col p-4">
      <div className="h-5 w-32 animate-pulse rounded-md bg-foreground/10" />
      <div className="mt-2 min-h-0 flex-1">
        <MessageListSkeleton />
      </div>
    </div>
  );
}
