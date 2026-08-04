import type { ChatMessageSummary } from "@/lib/api/types";
import type { PendingTurn } from "./ChatThread";

// Step 12 Frontend Slice 4: the presentation-layer shape MessageBubble
// actually renders. `id` is a string on purpose -- canonical rows get a
// "c-" prefixed real DB id, pending/local rows get a "local-" prefixed
// clientId. Never mix a client-only id into ChatMessageSummary.id
// (number) itself.
export type ViewModelStatus = "completed" | "streaming" | "failed" | "aborted";

export interface MessageViewModel {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: ViewModelStatus;
  errorMessage: string | null;
}

export function canonicalToViewModel(message: ChatMessageSummary): MessageViewModel {
  return {
    id: `c-${message.id}`,
    role: message.role === "assistant" ? "assistant" : "user",
    content: message.content,
    status: (message.status as ViewModelStatus) ?? "completed",
    errorMessage: message.error_message,
  };
}

// Returns 0-2 bubbles for the turn currently in flight: the optimistic
// user bubble (always, once a turn exists) plus an assistant bubble once
// there is something to show for it. No assistant bubble is ever shown
// before message_started actually arrived (phase="connecting") -- and
// none at all for failed-before-stream, since in that case the backend
// never created an assistant row (see ChatThread's pre-stream error
// classification).
export function pendingTurnToViewModels(pending: PendingTurn): MessageViewModel[] {
  const userBubble: MessageViewModel = {
    id: `local-${pending.clientId}-user`,
    role: "user",
    content: pending.userContent,
    status: "completed",
    errorMessage: null,
  };

  switch (pending.phase) {
    case "idle":
    case "connecting":
    case "failed-before-stream":
      return [userBubble];
    case "streaming":
    case "stopping":
      return [
        userBubble,
        {
          id: `local-${pending.clientId}-assistant`,
          role: "assistant",
          content: pending.assistantContent,
          status: "streaming",
          errorMessage: null,
        },
      ];
    case "completed":
      return [
        userBubble,
        {
          id: `local-${pending.clientId}-assistant`,
          role: "assistant",
          content: pending.assistantContent,
          status: "completed",
          errorMessage: null,
        },
      ];
    case "failed-during-stream":
      return [
        userBubble,
        {
          id: `local-${pending.clientId}-assistant`,
          role: "assistant",
          content: pending.assistantContent,
          status: "failed",
          errorMessage: pending.errorMessage,
        },
      ];
    case "aborted":
      return [
        userBubble,
        {
          id: `local-${pending.clientId}-assistant`,
          role: "assistant",
          content: pending.assistantContent,
          status: "aborted",
          errorMessage: null,
        },
      ];
    default:
      return [userBubble];
  }
}
