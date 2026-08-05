# Step 12 Sub-step 3A Slice 4 — Implementation Plan (Streaming Message Endpoint)

> Planning document only. No functional code, schema, or migration has been
> written yet. Resolves `POST /conversations/{conversation_id}/messages`
> (SSE) against the current, actually-shipped state of the repo (Slices 1–3
> merged: `chat_provider.py`, conversation CRUD, and
> `GET /conversations/{id}/messages` read model), not against the plan
> document in the abstract.

## 0. What's already shipped vs. what this slice adds

- **Already shipped** (`e051158`, `a4ebc75`, `987d76d`): `ChatProvider`/
  `ChatDeltaEvent`/`ChatFinishEvent`/`ChatProviderError` family
  (`backend/app/services/chat_provider.py`); conversation CRUD (`POST`/
  `GET /conversations`, `GET`/`PATCH`/`DELETE /conversations/{id}`); **and**
  `GET /conversations/{id}/messages` (Slice 3 — the read model). This slice
  does **not** touch any of that.
- **This slice adds**: `POST /conversations/{conversation_id}/messages`
  only — the one remaining endpoint from the original 3A scope, and the
  only one that actually calls `ChatProvider`.
- **One correction to the master plan's own sample code**: `docs/step12_substep3a_plan.md`
  §4's `post_message` sample calls `generate(..., request)` but never
  declares `request: Request` as a parameter of `post_message` itself —
  this is a plan-document typo, not a design decision, and is fixed in
  section 3 below (the endpoint signature explicitly takes
  `request: Request`, which FastAPI injects automatically for any route
  parameter typed `Request`).

## 1. Request / SSE response contract

`PostMessageRequest` (new, added to `backend/app/schemas.py` — the master
plan already specified this shape, not yet created because Slice 4 is the
first slice that needs it):

```python
class PostMessageRequest(BaseModel):
    content: str
```

No `role_mode` field (removed per the earlier plan-review fix — every
message uses the conversation's own stored `role_mode`).

```
POST /conversations/{conversation_id}/messages
Request body: {"content": "為什麼 12 號電池今天沒有依排程放電？"}

Response: 404 (application/json) if conversation missing or archived
          400 (application/json) if content is blank after .strip()
          200, Content-Type: text/event-stream, otherwise
```

The 404/400 checks happen entirely within Phase A (section 2), before any
`StreamingResponse` is constructed — so these two error cases are ordinary
JSON error responses via `HTTPException`, exactly like every other
endpoint in `main.py`, not SSE-framed errors. Once Phase A succeeds and
`StreamingResponse` is returned, every subsequent outcome (including
provider failure) is communicated only via SSE frames (section 4) plus the
DB row — never an HTTP error status after that point (the HTTP status for
a successful stream start is always `200`, per SSE convention; failure
mid-stream is a data-plane event, not a status-code change).

## 2. Phase A / B / C transaction boundaries

Directly inherits `docs/step12_substep3_plan.md` §6 and §7 (already
approved) and `docs/step12_substep3a_plan.md` §3/§4. Restated precisely
against the real function signatures currently in the repo:

- **Phase A** — one `with get_connection() as conn:` block, opened and
  fully closed before the SSE generator is even constructed (not relying
  on `Depends` cleanup timing — this was corrected in the overall plan
  review and still applies):
  1. `get_conversation_with_active_messages(conn, conversation_id)` → 404
     if `None` or `conversation["archived_at"] is not None`.
  2. Capture `role_mode = conversation["role_mode"]` and
     `prior_messages = detail["messages"]` (the list **before** this
     request's own user message is inserted — this is what avoids
     duplicating the new message when Phase B builds the provider's
     message list in section 5).
  3. `provider = _build_chat_provider()` (new factory seam, mirrors
     `_build_embedding_provider()`) — resolved **before** the placeholder
     insert specifically so its real `provider_name`/`model_name` can be
     recorded at creation time (this is the resolution of the master
     plan's open item 7: no change to `finalize_assistant_message`'s
     signature; `create_streaming_assistant_placeholder` gets the real
     values immediately).
  4. `user_message_id = insert_user_message(conn, conversation_id, content)`.
  5. `assistant_message_id = create_streaming_assistant_placeholder(conn, conversation_id, user_message_id, attempt_number=1, provider=provider.provider_name, model=provider.model_name)`.
  6. `conn.commit()`.
  The `with` block's exit here is what actually closes the connection —
  verified structurally (the block exits before `StreamingResponse` is
  constructed), and further verified at runtime by
  `test_conversations_streaming_integration.py` (section 7).
- **Phase B** — inside the SSE generator (`async def generate(...)`), no DB
  connection held anywhere in this phase: calls `provider.stream_chat(messages, tools=None)`
  and consumes it under the 15s idle / 60s overall timeouts (section 4),
  yielding `token` SSE frames as content arrives. 3A never opens a tool-call
  connection here (no tool-calling in 3A at all).
- **Phase C** — inside the same generator, after Phase B's loop ends (by
  any of: normal completion, timeout, provider error, or disconnect): calls
  `_finalize_with_fallback(...)` (section 6), which opens its own fresh
  `with get_connection() as conn:` block(s), independent of Phase A's
  already-closed connection.

