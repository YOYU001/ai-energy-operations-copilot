# Step 12 Frontend — `/assistant` Chat UI: Architecture Investigation and Plan

> Planning document only. No frontend or backend code has been written yet.
> Backend is fully shipped (Sub-step 1–3C, `feature/step12-streaming-api`,
> 500 tests passing) — this plan wires a ChatGPT-style client onto that
> already-approved SSE/CRUD contract, per `.claude/rules/frontend/react.md`'s
> product positioning for `/assistant`.

## 0. What already exists (read directly from the repo, not assumed)

- `frontend/app/(dashboard)/assistant/page.tsx` is a bare placeholder — no
  logic, no state.
- `frontend/app/(dashboard)/layout.tsx` wraps every dashboard page
  (including `/assistant`) in `AppShell` with the global `Sidebar`/`TopNav`
  already wired — the new page inherits this automatically.
- `frontend/lib/api/client.ts` is `import "server-only"` — every existing
  function in it can only run in a Server Component/Route Handler/Server
  Action, never in a `"use client"` component. Its `apiFetch` wrapper
  hardcodes `res.json()` and a 5s `AbortSignal.timeout` — both wrong for a
  long-lived SSE response, so it is not reused for the streaming calls
  (only its JSON-call pattern is followed for the non-streaming
  conversation CRUD calls, see section 2).
- `frontend/lib/api/types.ts` has zero chat/conversation types yet — all
  need to be added.
- `frontend/components/ui/` has exactly 4 primitives (`EmptyState`,
  `IconButton`, `ConfidenceBadge`, `StatusBadge`) — no button, card,
  textarea, message bubble, or skeleton component exists. This page is
  ~100% new UI.
- No SSE/streaming library, no global state library (Context/Zustand/
  Redux), and no frontend test framework (no Jest/Vitest/Playwright) exist
  anywhere in `package.json` — confirmed via direct inspection, not
  assumed.
- `PageShell` is a `max-w-5xl mx-auto` centered column with a fixed
  title/description header — wrong shape for a full-height chat interface
  and not reused for this page (section 4).
- Dark mode is `data-theme` attribute-driven (`@custom-variant dark` in
  `globals.css`), not Tailwind's class strategy — every new component
  follows the existing `border-black/10 dark:border-white/10` pairing
  convention already used throughout `components/layout/` and the
  `cases`/`documents` pages.

## 1. Decision (confirmed): Next.js Route Handlers as SSE proxy

Browser never calls FastAPI directly. `API_BASE_URL` stays server-only,
exactly like every existing `lib/api/client.ts` call. New Route Handlers
under `frontend/app/api/assistant/` proxy every conversation/message
operation; the two streaming ones passthrough the backend's
`ReadableStream` body untouched — no re-framing of SSE events in the
proxy layer.

### 1.1 Route Handler path design

| Route Handler | Proxies | Streaming? |
|---|---|---|
| `app/api/assistant/conversations/route.ts` (`GET`, `POST`) | `GET/POST /conversations` | No (JSON) |
| `app/api/assistant/conversations/[id]/route.ts` (`GET`, `PATCH`, `DELETE`) | `GET/PATCH/DELETE /conversations/{id}` | No (JSON) |
| `app/api/assistant/conversations/[id]/messages/route.ts` (`GET`, `POST`) | `GET /conversations/{id}/messages` (JSON), `POST /conversations/{id}/messages` (SSE) | `GET` no, `POST` yes |
| `app/api/assistant/conversations/[id]/messages/[messageId]/regenerate/route.ts` (`POST`) | `POST /conversations/{id}/messages/{message_id}/regenerate` | Yes |

Path segments mirror the backend's own routes 1:1 (just prefixed with
`/api/assistant`) — no renaming, so the mapping stays obvious.

### 1.2 SSE passthrough and abort propagation

