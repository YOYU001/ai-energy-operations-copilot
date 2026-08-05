"use client";

import Link from "next/link";
import { useEffect, useReducer, useRef } from "react";
import { useRouter } from "next/navigation";
import type { ChatMessageSummary } from "@/lib/api/types";
import Composer from "./Composer";
import MessageList from "./MessageList";
import {
  canonicalToViewModel,
  orderCanonicalMessages,
  pendingTurnToViewModels,
  type MessageViewModel,
  type ToolActivityEntry,
} from "./messageViewModel";
import { useSendMessage } from "./useSendMessage";

// Step 12 Frontend Slice 4: single client-side state owner for a
// conversation's live send/stream lifecycle. `canonicalMessages` is
// server-fetched truth (re-supplied via router.refresh() after page.tsx
// re-runs); `pendingTurn` is everything about the turn currently in
// flight that hasn't been reconciled into canonical history yet. Keeping
// these two separate -- instead of splicing a temporary id into
// ChatMessageSummary -- is deliberate: canonical ids are real DB numbers,
// pending ids are client-only and must never be confused with them.

export type RequestPhase =
  | "idle"
  | "connecting"
  | "streaming"
  | "stopping"
  | "completed"
  | "failed-before-stream"
  | "failed-during-stream"
  | "aborted";

export type PreStreamError =
  | { kind: "validation"; message: string }
  | { kind: "conversation-unavailable"; message: string }
  | { kind: "already-in-progress"; message: string }
  | { kind: "reconcile-required"; message: string };

export interface PendingTurn {
  // Step 12 Frontend Slice 5: "send" is a brand-new user turn (Composer);
  // "regenerate" re-asks an EXISTING user message identified by
  // parentUserMessageId -- no new user bubble is ever synthesized for it.
  kind: "send" | "regenerate";
  parentUserMessageId: number | null;
  clientId: string;
  phase: RequestPhase;
  userContent: string;
  assistantMessageId: number | null;
  attemptNumber: number | null;
  assistantContent: string;
  errorMessage: string | null;
  preStreamError: PreStreamError | null;
  toolActivity: ToolActivityEntry[];
}

// Step 12 Frontend Slice 5: keyed by the REAL assistant message id (known
// only once message_started arrives). Populated at RECONCILED time --
// see the reducer -- so a turn's tool activity survives canonical
// takeover instead of vanishing the instant pendingTurn is cleared. Only
// lives for this page session; a reload or conversation switch loses it
// (backend never returns tool_calls in ChatMessageSummary -- see
// messageViewModel.ts), which is an accepted, documented limitation.
export type ActivityByMessageId = Record<number, ToolActivityEntry[]>;

interface ChatThreadState {
  pendingTurn: PendingTurn | null;
  activityByMessageId: ActivityByMessageId;
}

export type Action =
  | { type: "SEND_REQUESTED"; clientId: string; content: string }
  | { type: "REGENERATE_REQUESTED"; clientId: string; parentUserMessageId: number }
  | { type: "MESSAGE_STARTED"; assistantMessageId: number; attemptNumber: number }
  | { type: "TOKEN_RECEIVED"; delta: string }
  | { type: "TOOL_ACTIVITY"; entry: ToolActivityEntry }
  | { type: "STOP_REQUESTED" }
  | { type: "ABORTED" }
  | { type: "MESSAGE_COMPLETED"; assistantMessageId: number }
  | { type: "STREAM_FAILED_DURING"; assistantMessageId?: number; error: string }
  | { type: "FAILED_BEFORE_STREAM"; preStreamError: PreStreamError }
  | { type: "RECONCILED" }
  | { type: "DISMISS_UNCERTAIN" };

const TERMINAL_RECONCILE_PHASES = new Set<RequestPhase>([
  "completed",
  "failed-during-stream",
  "aborted",
]);

const BUSY_PHASES = new Set<RequestPhase>(["connecting", "streaming", "stopping"]);

const MAX_RECONCILE_RETRIES = 3;
const RECONCILE_RETRY_DELAY_MS = 2000;

