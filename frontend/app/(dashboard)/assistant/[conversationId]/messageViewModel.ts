import type { ChatMessageSummary } from "@/lib/api/types";
import type { PendingTurn } from "./ChatThread";

// Step 12 Frontend Slice 4: the presentation-layer shape MessageBubble
// actually renders. `id` is a string on purpose -- canonical rows get a
// "c-" prefixed real DB id, pending/local rows get a "local-" prefixed
// clientId. Never mix a client-only id into ChatMessageSummary.id
// (number) itself.
export type ViewModelStatus = "completed" | "streaming" | "thinking" | "failed" | "aborted";

// Step 12 Frontend Slice 5: one line item from a tool_call/tool_result SSE
// pair. Deliberately NOT paired into a single {call, result} record --
// backend is a simple sequential generator so events arrive in a stable
// call-then-result order, but rendering them as an ordered list of
// independent entries means a pairing bug can never hide or misattribute
// an event. `detail` is either the JSON-stringified call arguments or the
// backend-provided summary string for a result -- never the raw,
// potentially large tool result payload itself.
export interface ToolActivityEntry {
  type: "call" | "result";
  toolName: string;
  detail: string;
  // multi-agent failure-mode sweep, TODO.md 2026-08-28/31: the SSE
  // contract previously had no id field for tool_call/tool_result at all,
  // so a duplicate/retried pair from the backend had nothing to dedupe
  // against and would render as duplicate rows. Paired with the backend's
  // own tool_call.id (unique per model-requested call within a turn), so
  // ChatThread's TOOL_ACTIVITY reducer case can dedupe on
  // `${toolCallId}:${type}`.
  toolCallId: string;
}

export interface MessageViewModel {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: ViewModelStatus;
  errorMessage: string | null;
  // Step 12 Frontend Slice 5: only ever non-null for a canonical assistant
  // row (backend guarantees role="assistant" -> parent_user_message_id
  // NOT NULL). Pending/local assistant bubbles always get null here on
  // purpose -- Regenerate targets a real, already-persisted user message,
  // and a bubble that hasn't been reconciled into canonical history yet
  // has nothing reliable to regenerate against.
  parentUserMessageId: number | null;
  // Step 12 Frontend Slice 5: only ever present on the assistant bubble
  // for the turn currently streaming/just-completed in THIS browser
  // session (see ChatThread's activityByMessageId). Canonical history
  // fetched fresh (reload, different session) never carries this --
  // backend's ChatMessageSummary has no tool_calls field.
  activity?: ToolActivityEntry[];
}

export function canonicalToViewModel(
  message: ChatMessageSummary,
  activity?: ToolActivityEntry[],
): MessageViewModel {
  return {
    id: `c-${message.id}`,
    role: message.role === "assistant" ? "assistant" : "user",
    content: message.content,
    status: (message.status as ViewModelStatus) ?? "completed",
    errorMessage: message.error_message,
    parentUserMessageId: message.role === "assistant" ? message.parent_user_message_id : null,
    activity: activity && activity.length > 0 ? activity : undefined,
  };
}

// Step 12 Frontend Slice 5: groups canonical messages by
// parent_user_message_id instead of relying on raw created_at order, so a
// regenerated reply (a brand-new row, timestamped "now") still renders
// directly under its original user message instead of jumping to the end
// of the conversation. Defensive against data this function does not
// expect to see in practice (backend only ever returns one active
// attempt per parent) -- rather than silently dropping anything
// unexpected, it appends it at the end with a console.warn.
export function orderCanonicalMessages(messages: ChatMessageSummary[]): ChatMessageSummary[] {
  const userMessages = messages.filter((m) => m.role === "user");
  const userIds = new Set(userMessages.map((m) => m.id));
  const assistantByParent = new Map<number, ChatMessageSummary[]>();
  const orphaned: ChatMessageSummary[] = [];

  for (const m of messages) {
    if (m.role !== "assistant") continue;
    if (m.parent_user_message_id === null || !userIds.has(m.parent_user_message_id)) {
      console.warn(
        `assistant message ${m.id} has no matching parent user message in this view; appending at end`,
      );
      orphaned.push(m);
      continue;
    }
    const bucket = assistantByParent.get(m.parent_user_message_id);
    if (bucket) {
      bucket.push(m);
    } else {
      assistantByParent.set(m.parent_user_message_id, [m]);
    }
  }

  const ordered: ChatMessageSummary[] = [];
  for (const user of userMessages) {
    ordered.push(user);
    const replies = assistantByParent.get(user.id);
    if (replies === undefined) continue;
    if (replies.length === 1) {
      ordered.push(replies[0]);
      continue;
    }
    console.warn(
      `multiple assistant replies found for user message ${user.id}; using the most recently created one, appending the rest at end`,
    );
    const sorted = [...replies].sort(
      (a, b) => a.created_at.localeCompare(b.created_at) || a.id - b.id,
    );
    ordered.push(sorted[sorted.length - 1]);
    orphaned.push(...sorted.slice(0, -1));
  }

  ordered.push(...orphaned);
  return ordered;
}

function pendingAssistantViewModel(pending: PendingTurn): MessageViewModel | null {
  const activity = pending.toolActivity.length > 0 ? pending.toolActivity : undefined;
  const base = {
    id: `local-${pending.clientId}-assistant`,
    role: "assistant" as const,
    parentUserMessageId: null,
    activity,
  };

  switch (pending.phase) {
    case "streaming":
    case "stopping":
      return { ...base, content: pending.assistantContent, status: "streaming", errorMessage: null };
    case "thinking":
      return { ...base, content: pending.assistantContent, status: "thinking", errorMessage: null };
    case "completed":
      return { ...base, content: pending.assistantContent, status: "completed", errorMessage: null };
    case "failed-during-stream":
      return {
        ...base,
        content: pending.assistantContent,
        status: "failed",
        errorMessage: pending.errorMessage,
      };
    case "aborted":
      return { ...base, content: pending.assistantContent, status: "aborted", errorMessage: null };
    default:
      // idle / connecting / failed-before-stream: no assistant bubble yet
      // (message_started hasn't arrived, or never will for this turn).
      return null;
  }
}

// Step 12 Frontend Slice 5: `kind: "send"` still returns 0-2 bubbles
// (optimistic user bubble + assistant bubble once there's something to
// show), exactly Slice 4's behavior. `kind: "regenerate"` returns only
// the assistant bubble (0 or 1) -- the user message being regenerated
// already exists in canonical history, so no new user bubble is ever
// synthesized for it.
export function pendingTurnToViewModels(pending: PendingTurn): MessageViewModel[] {
  const assistantModel = pendingAssistantViewModel(pending);

  if (pending.kind === "regenerate") {
    return assistantModel ? [assistantModel] : [];
  }

  const userBubble: MessageViewModel = {
    id: `local-${pending.clientId}-user`,
    role: "user",
    content: pending.userContent,
    status: "completed",
    errorMessage: null,
    parentUserMessageId: null,
  };
  return assistantModel ? [userBubble, assistantModel] : [userBubble];
}
