# Step 12 Sub-step 3A — Implementation Plan (Conversation CRUD, ChatProvider, SSE Minimum-Safe Lifecycle)

> Planning document only. No functional code, schema, or migration has been
> written yet. Scoped strictly to 3A per `docs/step12_substep3_plan.md`
> (the reviewed overall Sub-step 3 architecture, already approved). This
> document resolves the three technical decisions that plan left open for
> 3A implementation time.

## 1. Decision: `AsyncOpenAI` native async streaming, not sync client + thread

**Chosen: `AsyncOpenAI`.** Reasoning, weighed against sync client + bounded
worker thread:

- **Cancellation is a first-class primitive with `AsyncOpenAI`, not with a
  thread.** When the client disconnects mid-stream, the FastAPI request
  handling task can be cancelled (or observed via `is_disconnected()`); an
  `async for` loop consuming an `AsyncOpenAI` stream responds naturally to
  `asyncio.CancelledError` / a `wait_for` timeout and stops making further
  network reads. A sync call running inside a worker thread (e.g. via
  `anyio.to_thread.run_sync`) cannot be forcibly cancelled at all in
  Python — the thread keeps running the blocking HTTP call to completion
  (or its own internal timeout) even after the request handler gives up on
  it, which means: (a) the provider call keeps consuming API quota/cost for
  a client that already left, and (b) there is no clean way to guarantee
  the thread's eventual result doesn't race with a Phase C that already ran
  via the cancellation path.
- **Timeout enforcement is simpler and more precise.** `asyncio.wait_for`
  around an async generator's `__anext__()` gives a precise per-token idle
  timeout (section 2) with no additional thread/queue machinery. Doing the
  same for a thread-wrapped sync call requires a separate cross-thread
  signaling mechanism (e.g. a `queue.Queue` the thread pushes into and the
  async side polls) just to approximate what `asyncio.wait_for` gives for
  free.
- **`openai==2.48.0` (already installed, no new package) ships `AsyncOpenAI`
  as a first-class client** — this is not a new dependency, just a
  different import (`from openai import AsyncOpenAI`) from the same
  package already used by `OpenAIEmbeddingProvider`.
- **Must not block the event loop**: this is the explicit constraint from
  `docs/step12_substep3_plan.md` §11, and it is exactly what `AsyncOpenAI`
  is designed to satisfy directly — no `run_in_threadpool` bridging layer
  needed for the chat path (unlike `OpenAIEmbeddingProvider`, which stays
  sync because it is only ever called from a background task thread today,
  not from an async request-handling path; that provider is out of scope
  for this change).

**Concrete `ChatProvider` contract** (replaces the `class ChatStreamEvent(Protocol): ...`
placeholder from the overall plan — the earlier draft's TBD is resolved
here, not deferred further):

```python
from dataclasses import dataclass
from typing import AsyncIterator, Optional, Protocol


@dataclass(frozen=True)
class ChatDeltaEvent:
    delta: str


@dataclass(frozen=True)
class ChatFinishEvent:
    finish_reason: str  # "stop" | "length" | "content_filter" | "tool_calls"
    usage: Optional[dict]  # {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int} or None


ChatStreamEvent = ChatDeltaEvent | ChatFinishEvent


class ChatProviderError(RuntimeError):
    """Base class for all provider-side failures this module raises.
    Callers map subclasses to the sanitized error_message codes in
    docs/step12_substep3_plan.md section 10."""


class ChatProviderTimeout(ChatProviderError):
    """Raised on first-token or overall generation timeout (section 2).
    Caller maps this to error_message='provider_timeout'."""


class ChatProviderAPIError(ChatProviderError):
    """Raised when the provider API itself returns an error (rate limit,
    auth, malformed response, etc). Caller maps this to
    error_message='provider_error'. Wraps the underlying openai SDK
    exception as __cause__ for server-log-only detail (section 10) --
    never surfaced directly to the DB or SSE layer."""


class ChatProvider(Protocol):
    provider_name: str
    model_name: str

    def stream_chat(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> AsyncIterator[ChatStreamEvent]: ...


class OpenAIChatProvider:
    provider_name = "openai"

    def __init__(self, model: str = "gpt-4o-mini", client: "AsyncOpenAI | None" = None):
        self.model_name = model
        if client is not None:
            self._client = client  # test hook: inject a fake async client
        else:
            from openai import AsyncOpenAI  # lazy import, matches OpenAIEmbeddingProvider's convention

            self._client = AsyncOpenAI()

    async def stream_chat(self, messages, tools=None) -> AsyncIterator[ChatStreamEvent]:
        try:
            stream = await self._client.chat.completions.create(
                model=self.model_name, messages=messages, tools=tools, stream=True,
            )
        except Exception as exc:
            raise ChatProviderAPIError("failed to open chat stream") from exc

        try:
            async for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if choice is None:
                    continue
                if choice.delta and choice.delta.content:
                    yield ChatDeltaEvent(delta=choice.delta.content)
                if choice.finish_reason is not None:
                    usage = getattr(chunk, "usage", None)
                    yield ChatFinishEvent(
                        finish_reason=choice.finish_reason,
                        usage=usage.model_dump() if usage else None,
                    )
        except Exception as exc:
            raise ChatProviderAPIError("chat stream interrupted") from exc
```

