"use client";

import Link from "next/link";
import { useEffect, useReducer, useRef } from "react";
import { useRouter } from "next/navigation";
import type { ChatMessageSummary } from "@/lib/api/types";
import Composer from "./Composer";
import MessageList from "./MessageList";
import { canonicalToViewModel, pendingTurnToViewModels } from "./messageViewModel";
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
  | { kind: "reconcile-required"; message: string };

export interface PendingTurn {
  clientId: string;
  phase: RequestPhase;
  userContent: string;
  assistantMessageId: number | null;
  attemptNumber: number | null;
  assistantContent: string;
  errorMessage: string | null;
  preStreamError: PreStreamError | null;
}

interface ChatThreadState {
  pendingTurn: PendingTurn | null;
}

export type Action =
  | { type: "SEND_REQUESTED"; clientId: string; content: string }
  | { type: "MESSAGE_STARTED"; assistantMessageId: number; attemptNumber: number }
  | { type: "TOKEN_RECEIVED"; delta: string }
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

const MAX_RECONCILE_RETRIES = 3;
const RECONCILE_RETRY_DELAY_MS = 2000;

function reducer(state: ChatThreadState, action: Action): ChatThreadState {
  const pending = state.pendingTurn;

  switch (action.type) {
    case "SEND_REQUESTED":
      return {
        pendingTurn: {
          clientId: action.clientId,
          phase: "connecting",
          userContent: action.content,
          assistantMessageId: null,
          attemptNumber: null,
          assistantContent: "",
          errorMessage: null,
          preStreamError: null,
        },
      };
    case "MESSAGE_STARTED":
      if (pending === null || pending.phase !== "connecting") return state;
      return {
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
      return { pendingTurn: { ...pending, assistantContent: pending.assistantContent + action.delta } };
    case "STOP_REQUESTED":
      if (pending === null || (pending.phase !== "connecting" && pending.phase !== "streaming")) {
        return state;
      }
      return { pendingTurn: { ...pending, phase: "stopping" } };
    case "ABORTED":
      if (pending === null) return state;
      return { pendingTurn: { ...pending, phase: "aborted" } };
    case "MESSAGE_COMPLETED":
      if (pending === null) return state;
      return {
        pendingTurn: {
          ...pending,
          phase: "completed",
          assistantMessageId: pending.assistantMessageId ?? action.assistantMessageId,
        },
      };
    case "STREAM_FAILED_DURING":
      if (pending === null) return state;
      return {
        pendingTurn: {
          ...pending,
          phase: "failed-during-stream",
          assistantMessageId: pending.assistantMessageId ?? action.assistantMessageId ?? null,
          errorMessage: action.error,
        },
      };
    case "FAILED_BEFORE_STREAM":
      if (pending === null) return state;
      return { pendingTurn: { ...pending, phase: "failed-before-stream", preStreamError: action.preStreamError } };
    case "RECONCILED":
    case "DISMISS_UNCERTAIN":
      return { pendingTurn: null };
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
  const [state, dispatch] = useReducer(reducer, { pendingTurn: null });
  const { send, stop, cancelActive } = useSendMessage(conversationId, dispatch);

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

  function handleManualRefresh() {
    router.refresh();
  }

  function handleDismissUncertain() {
    clearReconcileTimer();
    dispatch({ type: "DISMISS_UNCERTAIN" });
  }

  const viewModels = [
    ...canonicalMessages.map(canonicalToViewModel),
    ...(state.pendingTurn ? pendingTurnToViewModels(state.pendingTurn) : []),
  ];

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
        />
      </div>
      <Composer
        phase={state.pendingTurn?.phase ?? "idle"}
        onSend={handleSend}
        onStop={stop}
      />
    </div>
  );
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
