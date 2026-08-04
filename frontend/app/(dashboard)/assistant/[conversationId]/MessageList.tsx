"use client";

import { useEffect, useRef } from "react";
import EmptyState from "@/components/ui/EmptyState";
import type { ChatMessageSummary } from "@/lib/api/types";
import MessageBubble from "./MessageBubble";

// Step 12 Frontend Slice 3: page.tsx is a Server Component that re-fetches
// ConversationDetail on every route change, so switching conversations
// naturally passes a fresh `messages` array here -- no client-side refetch
// needed. This component only owns rendering and scroll-to-bottom.
export default function MessageList({
  conversationId,
  messages,
}: {
  conversationId: number;
  messages: ChatMessageSummary[];
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // messages.length (not the array itself) is the dependency: a new array
  // reference on every render would re-trigger this even when nothing
  // actually changed.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [conversationId, messages.length]);

  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <EmptyState message="這個對話目前沒有訊息" />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto">
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
