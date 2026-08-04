"use client";

import { useEffect, useMemo, useRef } from "react";
import type { ReactNode } from "react";
import EmptyState from "@/components/ui/EmptyState";
import MessageBubble from "./MessageBubble";
import type { MessageViewModel } from "./messageViewModel";

// Step 12 Frontend Slice 4: renders whatever view-model array ChatThread
// hands it (canonical history + any pending/local overlay already
// merged) plus an optional trailing panel (pre-stream error / "still
// confirming final status" notices). This component owns rendering and
// auto-scroll only -- no network/reducer logic lives here.
export default function MessageList({
  conversationId,
  messages,
  trailingPanel,
  onRegenerate,
  regenerateDisabled,
}: {
  conversationId: number;
  messages: MessageViewModel[];
  trailingPanel?: ReactNode;
  onRegenerate?: (parentUserMessageId: number) => void;
  regenerateDisabled?: boolean;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Slice 3 scrolled on messages.length alone; SSE token streaming grows
  // a bubble's content without changing the count, so the dependency
  // here also folds in total content length -- still a plain number, not
  // the array reference itself, so an unrelated re-render doesn't
  // re-trigger this.
  const scrollRevision = useMemo(
    () => messages.reduce((total, message) => total + message.content.length, messages.length),
    [messages],
  );

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [conversationId, scrollRevision]);

  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <EmptyState message="這個對話目前沒有訊息" />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-4">
      {messages.map((message) => (
        <MessageBubble
          key={message.id}
          message={message}
          onRegenerate={onRegenerate}
          regenerateDisabled={regenerateDisabled}
        />
      ))}
      {trailingPanel}
      <div ref={bottomRef} />
    </div>
  );
}