## 3. User message vs. assistant placeholder creation order

Fixed order, both inside Phase A, both on the same `conn`, both before the
single Phase A commit — **user message always first**:

1. `insert_user_message` — this is what actually persists what the user
   typed, and (per its existing implementation) also backend-generates the
   conversation's title from this content if one doesn't exist yet, in the
   same transaction.
2. `create_streaming_assistant_placeholder` — takes `insert_user_message`'s
   returned `user_message_id` as its `parent_user_message_id`, so the
   placeholder row is only ever created once its parent already exists
   within the same uncommitted transaction (matching the FK relationship
   `chat_messages.parent_user_message_id → chat_messages.id`; both rows
   commit atomically together, so there is never a moment where a
   committed placeholder references a not-yet-committed parent).

`attempt_number=1` is hardcoded here (not computed) because this is
always the *first* attempt for a brand-new user message — Sub-step 1's own
documented carve-out (`docs/step12_substep1_plan.md` §2, "the first attempt
... does *not* take the lock") applies exactly here; `create_regenerate_attempt`
(a different, not-yet-wired endpoint — 3C scope) is the only path that
computes a non-1 `attempt_number` under a lock.

## 4. Streaming event types and payloads (3A subset)

Exactly the 4 event types the overall plan reserves for 3A (`tool_call`/
`tool_result` remain 3B-only and are never emitted here):

| `event` | `data` | Emitted when |
|---|---|---|
| `message_started` | `{"message_id": <assistant_message_id>, "attempt_number": 1}` | First frame, immediately after Phase A's connection closes, before Phase B's provider call starts. |
| `token` | `{"delta": <str>}` | Once per `ChatDeltaEvent` yielded by `ChatProvider.stream_chat`. |
| `message_completed` | `{"message_id": <id>, "finish_reason": <str>, "usage": {...} \| null}` | Terminal success — only if the client is still connected at the end of Phase C (best-effort; see section 5). |
| `message_failed` | `{"message_id": <id>, "error": <public-safe string>}` | Terminal failure/abort — same best-effort connectivity caveat. |

SSE framing (new helper, `backend/app/main.py`):

```python
def _sse_frame(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
```

`ChatProvider` itself (per prior review feedback, already honored in the
existing `chat_provider.py`) never knows about SSE — it only ever yields
`ChatDeltaEvent`/`ChatFinishEvent`. All `event:`/`data:` framing and event
naming happens exclusively in this slice's `main.py` generator, preserving
the layering: `AsyncOpenAI → ChatProvider → (typed events) → Streaming API → SSE`.

## 5. Terminal-state behavior: completion, provider error, disconnect

One generator function, one finalize call site (per `docs/step12_substep3_plan.md`
§7's requirement that 3A ship the minimum-safety lifecycle in full, not
defer any of it to 3C):

```python
async def generate(conversation_id, message_id, prior_messages, user_content, role_mode, request):
    provider = _build_chat_provider()
    yield _sse_frame("message_started", {"message_id": message_id, "attempt_number": 1})

    accumulated = ""
    status, error_message, finish_reason, usage = "completed", None, None, None
    start = time.monotonic()
    try:
        messages = _build_provider_messages(prior_messages, user_content, role_mode)
        stream = provider.stream_chat(messages, tools=None)
        while True:
            if await request.is_disconnected():
                status, error_message = "aborted", None
                break
            try:
                event = await asyncio.wait_for(stream.__anext__(), timeout=15)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                raise ChatProviderTimeout("idle timeout waiting for next token")
            if time.monotonic() - start > 60:
                raise ChatProviderTimeout("overall generation timeout")
            if isinstance(event, ChatDeltaEvent):
                accumulated += event.delta
                yield _sse_frame("token", {"delta": event.delta})
            elif isinstance(event, ChatFinishEvent):
                finish_reason, usage = event.finish_reason, event.usage
    except ChatProviderTimeout:
        status, error_message = "failed", "provider_timeout"
    except ChatProviderError:
        status, error_message = "failed", "provider_error"
    except Exception:
        log.exception("unexpected error in chat generation for message %s", message_id)
        status, error_message = "failed", "provider_error"

    finalized = _finalize_with_fallback(message_id, accumulated, status, error_message, finish_reason, usage)
    if not await request.is_disconnected():
        if status == "completed":
            yield _sse_frame("message_completed", {"message_id": message_id, "finish_reason": finish_reason, "usage": usage})
        else:
            yield _sse_frame("message_failed", {"message_id": message_id, "error": _public_error_message(error_message)})
    if not finalized:
        log.error("message %s left in a non-terminal DB state after two finalize attempts", message_id)
```

- **Normal completion**: `StopAsyncIteration` ends the loop with
  `status` still `"completed"` (its initial value) — this is why
  `status`/`error_message`/`finish_reason`/`usage` are all initialized
  *before* the try block, not inside a success branch: the "happy path" is
  simply "nothing raised, nothing set it to failed/aborted."
- **Provider error / idle timeout / overall timeout**: all funnel to
  `status="failed"` with a **sanitized DB code**
  (`error_message="provider_timeout"` or `"provider_error"` — never the
  raw exception). The raw exception is logged via `log.exception(...)`
  only in the catch-all branch here; `ChatProviderTimeout`/`ChatProviderAPIError`
  don't re-log because their `__cause__` was already set by
  `chat_provider.py` at raise time and this generator doesn't need to
  duplicate that — **decision for this slice**: add one `log.exception`
  call in the two named `except` branches too (not just the catch-all),
  so every failed path has a server-log trail, not just the unexpected
  one. This is a small addition to the sample above the master plan didn't
  spell out; implementation will add `log.exception(...)` to all three
  `except` branches, not only the last.
- **Client disconnect**: detected via `request.is_disconnected()`,
  `status="aborted"`, `error_message=None` (not a failure — a `finish_reason`/`usage`
  simply stay `None` since the provider was cut off, not concluded).
  `accumulated` (whatever partial content arrived before disconnect) is
  still persisted — an aborted message is not discarded, per
  `docs/step12_substep3_plan.md` §7.
- **`_public_error_message` mapping** (new, `main.py`): a small fixed dict,
  e.g. `{"provider_timeout": "assistant response failed, please try again", "provider_error": "assistant response failed, please try again", "persistence_failed": "assistant response failed, please try again"}`
  — 3A does not need distinct public wording per code yet (that
  refinement is not blocking); the important property enforced here is
  that the **DB code** and the **public string** are two different values
  produced from one lookup, never the same raw string reused in both
  places.

## 6. Provider/model resolution and persistence

- **Resolved once, in Phase A**, via `provider = _build_chat_provider()`
  (new factory seam):
  ```python
  def _build_chat_provider() -> ChatProvider:
      return OpenAIChatProvider()
  ```
  `OpenAIChatProvider.__init__` does no network I/O (just sets
  `model_name` and lazily constructs the `AsyncOpenAI` client), so calling
  it inside the synchronous Phase A block before any `await` is safe and
  cheap — this is the concrete confirmation of the master plan's §4
  resolution to the "open item."
- **`provider.provider_name`/`provider.model_name`** are passed directly
  into `create_streaming_assistant_placeholder`'s existing `provider`/`model`
  parameters at creation time — **no changes to `conversations_queries.py`**
  (per the user's final decision on the master plan's open item:
  `finalize_assistant_message` stays state-transition-only, no
  `provider`/`model` parameter added there).
- **The same `provider` instance** (not a second `_build_chat_provider()`
  call) is reused in Phase B's `generate()` — passed into the generator as
  a parameter, so Phase A resolves it once and Phase B doesn't have to
  re-resolve or risk a mismatch between the DB-recorded model and the
  model actually used to stream.

## 7. Files and test scope for this slice

### Modified

- `backend/app/schemas.py` — add `PostMessageRequest`.
- `backend/app/main.py`:
  - New imports: `insert_user_message`, `create_streaming_assistant_placeholder`
    from `app.conversations_queries` (not yet imported — only
    `archive_conversation`/`create_conversation`/`get_conversation_with_active_messages`/
    `list_conversations`/`update_conversation` are imported today);
    `StreamingResponse` from `fastapi.responses`; `Request` from `fastapi`;
    `ChatDeltaEvent`/`ChatFinishEvent`/`ChatProviderError`/`ChatProviderTimeout`/
    `OpenAIChatProvider` from `app.services.chat_provider`; stdlib `asyncio`,
    `time`, `json` (json likely already needed — check for an existing
    import before adding), and `logging` (**new pattern for this codebase**
    — no `backend/app/` module currently uses `logging`; this slice
    introduces `log = logging.getLogger(__name__)` at module level in
    `main.py`, stdlib only, no new package).
  - New: `PostMessageRequest` import, `_build_chat_provider()`,
    `_sse_frame()`, `_public_error_message()`, `_build_provider_messages()`
    (new helper: maps `prior_messages` + `role_mode` + new user `content`
    into the `list[dict]` shape `AsyncOpenAI` expects — `[{"role": ..., "content": ...}, ...]`;
    for 3A this is a straightforward mapping of each prior active
    message's `role`/`content` plus an optional leading `{"role": "system", "content": ...}`
    derived from `role_mode` if set, plus the new user turn appended last;
    no seven-part-structure prompting here — that's 3B), `_finalize_with_fallback()`,
    the `generate()` async generator, and the `POST /conversations/{conversation_id}/messages`
    route itself.

### New test files

- `backend/tests/test_chat_streaming.py` — per `docs/step12_substep3a_plan.md`
  §5/§8: a fake `ChatProvider` driving `generate()` directly (not through
  `TestClient`, since `TestClient` does not straightforwardly simulate a
  mid-stream disconnect or a hung generator): scripted delta/finish
  sequence → `message_completed` + DB `status='completed'`; idle-timeout
  stall → `message_failed`/`provider_timeout`; raised `ChatProviderAPIError`
  → `message_failed`/`provider_error`; simulated `request.is_disconnected() == True`
  mid-loop → `status='aborted'`, no `message_failed`/`message_completed`
  frame emitted (best-effort suppressed since "disconnected" is exactly
  the condition that suppresses it); `_finalize_with_fallback` first-call-raises
  → second attempt succeeds, `finalized=True`; both attempts raise →
  `finalized=False`, `log.error` called, generator does not raise
  uncaught.
- Extend `backend/tests/test_conversations_api.py` (matching its existing
  `FakeConversationsConnection`-based style) with the Phase A checks that
  don't require actually consuming an SSE stream: `POST .../messages` on a
  missing conversation → `404`; on an archived conversation → `404`; blank
  `content` → `400`. (The 200/streaming happy path itself is exercised in
  `test_chat_streaming.py` against `generate()` directly, not via
  `TestClient.post(...)`, since `TestClient` buffers streaming responses
  rather than letting the test drive disconnect/timeout conditions.)
- `backend/tests/test_conversations_streaming_integration.py` — one
  real-Postgres test per the master plan §5/§8: asserts Phase A's
  connection is closed before Phase B/C run, and that Phase C's
  `_finalize_with_fallback` opens a connection with a different backend
  PID than Phase A's (same `pg_stat_activity` PID-comparison technique
  already used in `test_conversations_queries_integration.py`).

## 8. How this avoids leaving a permanent `streaming` row after disconnect/exception

This is the property the whole slice exists to guarantee, restated as a
checklist against the design above, not just asserted:

1. **Every exit from Phase B's loop is covered**: normal `StopAsyncIteration`,
   `ChatProviderTimeout` (idle or overall), any `ChatProviderError`, any
   other exception (catch-all), and disconnect (checked every iteration) —
   five paths, all five assign a `status` and fall through to the same
   single `_finalize_with_fallback` call. There is no `return`/`raise` inside
   the try block that could skip Phase C — every `except` branch falls
   through to the shared finalize call after the try/except, it does not
   re-raise.
2. **Phase C itself is not single-attempt**: `_finalize_with_fallback`
   tries a fresh connection twice before giving up, addressing the
   specific failure mode of "Phase C's own DB write fails" that a naive
   single-attempt finalize would leave uncovered.
3. **The one remaining gap is explicitly documented, not hidden**: if both
   fresh-connection attempts fail, the row stays `status='streaming'` —
   this is the same accepted, bounded residual risk already written into
   `docs/step12_substep3a_plan.md` §3, deferred to 3C's startup
   reconciliation wiring (already implemented as
   `mark_stale_streaming_messages_as_failed`, just not yet called from
   anywhere) or manual intervention. This slice does not claim a stronger
   guarantee than that — it claims "self-heals from one transient DB
   blip," not "never gets stuck."
4. **The disconnect check runs *before* processing each event, not just
   once at the end** — so a client that disconnects mid-token-stream is
   caught within one loop iteration (bounded by the 15s idle timeout at
   worst, if disconnect happens to coincide with waiting on the next
   token), not left running until the provider's own stream naturally
   ends.
5. **No code path constructs `StreamingResponse` without Phase A having
   already committed the placeholder row first** — the placeholder's
   existence is a precondition of Phase B/C ever running at all, so there
   is no route where Phase B/C "wins a race" against a placeholder that
   doesn't exist yet.

## Explicitly out of scope for this slice (unchanged from the master plan)

Tool-calling, citations, seven-part response structure, regenerate
endpoint, startup reconciliation wiring, frontend changes, schema changes,
new package installs, `PROGRESS.md` updates, Codex calls, `AGENTS.md`,
`worktrees/`, `runpane`.