```ts
// app/api/assistant/conversations/[id]/messages/route.ts
import "server-only";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await request.text(); // raw JSON passthrough, no re-parsing needed

  const backendRes = await fetch(`${API_BASE_URL}/conversations/${id}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    signal: request.signal, // client abort -> this fetch aborts -> backend sees disconnect
  });

  if (!backendRes.ok) {
    // 400/404/409 established BEFORE any stream starts -- plain JSON
    // error passthrough, no SSE framing involved at all.
    return new Response(await backendRes.text(), {
      status: backendRes.status,
      headers: { "Content-Type": backendRes.headers.get("content-type") ?? "application/json" },
    });
  }

  // Stream established -- passthrough the body untouched. Any failure
  // from this point on is communicated via a message_failed SSE event
  // inside the stream itself, never a changed HTTP status (matches the
  // backend contract exactly: "once StreamingResponse is returned, every
  // subsequent outcome is a data-plane event, not a status-code change").
  return new Response(backendRes.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
```

- **Abort chain**: browser aborts its `fetch()` (e.g. tab closed, "Stop
  generating" button, section 7) → the `AbortSignal` passed to that fetch
  fires → Next.js's `request.signal` for the Route Handler fires → the
  outbound `fetch(...,{signal: request.signal})` to FastAPI aborts → the
  TCP connection to FastAPI closes → FastAPI's own
  `await request.is_disconnected()` check (already implemented, Sub-step
  3A) observes it and finalizes the message as `aborted`. No new backend
  work needed — this is exactly the disconnect path already built and
  tested.
- **The regenerate Route Handler is structurally identical**, just with
  no request body (`POST` with empty body) and the `/regenerate` path
  segment.
- **Non-streaming Route Handlers** (`conversations`, `conversations/[id]`,
  `messages` `GET`) are plain JSON passthrough — same shape as
  `lib/api/client.ts`'s existing `apiFetch`, and in fact these reuse new
  functions added to that same file (section 2), since they have no
  streaming concern at all.

### 1.3 Client-side SSE parser

Hand-rolled, no package added (per your decision). Backend's
`_sse_frame` always emits single-line `data:` (plain `json.dumps`, no
embedded newlines), so the parser only needs to split on the blank-line
frame boundary and read the first `event:`/`data:` line pair per frame:

```ts
// frontend/lib/assistant/sse.ts
export type AssistantSSEEvent =
  | { event: "message_started"; data: { message_id: number; attempt_number: number } }
  | { event: "token"; data: { delta: string } }
  | { event: "tool_call"; data: { tool_name: string; arguments: Record<string, unknown> } }
  | { event: "tool_result"; data: { tool_name: string; summary: string } }
  | { event: "message_completed"; data: { message_id: number; finish_reason: string | null; usage: unknown } }
  | { event: "message_failed"; data: { message_id: number; error: string } };

export async function* parseAssistantSSEStream(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<AssistantSSEEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const eventLine = frame.split("\n").find((l) => l.startsWith("event: "));
      const dataLine = frame.split("\n").find((l) => l.startsWith("data: "));
      if (eventLine && dataLine) {
        yield {
          event: eventLine.slice("event: ".length),
          data: JSON.parse(dataLine.slice("data: ".length)),
        } as AssistantSSEEvent;
      }
    }
  }
}
```

Caller (in `AssistantApp`, section 6) does:

```ts
const controller = new AbortController();
const res = await fetch(`/api/assistant/conversations/${conversationId}/messages`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ content }),
  signal: controller.signal,
});
if (!res.ok) { /* JSON error body -- 400/404 before any stream, show inline error */ }
for await (const evt of parseAssistantSSEStream(res.body!)) {
  dispatch({ type: evt.event, payload: evt.data }); // reducer, section 6
}
```

## 2. `lib/api/client.ts` / `types.ts` additions (non-streaming only)

New functions in `client.ts` (same `apiFetch` + type-guard convention as
every existing function — `getConversations`, `createConversation`,
`getConversation`, `updateConversation`, `archiveConversation`,
`getConversationMessages`), called **from the new Route Handlers**, not
from client components (the `server-only` boundary is respected exactly
as today). New types in `types.ts`: `ConversationSummary`,
`ConversationsPage`, `ChatMessageSummary`, `ConversationDetail` — mirroring
`backend/app/schemas.py`'s Pydantic models field-for-field.

## 3. Conversation list / create / archive / select flow

- **Initial load**: `assistant/page.tsx` (Server Component) calls
  `getConversations()` directly (existing convention, e.g. matching
  `cases/page.tsx`) and passes the result as an initial prop into the
  client `AssistantApp` tree — first paint has real data, no client-side
  loading flash for the list.
- **Create**: "New chat" button in `ConversationSidebar` calls
  `POST /api/assistant/conversations` (client fetch, JSON, not SSE),
  optimistically prepends the new conversation to the list and selects it.
- **Archive**: a per-conversation "..." menu action calls
  `DELETE /api/assistant/conversations/{id}`; on success, removes it from
  the visible list (archived conversations are already excluded by
  `list_conversations`) and, if it was the selected one, deselects (shows
  the empty/no-selection pane, section 9).
- **Select**: clicking a conversation in the sidebar sets
  `selectedConversationId` client-side and triggers a message-history
  fetch (section 4) — no full page navigation/reload, matching ChatGPT's
  instant-switch UX. (No `/assistant/[conversationId]` dynamic route in
  this design — see open item in section 13 if URL-addressable
  conversations are wanted later.)

## 4. Message history loading

On conversation selection (or initial deep-link, if added later),
`AssistantApp` calls `GET /api/assistant/conversations/{id}/messages`
(client fetch, JSON) and replaces its message-list state wholesale. This
is a full reload, not an incremental diff — simplest correct behavior for
MVP, and it's also the client's only recovery path after a dropped SSE
connection (per the backend contract: no resumable stream, `GET` is how a
client re-syncs to whatever the DB's terminal state actually is).

## 5. Composer and send flow

`Composer` is a `"use client"` leaf: a `<textarea>` (auto-growing height,
Enter-to-send/Shift+Enter-for-newline, matching ChatGPT convention) +
send button. On submit: `AssistantApp` immediately appends a local
optimistic user-message bubble (`status: "sending"`, not yet DB-confirmed)
and a placeholder assistant bubble, then starts the SSE POST (section 1.3).
Composer is disabled (send button replaced by a "Stop" button, section 7)
while a stream is in flight for the selected conversation.

## 6. SSE event handling and streaming UI

`AssistantApp` owns a `useReducer` over the current conversation's message
list (component/state ownership detailed in section 9). Reducer actions
map 1:1 to the 6 SSE event types:

| Event | Reducer action |
|---|---|
| `message_started` | Replace the placeholder assistant bubble's id with the real `message_id`; mark `status: "streaming"`. |
| `token` | Append `delta` to that message's `content`. |
| `tool_call` | Push `{tool_name, arguments}` into that message's `toolActivity` list, rendered as a transient "查詢中: {tool_name}" line (section 8). |
| `tool_result` | Update the matching `toolActivity` entry with `summary`, rendered as "已完成: {summary}". |
| `message_completed` | `status: "completed"`, clear any lingering "streaming" indicator. |
| `message_failed` | `status: "failed"`, store `error` for display + regenerate action (section 10). |

Token-by-token streaming re-renders only the one bubble whose content is
growing (React state update per `token` event) — no virtualization needed
at MVP message-count scale.

## 7. "Stop generating" (new, ChatGPT-parity UX enabled by the abort chain)

The `AbortController` created for the SSE `fetch` (section 1.3) is kept in
`AssistantApp` state while streaming. The Composer's send button becomes a
"Stop" button during streaming; clicking it calls `controller.abort()`,
which propagates through the full chain in section 1.2 and results in the
backend marking the message `aborted` — the UI then shows that bubble as
aborted with a regenerate action, exactly like a network-drop disconnect
would.

## 8. `tool_call` / `tool_result` display

Rendered inline, above the assistant bubble's growing text, as a small
muted line (`text-foreground/60`, matching the existing meta-text
convention) that updates in place: "查詢中: {tool_name}" →
"已完成: {summary}" per tool call, in order. Multiple tool calls in one
round stack as multiple lines. This is deliberately not a collapsible/
technical panel for MVP — just enough to show "the assistant is checking
internal data," matching the backend's own "short, non-sensitive summary"
contract (never the raw tool result JSON, which the frontend never even
receives).

## 9. Full-height layout — bypassing `PageShell`

`assistant/page.tsx` does **not** use `PageShell` (its `max-w-5xl
mx-auto` + fixed header shape is wrong here). Instead:

```tsx
// assistant/page.tsx (Server Component)
export const dynamic = "force-dynamic";
export default async function AssistantPage() {
  const conversations = await getConversations();
  return <AssistantApp initialConversations={conversations} />;
}
```

```tsx
// AssistantApp.tsx ("use client")
<div className="flex h-full min-h-0">
  <ConversationSidebar ... />
  <div className="flex min-h-0 flex-1 flex-col">
    <MessageList className="flex-1 overflow-y-auto" ... />
    <Composer className="shrink-0 border-t border-black/10 dark:border-white/10" ... />
  </div>