function freshPendingTurn(
  kind: "send" | "regenerate",
  clientId: string,
  parentUserMessageId: number | null,
  userContent: string,
): PendingTurn {
  return {
    kind,
    parentUserMessageId,
    clientId,
    phase: "connecting",
    userContent,
    assistantMessageId: null,
    attemptNumber: null,
    assistantContent: "",
    errorMessage: null,
    preStreamError: null,
    toolActivity: [],
  };
}

function reducer(state: ChatThreadState, action: Action): ChatThreadState {
  const pending = state.pendingTurn;

  switch (action.type) {
    case "SEND_REQUESTED":
      return { ...state, pendingTurn: freshPendingTurn("send", action.clientId, null, action.content) };
    case "REGENERATE_REQUESTED":
      return {
        ...state,
        pendingTurn: freshPendingTurn("regenerate", action.clientId, action.parentUserMessageId, ""),
      };
    case "MESSAGE_STARTED":
      if (pending === null || pending.phase !== "connecting") return state;
      return {
        ...state,
        pendingTurn: {
          ...pending,
          phase: "streaming",
          assistantMessageId: action.assistantMessageId,
          attemptNumber: action.attemptNumber,
        },
      };
    case "TOKEN_RECEIVED":
      if (pending === null || (pending.phase !== "streaming" && pending.phase !== "stopping")) {
        return state;
      }
      return {
        ...state,
        pendingTurn: { ...pending, assistantContent: pending.assistantContent + action.delta },
      };
    case "TOOL_ACTIVITY":
      if (pending === null || (pending.phase !== "streaming" && pending.phase !== "stopping")) {
        return state;
      }
      return {
        ...state,
        pendingTurn: { ...pending, toolActivity: [...pending.toolActivity, action.entry] },
      };
    case "STOP_REQUESTED":
      if (pending === null || (pending.phase !== "connecting" && pending.phase !== "streaming")) {
        return state;
      }
      return { ...state, pendingTurn: { ...pending, phase: "stopping" } };
    case "ABORTED":
      if (pending === null) return state;
      return { ...state, pendingTurn: { ...pending, phase: "aborted" } };
    case "MESSAGE_COMPLETED":
      if (pending === null) return state;
      return {
        ...state,
        pendingTurn: {
          ...pending,
          phase: "completed",
          assistantMessageId: pending.assistantMessageId ?? action.assistantMessageId,
        },
      };
    case "STREAM_FAILED_DURING":
      if (pending === null) return state;
      return {
        ...state,
        pendingTurn: {
          ...pending,
          phase: "failed-during-stream",
          assistantMessageId: pending.assistantMessageId ?? action.assistantMessageId ?? null,
          errorMessage: action.error,
        },
      };
    case "FAILED_BEFORE_STREAM":
      if (pending === null) return state;
      return {
        ...state,
        pendingTurn: { ...pending, phase: "failed-before-stream", preStreamError: action.preStreamError },
      };
    case "RECONCILED": {
      if (pending === null) return state;
      // Archive this turn's tool activity under its real assistant id
      // BEFORE dropping pendingTurn, so it survives canonical takeover
      // (messageViewModel's canonicalToViewModel looks it up by id).
      if (pending.assistantMessageId !== null && pending.toolActivity.length > 0) {
        return {
          pendingTurn: null,
          activityByMessageId: {
            ...state.activityByMessageId,
            [pending.assistantMessageId]: pending.toolActivity,
          },
        };
      }
      return { ...state, pendingTurn: null };
    }
    case "DISMISS_UNCERTAIN":
      return { ...state, pendingTurn: null };
    default:
      return state;
  }
}

