"use client";

import Link from "next/link";
import EmptyState from "@/components/ui/EmptyState";
import type { ConversationSummary } from "@/lib/api/types";

export default function ConversationList({
  conversations,
  selectedId,
  onArchive,
  onItemClick,
}: {
  conversations: ConversationSummary[];
  selectedId: number | null;
  onArchive: (id: number) => void;
  onItemClick?: () => void;
}) {
  if (conversations.length === 0) {
    return <EmptyState message="尚無對話，開始新的對話" />;
  }

  return (
    <ul className="flex flex-col gap-1">
      {conversations.map((conversation) => {
        const isActive = conversation.id === selectedId;
        return (
          <li key={conversation.id} className="group flex items-center gap-1">
            <Link
              href={`/assistant/${conversation.id}`}
              onClick={onItemClick}
              aria-current={isActive ? "page" : undefined}
              className={`block min-w-0 flex-1 truncate rounded-md px-3 py-2 text-sm transition-colors ${
                isActive
                  ? "bg-foreground/10 font-medium text-foreground"
                  : "text-foreground/70 hover:bg-foreground/5 hover:text-foreground"
              }`}
            >
              {conversation.title ?? "新對話"}
            </Link>
            <button
              type="button"
              aria-label="封存對話"
              onClick={() => onArchive(conversation.id)}
              className="shrink-0 rounded-md p-1.5 text-foreground/40 opacity-0 hover:bg-foreground/10 hover:text-foreground group-hover:opacity-100"
            >
              ×
            </button>
          </li>
        );
      })}
    </ul>
  );
}