</div>
```

`AppShell`'s `<main className="flex-1 overflow-y-auto">` already gives
this page a bounded height (it's a flex child in a `h-screen`-rooted
column — **to confirm exactly at implementation time**, not assumed: read
`AppShell.tsx`'s outer wrapper class to verify it sets an explicit height
root, since `flex-1` only resolves to a bounded height if an ancestor
does). The chat root here uses `h-full min-h-0` so it fills that bounded
box without adding its own scroll; only `MessageList` scrolls internally
(`flex-1 overflow-y-auto`), and `Composer` stays pinned via `shrink-0`.
This avoids the double-scrollbar problem of nesting one `overflow-y-auto`
inside another.

## 10. Regenerate UI and state handling

A "regenerate" icon action appears on hover for any assistant bubble
(matching ChatGPT), and automatically/prominently for one that ended
`failed` or `aborted`. Clicking it calls
`POST /api/assistant/conversations/{id}/messages/{parentUserMessageId}/regenerate`
(same SSE handling as section 6, targeting the **same bubble position** —
the reducer replaces that message's content/status in place, it does not
append a new bubble, since the backend's active-attempt model means the
old attempt is no longer returned by `GET .../messages` at all once
superseded).

**Explicit MVP limitation, stated plainly**: there is no attempt-history
switcher (ChatGPT's "‹ 1/2 ›" arrows) — the backend only exposes the
currently-active attempt via `GET .../messages`, with no endpoint listing
all past attempts for a parent. Regenerating replaces what's shown; the
previous attempt's text is gone from the UI (though still in the DB,
`is_active=false`, unreachable from any current endpoint). If browsing
past attempts is wanted later, that's new backend scope, not a frontend
gap to work around.

`409` (already an active streaming attempt for this parent) is handled by
disabling the regenerate action while `status === "streaming"` for that
message — the UI's own state already knows this, so the 409 case should
rarely be user-reachable; if it does occur (e.g. a stale UI state), show
a small inline "already generating" message rather than a raw error.

## 11. Loading / empty / error / disconnect / retry UX

| State | Treatment |
|---|---|
| Conversation list loading | Server-rendered on first load (no flash); a lightweight skeleton (new, simple pulsing bars — no existing skeleton component) for subsequent client refetches. |
| No conversations yet | `EmptyState` (existing component) inside the sidebar area: "尚無對話，開始新的對話". |
| No conversation selected | Centered placeholder pane in the main chat column inviting selection/creation — not `EmptyState` verbatim (that's sidebar-shaped), a dedicated simple centered message. |
| Message history loading (switching conversations) | Brief inline loading text in the message pane (matching existing plain-text loading convention, e.g. `cases`' `loading.tsx` style, not a spinner component that doesn't exist yet). |
| Send request rejected before streaming (400/404/409 JSON) | Inline error banner above the composer; composer stays editable, user can fix and resend. |
| Disconnect mid-stream (network drop, not user-initiated stop) | Bubble shows `aborted` styling + regenerate action, exactly like `message_failed`, once the `fetch`/stream itself errors client-side (caught around the `for await` loop) — no waiting for a background reconciliation to notice. |
| Regenerate retry | Same as original send — no special-cased retry mechanism; regenerate **is** the retry action (section 10). |

## 12. Responsive strategy (desktop vs. narrow)

- **Desktop (≥ `md`, matching the existing breakpoint convention already
  used by `AppShell`)**: three columns — global nav `Sidebar` (existing,
  already collapsible) + `ConversationSidebar` (new, fixed `w-64`, always
  visible) + chat column (`flex-1`).
- **Narrow (< `md`)**: the existing global nav drawer (hamburger, already
  wired in `AppShell`) is unchanged. `ConversationSidebar` gets its
  **own, separate** toggle — a small icon button in the chat column's own
  header (not the global `TopNav`) that opens the conversation list as an
  overlay drawer, using the same `fixed inset-0`/backdrop pattern
  `AppShell` already established for its own mobile drawer (visually
  consistent, but a **separate piece of state**, not shared with the
  global nav drawer — two independent collapsible panels is an explicit,
  deliberate consequence of this app having both a global dashboard nav
  *and* a ChatGPT-style conversation list, unlike ChatGPT itself which
  only has the latter). Flagged as an open UX question in section 13 —
  worth a quick look at an actual narrow-viewport render before finalizing,
  not just reasoned about in the abstract.

## 13. Component boundary and state ownership

```
assistant/page.tsx (Server Component: initial getConversations() fetch)
 └─ AssistantApp.tsx ("use client", owns ALL state below)
     ├─ ConversationSidebar.tsx (props: conversations, selectedId, callbacks)
     ├─ MessageList.tsx (props: messages, scroll-to-bottom-while-streaming behavior)
     │   └─ MessageBubble.tsx (props: one message; renders role styling,
     │       toolActivity lines, regenerate action)
     └─ Composer.tsx (props: value, onSend, onStop, isStreaming)
