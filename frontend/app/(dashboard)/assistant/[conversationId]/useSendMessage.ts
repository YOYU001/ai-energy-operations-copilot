import { useCallback, useRef } from "react";
import type { Dispatch } from "react";
import { parseAssistantSSEStream } from "@/lib/assistant/sse";
import type { Action } from "./ChatThread";

// Step 12 Frontend Slice 4: orchestrates one send -- POST, then read the
// SSE stream via the EXISTING parser in lib/assistant/sse.ts (not
// reimplemented here). This module only adds a defensive event-order
// guard and dispatches reducer actions; ChatThread owns all resulting
// state.

async function parseErrorDetail(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: string };
    return body.detail ?? `HTTP ${res.status}`;
  } catch {
    return `HTTP ${res.status}`;
  }
}

function isAbortError(cause: unknown): boolean {
  return cause instanceof DOMException && cause.name === "AbortError";
}

async function runSend(
  conversationId: number,
  content: string,
  signal: AbortSignal,
  dispatch: Dispatch<Action>,
  isCurrent: () => boolean,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`/api/assistant/conversations/${conversationId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
      signal,
    });
  } catch (cause) {
    if (!isCurrent()) return;
    if (isAbortError(cause)) {
      dispatch({ type: "ABORTED" });
      return;
    }
    dispatch({
      type: "FAILED_BEFORE_STREAM",
      preStreamError: {
        kind: "reconcile-required",
        message: `無法連線到伺服器（${(cause as Error).message}）。`,
      },
    });
    return;
  }

  if (!isCurrent()) return;

  if (!res.ok) {
    const detail = await parseErrorDetail(res);
    // Per backend/app/main.py's post_message: insert_user_message runs
    // before conn.commit(), and only content-blank (400) and
    // conversation-not-found/archived (404) are guaranteed to be raised
    // BEFORE that insert. Any other status means we can't rule out the
    // user message having already been committed server-side.
    if (res.status === 400) {
      dispatch({ type: "FAILED_BEFORE_STREAM", preStreamError: { kind: "validation", message: detail } });
    } else if (res.status === 404) {
      dispatch({
        type: "FAILED_BEFORE_STREAM",
        preStreamError: { kind: "conversation-unavailable", message: detail },
      });
    } else {
      dispatch({ type: "FAILED_BEFORE_STREAM", preStreamError: { kind: "reconcile-required", message: detail } });
    }
    return;
  }

  if (res.body === null) {
    dispatch({
      type: "FAILED_BEFORE_STREAM",
      preStreamError: { kind: "reconcile-required", message: "伺服器沒有回傳串流內容。" },
    });
    return;
  }

  let gotMessageStarted = false;
  let gotTerminal = false;

  try {
    for await (const evt of parseAssistantSSEStream(res.body)) {
      if (!isCurrent()) return;
      if (gotTerminal) {
        console.warn(`assistant SSE: ignoring "${evt.event}" received after a terminal event`);
        continue;
      }

      switch (evt.event) {
        case "message_started": {
          if (gotMessageStarted) {
            console.warn("assistant SSE: ignoring duplicate message_started");
            break;
          }
          gotMessageStarted = true;
          dispatch({
            type: "MESSAGE_STARTED",
            assistantMessageId: evt.data.message_id,
            attemptNumber: evt.data.attempt_number,
          });
          break;
        }
        case "token": {
          if (!gotMessageStarted) {
            console.warn("assistant SSE: ignoring token received before message_started");
            break;
          }
          dispatch({ type: "TOKEN_RECEIVED", delta: evt.data.delta });
          break;
        }
        case "tool_call":
        case "tool_result":
          // No tool activity UI this Slice -- consumed so the stream
          // keeps draining, deliberately no dispatch.
          break;
        case "message_completed": {
          gotTerminal = true;
          if (!gotMessageStarted) {
            console.warn(
              "assistant SSE: message_completed received before message_started -- treating as indeterminate",
            );
            dispatch({
              type: "FAILED_BEFORE_STREAM",
              preStreamError: { kind: "reconcile-required", message: "回覆狀態不明。" },
            });
            break;
          }
          dispatch({ type: "MESSAGE_COMPLETED", assistantMessageId: evt.data.message_id });
          break;
        }
        case "message_failed": {
          gotTerminal = true;
          if (!gotMessageStarted) {
            console.warn(
              "assistant SSE: message_failed received before message_started -- treating as indeterminate",
            );
            dispatch({
              type: "FAILED_BEFORE_STREAM",
              preStreamError: { kind: "reconcile-required", message: evt.data.error },
            });
            break;
          }
          dispatch({
            type: "STREAM_FAILED_DURING",
            assistantMessageId: evt.data.message_id,
            error: evt.data.error,
          });
          break;
        }
      }
    }
  } catch (cause) {
    if (!isCurrent()) return;
    if (isAbortError(cause)) {
      dispatch({ type: "ABORTED" });
      return;
    }
    if (gotMessageStarted) {
      dispatch({ type: "STREAM_FAILED_DURING", error: "連線中斷，狀態不明。" });
    } else {
      dispatch({
        type: "FAILED_BEFORE_STREAM",
        preStreamError: { kind: "reconcile-required", message: "連線中斷，訊息傳送狀態不明。" },
      });
    }
    return;
  }

  if (!isCurrent()) return;
  if (!gotTerminal) {
    // Stream closed cleanly but never sent a terminal event -- a
    // contract violation we defend against rather than assume away.
    console.warn("assistant SSE: stream ended without a terminal event");
    if (gotMessageStarted) {
      dispatch({ type: "STREAM_FAILED_DURING", error: "連線已結束但未收到完成事件，狀態不明。" });
    } else {
      dispatch({
        type: "FAILED_BEFORE_STREAM",
        preStreamError: { kind: "reconcile-required", message: "連線已結束但未收到任何回應，狀態不明。" },
      });
    }
  }
}

export function useSendMessage(conversationId: number, dispatch: Dispatch<Action>) {
  const abortControllerRef = useRef<AbortController | null>(null);
  const runIdRef = useRef(0);

  const send = useCallback(
    (content: string) => {
      const trimmed = content.trim();
      if (trimmed === "") return;

      runIdRef.current += 1;
      const myRunId = runIdRef.current;
      const clientId =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random()}`;
      const controller = new AbortController();
      abortControllerRef.current = controller;

      dispatch({ type: "SEND_REQUESTED", clientId, content: trimmed });

      void runSend(conversationId, trimmed, controller.signal, dispatch, () => runIdRef.current === myRunId);
    },
    [conversationId, dispatch],
  );

  const stop = useCallback(() => {
    dispatch({ type: "STOP_REQUESTED" });
    abortControllerRef.current?.abort();
  }, [dispatch]);

  // Invalidates any in-flight dispatches (runId guard) and aborts the
  // underlying fetch -- used on unmount/conversation switch, not on a
  // user-initiated Stop (that's `stop`, above).
  const cancelActive = useCallback(() => {
    runIdRef.current += 1;
    abortControllerRef.current?.abort();
  }, []);

  return { send, stop, cancelActive };
}