`tools` stays a typed parameter (accepted, always `None`/empty in 3A calls)
so 3B does not need to change this Protocol's shape later — only start
passing real tool schemas through it. **3A does not implement tool-calling
itself**: no tool registry, no `tool_call`/`tool_result` SSE events wired
up (those event types remain documented in the overall plan for 3B, not
emitted by 3A code).

Factory seam, matching `_build_embedding_provider()`'s existing pattern in
`main.py`:

```python
def _build_chat_provider() -> ChatProvider:
    return OpenAIChatProvider()
```

## 2. Decision: timeout contract (concrete values)

| Timeout | Value | Enforcement mechanism |
|---|---|---|
| Per-event idle timeout (covers first-token latency and any mid-stream stall) | **15 seconds** | `asyncio.wait_for(stream.__anext__(), timeout=15)` around each iteration of the provider stream. Applies uniformly to "waiting for the first token" and "waiting for the next token after N have already arrived" — one mechanism, not two separate timers. |
| Overall generation hard cap (whole Phase B, from provider call start to final `ChatFinishEvent`) | **60 seconds** | Wall-clock elapsed time checked after each yielded event; if exceeded, the consuming loop raises `ChatProviderTimeout` and stops reading further from the stream (it does not wait for the underlying `stream.aclose()` to finish network teardown before proceeding to Phase C). |
| Cancellation / disconnect check | Every event, not a separate polling loop | Before processing each `ChatStreamEvent`, the route handler calls `await request.is_disconnected()`. Because this check sits in the same `async for` loop as the idle-timeout `wait_for`, no separate timer/poll task is needed — disconnect detection piggybacks on the same per-token loop iteration that already awaits something. |

Either timeout firing maps to the same outcome already specified in the
overall plan: Phase C runs with `status='failed'`,
`error_message='provider_timeout'`. These two specific numbers (15s / 60s)
are 3A's committed values, not placeholders — they may be revisited with
real usage data post-MVP, but 3A ships with them fixed, not configurable
via environment variable (no config surface is being added for this in
3A; hardcoded constants in the chat route module, matching how
`MAX_ANALYSIS_ROWS` is a hardcoded constant in `main.py` today).

## 3. Decision: Phase C finalize-failure handling (fresh-connection fallback)

The overall plan states every `chat_messages` row reaches a terminal DB
status. That guarantee is only as strong as Phase C's own robustness — if
the fresh connection can't be opened, or the `UPDATE`/commit inside it
fails (transient DB blip, connection pool exhaustion, deadlock), the row
would otherwise stay `status='streaming'` with nothing further to catch it
until the *next process restart's* reconciliation (section 8 of the
overall plan) runs. 3A does not defer the first attempt at mitigating this
to 3C; it ships one bounded fallback:

