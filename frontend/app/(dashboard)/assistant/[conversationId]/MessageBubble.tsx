import type { ChatMessageSummary } from "@/lib/api/types";

// Step 12 Frontend Slice 3: role_shape_check in database/schema.sql
// guarantees role="user" rows are always status="completed" -- only
// assistant rows can be streaming/failed/aborted. This component doesn't
// special-case that on role though; it renders purely off `status` so it
// keeps working if that guarantee ever changes.
const STATUS_LABELS: Record<string, string> = {
  streaming: "回覆中…",
  failed: "回覆失敗",
  aborted: "已中止回覆",
};

export default function MessageBubble({ message }: { message: ChatMessageSummary }) {
  const isUser = message.role === "user";
  const isFailed = message.status === "failed";
  const statusLabel = STATUS_LABELS[message.status];

  const bubbleStyle = isUser
    ? "bg-foreground/10 text-foreground"
    : isFailed
      ? "border border-red-500/30 bg-red-500/5 text-foreground"
      : "border border-black/10 bg-background text-foreground dark:border-white/10";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[75%] rounded-lg px-3 py-2 text-sm ${bubbleStyle}`}>
        {statusLabel && (
          <p
            className={`mb-1 text-xs font-medium ${
              isFailed ? "text-red-600 dark:text-red-400" : "text-foreground/50"
            }`}
          >
            {statusLabel}
          </p>
        )}
        <p className="whitespace-pre-wrap break-words">{message.content}</p>
        {isFailed && message.error_message && (
          <p className="mt-1 text-xs text-red-600 dark:text-red-400">
            {message.error_message}
          </p>
        )}
      </div>
    </div>
  );
}