export default function ChatThread({
  conversationId,
  canonicalMessages,
}: {
  conversationId: number;
  canonicalMessages: ChatMessageSummary[];
}) {
  const router = useRouter();
  const [state, dispatch] = useReducer(reducer, { pendingTurn: null, activityByMessageId: {} });
  const { send, regenerate, stop, cancelActive } = useSendMessage(conversationId, dispatch);

  const reconcileAttemptsRef = useRef(0);
  const reconcileTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function clearReconcileTimer() {
    if (reconcileTimerRef.current !== null) {
      clearTimeout(reconcileTimerRef.current);
      reconcileTimerRef.current = null;
    }
  }

  // Kick off one immediate refresh the moment a turn reaches a
  // terminal-ish local phase. The bounded retry loop (below) takes over
  // from there if that first refresh doesn't yet show a reconciled
  // canonical status.
  useEffect(() => {
    const pending = state.pendingTurn;
    if (pending === null || !TERMINAL_RECONCILE_PHASES.has(pending.phase)) return;
    if (pending.assistantMessageId === null) return;

    reconcileAttemptsRef.current = 0;
    clearReconcileTimer();
    router.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fire once per phase transition, not on every render
  }, [state.pendingTurn?.phase]);

  // Conversation-unavailable is a distinct case: no assistant id will
  // ever exist for it, so it can't go through the id-based reconcile
  // loop above. A single refresh (e.g. to drop it from the sidebar list)
  // is still useful, but never a resend.
  useEffect(() => {
    const pending = state.pendingTurn;
    if (pending?.phase === "failed-before-stream" && pending.preStreamError?.kind === "conversation-unavailable") {
      router.refresh();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.pendingTurn?.phase, state.pendingTurn?.preStreamError?.kind]);

  // Re-checked every time canonicalMessages changes (i.e. after every
  // router.refresh()): once the canonical assistant row for this turn
  // exists and is no longer "streaming", the whole pending turn -- user
  // bubble included -- is dropped in one step so canonical history takes
  // over cleanly, never leaving a stray optimistic user bubble behind.
  useEffect(() => {
    const pending = state.pendingTurn;
    if (pending === null || !TERMINAL_RECONCILE_PHASES.has(pending.phase)) return;
    if (pending.assistantMessageId === null) return;

    const canonical = canonicalMessages.find((m) => m.id === pending.assistantMessageId);
    if (canonical !== undefined && canonical.status !== "streaming") {
      clearReconcileTimer();
      dispatch({ type: "RECONCILED" });
      return;
    }

    if (reconcileAttemptsRef.current >= MAX_RECONCILE_RETRIES) {
      clearReconcileTimer();
      return; // bounded: stop automatic polling, leave the manual "重新整理" affordance
    }

    clearReconcileTimer();
    reconcileTimerRef.current = setTimeout(() => {
      reconcileAttemptsRef.current += 1;
      router.refresh();
    }, RECONCILE_RETRY_DELAY_MS);

    return clearReconcileTimer;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canonicalMessages, state.pendingTurn?.phase, state.pendingTurn?.assistantMessageId]);

  // Conversation switch remounts this component (page.tsx keys ChatThread
  // by conversationId), so this cleanup also covers "abort + clear timer
  // on conversation change" -- not just unmount.
  useEffect(() => {
    return () => {
      clearReconcileTimer();
      cancelActive();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleSend(content: string) {
    clearReconcileTimer();
    reconcileAttemptsRef.current = 0;
    send(content);
  }

  function handleRegenerate(parentUserMessageId: number) {
    clearReconcileTimer();
    reconcileAttemptsRef.current = 0;
    regenerate(parentUserMessageId);
  }

  function handleManualRefresh() {
    router.refresh();
  }

  function handleDismissUncertain() {
    clearReconcileTimer();
    dispatch({ type: "DISMISS_UNCERTAIN" });
  }

  const isBusy = state.pendingTurn !== null && BUSY_PHASES.has(state.pendingTurn.phase);
  const viewModels = buildViewModels(canonicalMessages, state.pendingTurn, state.activityByMessageId);

  const trailingPanel = state.pendingTurn ? (
    <TrailingPanel
      pending={state.pendingTurn}
      onRefresh={handleManualRefresh}
      onDismiss={handleDismissUncertain}
    />
  ) : null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1">
        <MessageList
          conversationId={conversationId}
          messages={viewModels}
          trailingPanel={trailingPanel}
          onRegenerate={handleRegenerate}
          regenerateDisabled={isBusy}
        />
      </div>
      <Composer phase={state.pendingTurn?.phase ?? "idle"} onSend={handleSend} onStop={stop} />
    </div>
  );
}

// Step 12 Frontend Slice 5: assembles the final render order. Canonical
// messages are grouped by parent (orderCanonicalMessages), then, if a
// regenerate is in flight, the OLD canonical reply for that parent is
// suppressed and the pending regenerate bubble is spliced in right after
// that parent user message instead -- including the defensive case where
// that parent has no canonical reply at all yet (append after the parent
// regardless, per review point 3). A "send" pending turn is unaffected by
// any of this and is simply appended at the end, exactly Slice 4's
// behavior.
function buildViewModels(
  canonicalMessages: ChatMessageSummary[],
  pending: PendingTurn | null,
  activityByMessageId: ActivityByMessageId,
): MessageViewModel[] {
  const ordered = orderCanonicalMessages(canonicalMessages);
  const regenerateTargetId = pending?.kind === "regenerate" ? pending.parentUserMessageId : null;

  const result: MessageViewModel[] = [];
  let regenerateInserted = false;

  for (const m of ordered) {
    if (m.role === "assistant" && regenerateTargetId !== null && m.parent_user_message_id === regenerateTargetId) {
      continue; // suppressed: superseded by the pending regenerate bubble inserted below
    }
    result.push(canonicalToViewModel(m, activityByMessageId[m.id]));
    if (m.role === "user" && m.id === regenerateTargetId && !regenerateInserted) {
      result.push(...pendingTurnToViewModels(pending!));
      regenerateInserted = true;
    }
  }

  if (pending?.kind === "send") {
    result.push(...pendingTurnToViewModels(pending));
  } else if (pending?.kind === "regenerate" && !regenerateInserted) {
    console.warn(
      `regenerate pending turn's parent user message ${pending.parentUserMessageId} was not found in canonical history; appending at end`,
    );
    result.push(...pendingTurnToViewModels(pending));
  }

  return result;
}

function TrailingPanel({
  pending,
  onRefresh,
  onDismiss,
}: {
  pending: PendingTurn;
  onRefresh: () => void;
  onDismiss: () => void;
}) {
  if (pending.phase === "failed-before-stream" && pending.preStreamError) {
    const { kind, message } = pending.preStreamError;

    if (kind === "validation") {
      return (
        <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-600 dark:text-red-400">
          {message}（請修改內容後再次送出）
        </div>
      );
    }

    if (kind === "conversation-unavailable") {
      return (
        <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-600 dark:text-red-400">
          <p>這個對話已無法使用（可能已被刪除或封存）。</p>
          <Link href="/assistant" className="mt-1 inline-block underline">
            返回 AI Assistant
          </Link>
        </div>
      );
    }

    if (kind === "already-in-progress") {
      return (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-sm text-foreground/70">
          <p>{message}已有其他回覆正在生成中，請稍後重新整理查看結果。</p>
          <button
            type="button"
            onClick={onRefresh}
            className="mt-2 rounded-md border border-black/10 px-2 py-1 text-xs hover:bg-foreground/5 dark:border-white/10"
          >
            重新整理
          </button>
        </div>
      );
    }

    return (
      <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-sm text-foreground/70">
        <p>{message}訊息傳送狀態不明，請確認上方對話紀錄後再決定是否重新輸入。</p>
        <div className="mt-2 flex gap-2">
          <button
            type="button"
            onClick={onRefresh}
            className="rounded-md border border-black/10 px-2 py-1 text-xs hover:bg-foreground/5 dark:border-white/10"
          >
            重新整理
          </button>
          <button
            type="button"
            onClick={onDismiss}
            className="rounded-md border border-black/10 px-2 py-1 text-xs hover:bg-foreground/5 dark:border-white/10"
          >
            取消顯示
          </button>
        </div>
      </div>
    );
  }

  if (TERMINAL_RECONCILE_PHASES.has(pending.phase)) {
    return (
      <div className="flex items-center gap-2 text-xs text-foreground/50">
        <span>{pending.phase === "aborted" ? "已停止，正在確認最終狀態…" : "正在確認最終狀態…"}</span>
        <button type="button" onClick={onRefresh} className="underline hover:text-foreground">
          重新整理
        </button>
      </div>
    );
  }

  return null;
}