```python
def _finalize_with_fallback(message_id, content, status, error_message, finish_reason, usage) -> bool:
    """Returns True if the row was confirmed finalized (this call or a
    prior one already did it), False if both attempts failed -- in which
    case the row is a documented, logged residual risk (see below), not
    silently swallowed."""
    for attempt in (1, 2):
        try:
            with get_connection() as conn:
                rowcount = finalize_assistant_message(
                    conn, message_id, content, status, error_message, finish_reason, usage
                )
                conn.commit()
            if rowcount == 0:
                # Already finalized by something else (e.g. a race with
                # startup reconciliation) -- not a failure of this call.
                log.info("finalize no-op: message %s already left 'streaming'", message_id)
            return True
        except Exception:
            log.exception("finalize attempt %d failed for message %s", attempt, message_id)
            # attempt 1 failing falls through to a second try with a brand
            # new connection (not a retry on the same broken one);
            # attempt 2 failing falls through to the return False below.
    return False
```

Call sites and their behavior on the `False` return:

- **Provider success / provider failure / disconnect paths (section 7 of
  the overall plan) all funnel through this same `_finalize_with_fallback`
  call** for Phase C — there is exactly one finalize code path, not one
  per failure mode, so this fallback logic is written and tested once.
- **If both attempts fail**: this is logged at `ERROR` level with the
  `message_id`, attempt count, and the real exception detail (server log
  only, per section 10's three-tier separation — never written to the DB,
  since the DB write is precisely what just failed twice). A best-effort
  SSE `message_failed` frame with `error: "persistence_failed"` is still
  attempted if the connection to the client is open (same best-effort
  posture as every other terminal SSE emission in this plan). **This is an
  explicit, documented residual Known Issue for 3A, not silently accepted
  as fine**: a message that hits this path is left `status='streaming'`
  in the DB despite two fresh-connection attempts, and will only be
  corrected the next time the process restarts and startup reconciliation
  (Sub-step 3C, once wired) runs — or manually. This gap is intentionally
  bounded (one extra fresh-connection attempt, not an unbounded retry
  loop) and is recorded as a known limitation in the execution report when
  3A ships; 3C may add backoff/more attempts/alerting, but 3A's job is to
  make the common transient-failure case (one blip) self-heal rather than
  leaving zero retries.

## 4. 3A endpoint contract

All new endpoints live in `backend/app/main.py`, following the existing
route style exactly (no new router/blueprint abstraction — this codebase
does not use one).

### Pydantic schemas (`backend/app/schemas.py` additions)

```python
class ConversationCreateRequest(BaseModel):
    role_mode: Optional[str] = None  # validated against the same 4 values as the DB CHECK constraint

class ConversationSummary(BaseModel):
    id: int
    title: Optional[str] = None
    role_mode: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class ConversationsPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ConversationSummary]

class ChatMessageSummary(BaseModel):
    id: int
    role: str
    content: str
    status: str
    parent_user_message_id: Optional[int] = None
    attempt_number: int
    is_active: bool
    provider: Optional[str] = None
    model: Optional[str] = None
    finish_reason: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

class ConversationDetail(BaseModel):
    conversation: ConversationSummary
    messages: list[ChatMessageSummary]

class ConversationUpdateRequest(BaseModel):
    title: Optional[str] = None
    role_mode: Optional[str] = None

class PostMessageRequest(BaseModel):
    content: str  # no role_mode field -- removed per the overall plan's audit fix
```

### Endpoints

