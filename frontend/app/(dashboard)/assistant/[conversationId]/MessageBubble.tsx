import type { MessageViewModel } from "./messageViewModel";
import ToolActivityPanel from "./ToolActivityPanel";

// Step 12 Frontend Slice 3/4/5: role_shape_check in database/schema.sql
// guarantees role="user" rows are always status="completed" -- only
// assistant rows can be streaming/failed/aborted. This component doesn't
// special-case that on role though; it renders purely off `status` so it
// keeps working if that guarantee ever changes. Slice 4: takes a
// MessageViewModel (string id) instead of ChatMessageSummary directly, so
// it renders canonical and pending/local bubbles identically.
const STATUS_LABELS: Record<string, string> = {
  streaming: "回覆中…",
  failed: "回覆失敗",
  aborted: "已中止回覆",
};

export default function MessageBubble({
  message,
  onRegenerate,
  regenerateDisabled,
}: {
  message: MessageViewModel;
  onRegenerate?: (parentUserMessageId: number) => void;
  regenerateDisabled?: boolean;
}) {
  const isUser = message.role === "user";
  const isFailed = message.status === "failed";
  const statusLabel = STATUS_LABELS[message.status];

  // Step 12 Frontend Slice 5: parentUserMessageId is only ever non-null on
  // a CANONICAL assistant bubble (see messageViewModel.ts) -- a
  // pending/local bubble never offers Regenerate, even if it's currently
  // failed/aborted, since it hasn't been reconciled into a real,
  // regenerable history entry yet.
  const canRegenerate =
    !isUser &&
    (message.status === "failed" || message.status === "aborted") &&
    message.parentUserMessageId !== null &&
    onRegenerate !== undefined;

  const bubbleStyle = isUser
    ? "bg-foreground/10 text-foreground"
    : isFailed
      ? "border border-red-500/30 bg-red-500/5 text-foreground"
      : "border border-black/10 bg-background text-foreground dark:border-white/10";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[75%] rounded-lg px-3 py-2 text-sm ${bubbleStyle}`}>
        {message.activity && message.activity.length > 0 && (
          <ToolActivityPanel entries={message.activity} />
        )}
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
        {isFailed && message.errorMessage && (
          <p className="mt-1 text-xs text-red-600 dark:text-red-400">
            {message.errorMessage}
          </p>
        )}
        {canRegenerate && (
          <button
            type="button"
            onClick={() => onRegenerate!(message.parentUserMessageId!)}
            disabled={regenerateDisabled}
            className="mt-2 rounded-md border border-black/10 px-2 py-1 text-xs hover:bg-foreground/5 disabled:opacity-50 dark:border-white/10"
          >
            重新產生回覆
          </button>
        )}
      </div>
    </div>
  );
}