```

**State lives in `AssistantApp` via `useReducer`** (not Context, not a
global store) — the tree above is only 3 levels deep, shallow enough for
plain prop passing, consistent with this codebase's existing "no global
state library" convention (confirmed nowhere in the repo today). State
shape:

```ts
type ChatMessageState = {
  id: number;
  role: "user" | "assistant";
  content: string;
  status: "sending" | "streaming" | "completed" | "failed" | "aborted";
  toolActivity?: { tool_name: string; summary?: string }[];
  errorMessage?: string;
};

type AssistantAppState = {
  conversations: ConversationSummary[];
  selectedConversationId: number | null;
  messages: ChatMessageState[];
  isStreaming: boolean;
  activeAbortController: AbortController | null;
  historyLoadError: string | null;
};
```

## 14. Test strategy

**No frontend test framework exists in this repo today** (confirmed:
zero Jest/Vitest/Playwright in `package.json`). Consistent with the
project's established pattern (manual browser verification + `npm run
lint`/`npm run build`/`tsc` for every prior frontend Step, per
`docs/DEVELOPMENT_WORKFLOW.md`'s "for UI changes, start dev server and
test in browser" rule), this plan does **not** propose introducing a new
test framework as part of this slice — that would be a separate,
explicitly-approved decision (flagged in section 15), not bundled in
silently. Verification for this slice:

- `npm run lint`, `npm run build`, `tsc --noEmit` must all pass.
- Manual browser verification covering: send a plain conversational
  message (Phase 2 synthesis path), send a diagnostic message that
  triggers a tool call (visible `tool_call`/`tool_result` lines), trigger
  the capability-guard "insufficient data" fallback, regenerate a
  completed answer, regenerate a failed answer, click "Stop generating"
  mid-stream, switch between two conversations, create a new conversation,
  archive a conversation, narrow-viewport (~375px) render of both the
  global nav drawer and the new conversation-list drawer, dark mode toggle
  while a stream is in progress.
- The two new Route Handlers that proxy non-streaming calls can be smoke-
  tested with `curl`/a manual browser network-tab check against the real
  dev backend (matching how backend Route Handler-style proxies have been
  spot-checked elsewhere in this project) — no automated test added.

## 15. Open UX/architecture items for your confirmation

1. **Two independent mobile drawers** (global nav + conversation list,
   section 12) is a real, slightly unusual UX consequence of this app's
   shape vs. ChatGPT's — worth a quick look at an actual narrow render
   before implementation locks it in, not just this document's reasoning.
2. **No `/assistant/[conversationId]` URL** — conversation selection is
   pure client state, not reflected in the URL, so refreshing the page or
   sharing a link always lands on "no conversation selected." If
   deep-linkable/bookmarkable conversations are wanted, that's a small
   but real scope addition (a dynamic route + reading the id from the URL
   instead of/alongside client state) — flagged, not assumed either way.
3. **Optimistic user-message bubble before the backend confirms
   `insert_user_message`**: if the SSE POST itself fails immediately
   (e.g. network error before any response), the optimistic bubble needs
   a clear "failed to send" treatment distinct from an assistant-side
   `message_failed` — this plan assumes that's a small addition to the
   same reducer, not a new architecture, but worth confirming it's in
   scope for this same implementation slice rather than deferred.
4. **Skeleton/loading visual polish** — this plan proposes a minimal new
   pulsing-skeleton primitive for conversation-list refetches, the first
   skeleton component in this codebase; confirm that's acceptable scope
   (vs. reusing the existing plain-text "載入中" convention everywhere,
   which would be even simpler but less polished for a ChatGPT-style page).

## Explicitly out of scope for this planning document

Any actual file changes, package installs, backend changes, attempt-history
browsing UI (section 10), URL-addressable conversations (section 15.2)
unless confirmed, a new frontend test framework (section 14) unless
confirmed, `AGENTS.md`, `worktrees/`, `runpane`.
