import { notFound } from "next/navigation";
import { ApiError, getConversation } from "@/lib/api/client";

export const dynamic = "force-dynamic";

// Step 12 Frontend Slice 2: route-based conversation selection. Message
// history / Composer / SSE streaming are a later slice -- this page only
// proves the conversation actually exists and is accessible (404 via
// notFound() otherwise) and shows a placeholder.
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
    <div className="flex h-full flex-col p-4">
      <h1 className="text-sm font-medium">{detail.conversation.title ?? "新對話"}</h1>
      <p className="mt-2 text-sm text-foreground/60">
        訊息記錄與對話功能將於下一個 Slice 加入。
      </p>
    </div>
  );
}
