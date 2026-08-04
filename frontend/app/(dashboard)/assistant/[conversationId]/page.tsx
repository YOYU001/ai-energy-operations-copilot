import { notFound } from "next/navigation";
import { ApiError, getConversation } from "@/lib/api/client";
import ChatThread from "./ChatThread";

export const dynamic = "force-dynamic";

// Step 12 Frontend Slice 4: route-based conversation selection, message
// history, and now live send/stream. This page fetches the full
// ConversationDetail (conversation + its active messages) and hands the
// messages to ChatThread as `canonicalMessages` -- re-supplied fresh on
// every route change AND every router.refresh() ChatThread triggers
// during reconciliation, never just used once on mount.
//
// GET /conversations/{id} treats an archived conversation the same as a
// nonexistent one (backend/app/conversations_queries.py's
// get_conversation_with_active_messages excludes archived_at IS NOT NULL
// rows) -- so a direct URL to an archived conversation's id also 404s
// here, with no separate frontend-side archived check needed.
export default async function AssistantConversationPage({
  params,
}: {
  params: Promise<{ conversationId: string }>;
}) {
  const { conversationId } = await params;
  const id = Number(conversationId);

  let detail;
  try {
    detail = await getConversation(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <h1 className="p-4 pb-0 text-sm font-medium">{detail.conversation.title ?? "新對話"}</h1>
      <div className="min-h-0 flex-1">
        <ChatThread key={id} conversationId={id} canonicalMessages={detail.messages} />
      </div>
    </div>
  );
}