| Endpoint | Request | Response | Status codes |
|---|---|---|---|
| `POST /conversations` | `ConversationCreateRequest` | `ConversationSummary` | `201` created; `422` invalid `role_mode` (FastAPI/Pydantic validation, matching the DB CHECK's 4 allowed values) |
| `GET /conversations` | `limit`/`offset` query params (same pattern as `GET /cases`) | `ConversationsPage` | `200` |
| `GET /conversations/{id}` | — | `ConversationDetail` | `200`; `404` if `get_conversation_with_active_messages` returns `None` |
| `PATCH /conversations/{id}` | `ConversationUpdateRequest` | `ConversationSummary` | `200`; `404` if `update_conversation` returns `None` |
| `DELETE /conversations/{id}` | — | `{"archived": true}` | `200`; `404` if `archive_conversation` returns `0` rows affected |
| `POST /conversations/{id}/messages` | `PostMessageRequest` | `text/event-stream` (SSE, see below) | `404` (as a JSON error, before any SSE starts) if the conversation doesn't exist or is archived; `400` if `content` is blank (mirrors the existing `query must not be blank` pattern in `post_case_search`); otherwise `200` with a streaming body |

**Archived-conversation behavior**: posting a message to an archived
conversation is rejected with `404` (treated as "not found" from the
caller's perspective, consistent with `list_conversations`/
`get_conversation_with_active_messages` already excluding/handling
archived conversations) — not silently un-archiving it and not silently
accepting the message.

### `POST /conversations/{id}/messages` — Phase A transaction (concrete)

```python
@app.post("/conversations/{conversation_id}/messages")
async def post_message(conversation_id: int, body: PostMessageRequest):
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="content must not be blank")

    with get_connection() as conn:
        conv = get_conversation_with_active_messages(conn, conversation_id)
        if conv is None or conv["conversation"]["archived_at"] is not None:
            raise HTTPException(status_code=404, detail=f"conversation {conversation_id} not found")
        role_mode = conv["conversation"]["role_mode"]

        user_message_id = insert_user_message(conn, conversation_id, content)
        assistant_message_id = create_streaming_assistant_placeholder(
            conn, conversation_id, user_message_id, attempt_number=1,
            provider=None, model=None,  # filled in once the provider call actually starts, see below
        )
        conn.commit()
    # connection closed here -- before generate() is ever called.

    return StreamingResponse(
        generate(conversation_id, assistant_message_id, conv["messages"], content, role_mode, request),
        media_type="text/event-stream",
    )
```

`provider=None, model=None` at placeholder-creation time (rather than
passing the real provider/model already): the placeholder is created
*before* `_build_chat_provider()` is even instantiated, so there is
nothing real to record yet; the generator records the actual
`provider_name`/`model_name` as part of the same Phase C
`finalize_assistant_message` call once the stream concludes (that
function's existing signature already has no separate provider/model
update path outside of `create_streaming_assistant_placeholder` — **this
is a real gap this plan surfaces, not papers over**: either
`finalize_assistant_message` needs a `provider`/`model` parameter added in
3A's implementation, or `create_streaming_assistant_placeholder` must be
called with the real provider/model already known by resolving
`_build_chat_provider()` before creating the placeholder. **Resolved
here**: 3A implementation instantiates `_build_chat_provider()` first
(cheap, no network call — it's just `OpenAIChatProvider.__init__`, no
`await` inside it), reads `provider_name`/`model_name` off it, and passes
those into `create_streaming_assistant_placeholder` — so Phase A's
transaction above is amended to build the provider before the placeholder
insert, not after.

### SSE frame encoder

```python
def _sse_frame(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
```

Event types emitted by 3A specifically (subset of the overall plan's full
table — `tool_call`/`tool_result` are 3B-only and never emitted by 3A
code): `message_started`, `token`, `message_completed`, `message_failed`.

### Client disconnect detection

Inside the generator's per-event loop (section 2 above), `await
request.is_disconnected()` is checked before yielding/processing each
`ChatStreamEvent`. On `True`, the loop breaks out without yielding further
SSE frames, and proceeds directly to Phase C with `status='aborted'` and
whatever partial `content` was accumulated so far.

### `completed` / `failed` / `aborted` persistence — one shared path

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
        # catch-all fail-closed path, per docs/step12_substep3_plan.md section 7
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

This is one function with one finalize call site, matching section 3's
requirement that all three outcomes (`completed`/`failed`/`aborted`) share
the same `_finalize_with_fallback` path rather than three separate,
independently-maintained code paths.

## 5. Files and tests

### New files

- `backend/app/services/chat_provider.py` — `ChatDeltaEvent`,
  `ChatFinishEvent`, `ChatProviderError`/`ChatProviderTimeout`/
  `ChatProviderAPIError`, `ChatProvider` Protocol, `OpenAIChatProvider`.
- `backend/tests/test_chat_provider.py` — fake `AsyncOpenAI`-shaped client
  (async generator stub) covering: normal delta/finish sequence, API error
  on stream open, mid-stream exception, empty-choices chunk handling.
- `backend/tests/test_conversations_api.py` — fake-connection tests for
  every CRUD endpoint (matching `test_cases_api.py`'s existing pattern):
  create/list/get/patch/archive happy paths, 404s (missing conversation,
  archived conversation for `POST .../messages`), 400 (blank content), 422
  (invalid `role_mode`).
- `backend/tests/test_chat_streaming.py` — a fake `ChatProvider` (yields a
  scripted sequence of `ChatDeltaEvent`/`ChatFinishEvent`, or raises a
  specific `ChatProviderError` subclass, or stalls to trigger the idle
  timeout) driving the SSE generator directly (not through a live HTTP
  client) to assert: correct SSE frame sequence for a successful
  completion; `status='failed'`/`error_message='provider_timeout'` on idle
  timeout; `status='failed'`/`error_message='provider_error'` on API/
  unexpected exception; `status='aborted'` on a simulated disconnected
  request; `_finalize_with_fallback`'s second-attempt success after a
  first `finalize_assistant_message` call is forced to raise (via a fake
  connection/monkeypatch); the `False`-return / both-attempts-fail path
  logs at `ERROR` and does not raise out of the generator.
- `backend/tests/test_conversations_streaming_integration.py` — one
  real-Postgres integration test (mirroring
  `test_conversations_queries_integration.py`'s existing pattern) proving
  Phase A's connection is actually closed before Phase B/C run (e.g. by
  asserting connection-pool checked-out-connection count returns to
  baseline immediately after the endpoint call returns its `StreamingResponse`,
  before the body is even consumed) and that Phase C opens a distinct
  connection from Phase A (e.g. via `pg_stat_activity` PID comparison, same
  technique already used in the Sub-step 1 integration test).

### Modified files

- `backend/app/main.py` — new endpoints (section 4), `_build_chat_provider`
  factory seam, the `generate()` SSE handler, `_finalize_with_fallback`,
  `_sse_frame`, `_public_error_message` (small dict keyed by the sanitized
  DB codes from `docs/step12_substep3_plan.md` section 10).
- `backend/app/schemas.py` — new Pydantic models (section 4).
- `backend/app/conversations_queries.py` — **not modified for its existing
  10 functions**, but see the open item in section 6 below about whether
  `finalize_assistant_message` needs a `provider`/`model` parameter added.
- `requirements.txt` — **no change**; `AsyncOpenAI` ships in the already-
  pinned `openai==2.48.0`.

## 6. Explicitly out of scope for 3A (unchanged from the overall plan, restated for this focused document)

Tool registry, citations, seven-part response structure, regenerate
endpoint, startup reconciliation wiring, frontend changes, schema changes,
new package installs, `PROGRESS.md` updates, Codex calls.

## 7. Open item still needing a decision before implementation starts

Section 4 surfaced one concrete open question while working through the
Phase A transaction detail: **does `finalize_assistant_message` need a new
`provider`/`model` parameter**, or should 3A instead resolve
`_build_chat_provider()` before `create_streaming_assistant_placeholder`
and pass `provider_name`/`model_name` in at placeholder-creation time (as
this document currently proposes in section 4)? This plan's proposed
resolution (build the provider first, pass real values into the existing
`create_streaming_assistant_placeholder` signature, no change to
`finalize_assistant_message`) is written above as the working design, but
is flagged here explicitly in case there's a reason to prefer changing
`finalize_assistant_message`'s signature instead — otherwise this plan
proceeds with the "resolve provider first" approach as final.

## 8. Acceptance criteria

- Every endpoint in section 4 has a passing fake-connection test for its
  documented status codes.
- `test_chat_streaming.py` demonstrates all four terminal paths
  (`completed`, `failed` from timeout, `failed` from provider error,
  `aborted` from disconnect) each result in exactly one
  `finalize_assistant_message`-confirmed terminal DB status, using a fake
  provider — no real OpenAI API calls in this test file.
- `test_conversations_streaming_integration.py` proves against a real dev
  Postgres database that Phase A's connection closes before Phase B/C
  begin, and that Phase C uses a distinct connection from Phase A.
- The fallback-finalize path in section 3 is exercised by a test that
  forces the first attempt to fail and confirms the second attempt still
  produces a terminal DB status; a separate test forces both attempts to
  fail and confirms the generator does not raise uncaught, logs an
  `ERROR`, and still attempts the best-effort SSE `message_failed` frame.
- Full-repo `pytest` stays green.
- `npm run lint` / `npm run build` unaffected (3A is backend-only).
