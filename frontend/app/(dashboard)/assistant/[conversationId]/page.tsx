import { notFound } from "next/navigation";
import { ApiError, getConversation } from "@/lib/api/client";
import MessageList from "./MessageList";

export const dynamic = "force-dynamic";

// Step 12 Frontend Slice 3: route-based conversation selection plus
// message history. Composer / POST message / SSE streaming are a later
// slice -- this page fetches the full ConversationDetail (conversation +
// its active messages) and hands the messages to the client-side
// MessageList for rendering and auto-scroll.
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
    <div className="flex h-full min-h-0 flex-col p-4">
      <h1 className="text-sm font-medium">{detail.conversation.title ?? "新對話"}</h1>
      <div className="mt-2 min-h-0 flex-1">
        <MessageList conversationId={id} messages={detail.messages} />
      </div>
    </div>
  );
}
