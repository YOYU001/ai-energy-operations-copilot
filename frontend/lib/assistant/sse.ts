// Step 12 Frontend Slice 1: client-side SSE parser for the assistant
// message/regenerate streams. Hand-rolled on purpose (no package added,
// per decision) -- native fetch + ReadableStream + TextDecoder only.
//
// This does not assume events arrive one-per-network-chunk: a chunk can
// contain zero, one, or many complete frames, and a single frame can be
// split across multiple chunks (including mid-line). Frames are
// delimited by a blank line ("\n\n") per the SSE spec, exactly matching
// backend app/main.py's `_sse_frame` (`f"event: {event}\ndata: {json.dumps(data)}\n\n"`).
//
// Per the SSE spec (and to stay forward-compatible, not just handle this
// backend's current single-line json.dumps output), a frame's `data:`
// lines are joined with "\n" if there happen to be more than one --
// this backend never emits that today, but the parser does not assume it
// never will.

export type AssistantSSEEvent =
  | { event: "message_started"; data: { message_id: number; attempt_number: number } }
  | { event: "token"; data: { delta: string } }
  | { event: "tool_call"; data: { tool_name: string; arguments: Record<string, unknown> } }
  | { event: "tool_result"; data: { tool_name: string; summary: string } }
  | {
      event: "message_completed";
      data: { message_id: number; finish_reason: string | null; usage: unknown };
    }
  | { event: "message_failed"; data: { message_id: number; error: string } };

const KNOWN_EVENT_TYPES = new Set<AssistantSSEEvent["event"]>([
  "message_started",
  "token",
  "tool_call",
  "tool_result",
  "message_completed",
  "message_failed",
]);

function isKnownEventType(value: string): value is AssistantSSEEvent["event"] {
  return KNOWN_EVENT_TYPES.has(value as AssistantSSEEvent["event"]);
}

/** Parses one already-split SSE frame (no trailing blank line) into an
 * event, or null if the frame is malformed / unrecognized -- callers skip
 * null rather than treating it as fatal, so one bad frame never kills the
 * rest of the stream. */
function parseFrame(frame: string): AssistantSSEEvent | null {
  let eventName: string | null = null;
  const dataLines: string[] = [];

  for (const line of frame.split("\n")) {
    if (line.startsWith("event: ")) {
      eventName = line.slice("event: ".length);
    } else if (line.startsWith("data: ")) {
      dataLines.push(line.slice("data: ".length));
    }
    // any other line (e.g. a stray comment/blank) is ignored, not fatal
  }

  if (eventName === null || dataLines.length === 0) {
    return null;
  }
  if (!isKnownEventType(eventName)) {
    console.warn(`assistant SSE: ignoring unknown event type "${eventName}"`);
    return null;
  }

  let data: unknown;
  try {
    data = JSON.parse(dataLines.join("\n"));
  } catch (cause) {
    console.warn(`assistant SSE: failed to JSON-parse data for event "${eventName}"`, cause);
    return null;
  }

  return { event: eventName, data } as AssistantSSEEvent;
}

/**
 * Reads a streaming SSE response body and yields one AssistantSSEEvent per
 * complete frame, in order. Handles:
 *  - a frame split across multiple network chunks (buffers until a
 *    complete "\n\n"-terminated frame is available)
 *  - multiple complete frames delivered in a single chunk (drains all of
 *    them from the buffer before awaiting the next chunk)
 *  - a trailing partial frame left in the buffer when the stream ends
 *    without a final blank line (ignored -- an incomplete frame carries
 *    no reliable event, matching the "one bad/incomplete frame does not
 *    crash the stream" principle above)
 *  - abort: if `body`'s underlying fetch was aborted, `reader.read()`
 *    rejects (DOMException "AbortError"); this function does not catch
 *    it -- it propagates to the caller's own try/catch around the
 *    `for await` loop, so the caller decides how an aborted stream is
 *    reflected in UI state (see docs/step12_frontend_chat_ui_plan.md
 *    section 7, "Stop generating").
 */
export async function* parseAssistantSSEStream(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<AssistantSSEEvent, void, void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        return; // any trailing partial frame in `buffer` is deliberately dropped
      }
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const parsed = parseFrame(frame);
        if (parsed !== null) {
          yield parsed;
        }
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}
