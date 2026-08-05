# Step 12 Sub-step 3C — Analysis and Implementation Plan (Regenerate API, Startup Reconciliation, Recovery Hardening)

> Builds on Sub-step 3A (Slices 1–4) and 3B (Slice 5), both merged to
> `feature/step12-streaming-api`. Scoped per `docs/step12_substep3_plan.md`
> §§7–8 (already approved: minimum-safety lifecycle already shipped in
> 3A/3B; 3C is stress-testing/hardening + the two pieces of functionality
> 3A/3B deliberately deferred: the regenerate endpoint and startup
> reconciliation wiring).
>
> **Revision after review**: the first draft proposed a route-level
> `SELECT` pre-check for the regenerate in-flight guard, which has a real
> TOCTOU race (two concurrent requests can both pass the check before
> either creates its attempt). Fixed by moving the check inside
> `create_regenerate_attempt`'s own `FOR UPDATE`-locked transaction
> (section 6). The read-time stale cleanup no longer lives inside
> `get_conversation_with_active_messages` (a getter must stay a pure read
> with no side effects) — it is a new, independent query primitive the
> route calls explicitly before reading (section 3). HTTP status mapping
> for `InvalidRegenerateTarget`/`ConversationMismatch` is corrected
> (section 4): the exception docstrings already in
> `conversations_queries.py` say "the caller maps this to a 409" (written
> at Sub-step 1, before this endpoint's contract existed), but the
> approved endpoint contract requires `400`/`404` respectively — the
> docstrings are stale comments to fix in passing.
>
> **A concrete conflict this revision surfaced, not assumed away**: the
> existing real-DB concurrency test
> (`test_conversations_queries_integration.py::test_concurrent_regenerate_calls_serialize_and_produce_no_duplicate_attempt_numbers`)
> seeds its parent message's first attempt via
> `create_streaming_assistant_placeholder` and never finalizes it —
> `status` stays `'streaming'` for the whole test. Adding the in-flight
> guard as designed (section 6) means **both** concurrent regenerate calls
> in that test would now see an already-`streaming` active attempt and
> get rejected, breaking a currently-passing test. This is fixed by
> updating that fixture to finalize the seeded attempt to `'completed'`
> before the concurrency test runs (its actual purpose — proving
> `FOR UPDATE` serializes two regenerate calls against a *normal* parent —
> was never about regenerating while the original send is still
> streaming; a completed precondition is the realistic case anyway, since
> no real UI would offer a "regenerate" action while the original answer
> is still streaming). See section 9 for the exact fixture change.

## 1. What already exists (read directly from the repo)

- **`create_regenerate_attempt`** (`conversations_queries.py`, Sub-step 1):
  fully implemented, concurrency-safe via `SELECT ... FOR UPDATE` on the
  parent user message, validated with a real two-connection integration
  test. Raises `ParentMessageNotFound`, `InvalidRegenerateTarget`,
  `ConversationMismatch`. **Not called from any route today.**
- **`mark_stale_streaming_messages_as_failed`** (`conversations_queries.py`,
  Sub-step 1): fully implemented (`UPDATE ... WHERE status='streaming'`,
  no age filter). **Not called from anywhere** — no lifespan exists in
  `main.py` at all (confirmed: zero `lifespan` references).
- **`generate()`** (`main.py`, 3A/3B): already fully generic over how the
  assistant placeholder was created — signature is `(message_id, provider,
  messages, request, is_diagnostic, build_embedding_provider)`, with no
  assumption baked in about `insert_user_message` having just run. **3C
  reuses `generate()` unchanged** — only Phase A (placeholder creation)
  and the route itself differ from `post_message`.
- **`_build_provider_messages`** already filters to `status='completed'`
  history and excludes the current turn — this needs no change for
  regenerate either; the parent user message is passed as `user_content`
  exactly like a normal send, and `prior_messages` is the active-message
  list minus that same parent id.

## 2. Startup reconciliation wiring

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        with get_connection() as conn:
            rowcount = mark_stale_streaming_messages_as_failed(conn)
            conn.commit()
        if rowcount:
            log.warning("startup reconciliation: marked %d stale streaming message(s) as failed", rowcount)
    except Exception:
        # Decision: a DB error here must NOT prevent the app from starting
        # -- crash-looping on every boot because reconciliation itself
        # can't reach the DB is worse than starting with some rows still
        # marked 'streaming' from a prior crash. The read-time stale
        # cleanup (section 3) is the safety net for exactly this case:
        # any row this failed to catch at startup still gets caught the
        # next time its conversation is read, once STREAMING_STALE_AFTER_SECONDS
        # has passed. This must be logged at ERROR (not WARNING) precisely
        # because it silently degrades a safety mechanism -- an operator
        # needs to notice and fix the underlying DB connectivity issue.
        log.error("startup reconciliation failed -- app will still start; stale rows rely on read-time cleanup", exc_info=True)
    yield

app = FastAPI(lifespan=lifespan)
```

- Runs **exactly once**, synchronously, before the app accepts requests.
- **No age/staleness threshold at startup** — every `status='streaming'`
  row present at process boot is, under the single-process assumption, by
  definition orphaned by a prior crash. This mirrors
  `docs/step12_substep3_plan.md` §8's already-approved reasoning; 3C does
  not add a time condition here since none is needed for correctness under
  that assumption.
- **Decision (this revision): reconciliation failure does not block
  startup**, but is logged at `ERROR` (not silently swallowed, not merely
  `WARNING`), and the read-time cleanup (section 3) is the documented
  fallback for whatever this pass missed.
- **Scope boundary, unchanged**: this lifespan hook does only this one
  reconciliation call — no periodic/background sweep is added (remains
  deferred from Sub-step 1 through 3A/3B/3C).

## 3. Read-time stale cleanup — independent query primitive, not a getter side effect

**Corrected from the first draft**: `get_conversation_with_active_messages`
stays a pure read. The stale-cleanup mutation is its own function, called
explicitly by the route *before* the read query runs — never hidden
inside a getter.

```python
STREAMING_STALE_AFTER_SECONDS = 300  # 5 minutes; comfortably longer than
# OVERALL_GENERATION_TIMEOUT_SECONDS (60s) plus two _finalize_with_fallback
# attempts combined, so a row still 'streaming' past this age is never a
# message genuinely still in flight.
```

```python
def mark_stale_streaming_attempts_for_conversation(conn, conversation_id: int, stale_before: datetime) -> int:
    """Idempotent, targeted stale-recovery: flips any message in this
    conversation still status='streaming' with created_at older than
    stale_before to 'failed'. The WHERE status='streaming' guard is the
    same idempotency mechanism finalize_assistant_message already relies
    on -- a message a concurrent request is genuinely still finalizing
    normally can never be double-transitioned by this call, because by
    the time this runs it has already left 'streaming' (or this call
    simply won't match it if it's still legitimately in progress and not
    yet past the cutoff). Cutoff is computed by the caller and passed in
    explicitly -- this function does not compute "now" itself, so tests
    can pass a deterministic stale_before without waiting."""
    result = conn.execute(
        text(
            """
            UPDATE chat_messages
            SET status = 'failed',
                error_message = 'stale_streaming',
                completed_at = now(),
                updated_at = now()
            WHERE conversation_id = :conversation_id
              AND status = 'streaming'
              AND created_at < :stale_before
            """
        ),
        {"conversation_id": conversation_id, "stale_before": stale_before},
    )
    return result.rowcount
```

Route usage (`GET /conversations/{id}` and `GET /conversations/{id}/messages`,
both already exist from Slice 2/3):

```python
@app.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: int, conn=Depends(get_db_dependency)):
    stale_before = datetime.now(timezone.utc) - timedelta(seconds=STREAMING_STALE_AFTER_SECONDS)
    mark_stale_streaming_attempts_for_conversation(conn, conversation_id, stale_before)
    conn.commit()
    detail = get_conversation_with_active_messages(conn, conversation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"conversation {conversation_id} not found")
    return detail
```

(Same two lines added to `get_conversation_messages`.) The cleanup call
happens unconditionally on every read of a conversation — a cheap
`UPDATE` that touches zero rows in the overwhelmingly common case (no
stale message), so this is not a meaningful cost per request.

**Why `created_at` and not `updated_at`/`started_at` for the cutoff**: a
`streaming` row's `created_at` is set once, at placeholder-creation time,
and never changes afterward for a row that stays `streaming` — using it
directly is the simplest, most robust comparison. (`updated_at` would also
work and is touched by nothing while a row stays `streaming`, so both are
equally valid here; `created_at` is used since it's the more obviously
"how old is this row" field.)

## 4. Regenerate API endpoint

```
POST /conversations/{conversation_id}/messages/{message_id}/regenerate
```

- `message_id` is the **parent user message id** (matching
  `create_regenerate_attempt`'s own parameter name) — documented
  explicitly in the route's docstring since it's easy to misread as an
  assistant message id.
- No request body.
- Response: `text/event-stream`, identical SSE contract to
  `post_message`, reusing `generate()` unchanged.

### HTTP status mapping (corrected from the first draft)

| Condition | Status | Source |
|---|---|---|
| Conversation doesn't exist or is archived | `404` | checked directly, same pattern as `post_message` |
| Parent user message doesn't exist, **or exists in a different conversation** | `404` | `ParentMessageNotFound` and `ConversationMismatch` both map here — from the caller's perspective, "exists but not in this conversation" and "doesn't exist" are treated identically (no information disclosure about a message id belonging to another conversation) |
| Message exists in this conversation but is not a `role='user'` message | `400` | `InvalidRegenerateTarget` — **corrected from `409`**: `conversations_queries.py`'s existing docstring says 409; that comment is stale and is fixed in the same change, not treated as authoritative over this approved endpoint contract |
| An attempt for this parent is already `is_active=true AND status='streaming'` | `409` | new `RegenerateAlreadyInProgress` (section 6) |
| Otherwise | `200`, `text/event-stream` | |

### Phase A (regenerate-specific; reuses `generate()` for Phase B/C unchanged)

```python
@app.post("/conversations/{conversation_id}/messages/{message_id}/regenerate")
async def post_regenerate(conversation_id: int, message_id: int, request: Request):
    with get_connection() as conn:
        detail = get_conversation_with_active_messages(conn, conversation_id)
        if detail is None or detail["conversation"]["archived_at"] is not None:
            raise HTTPException(status_code=404, detail=f"conversation {conversation_id} not found")
        role_mode = detail["conversation"]["role_mode"]

        parent_message = next((m for m in detail["messages"] if m["id"] == message_id), None)
        # see section 5 (_get_message_content) for why this lookup is safe
        # to do against detail["messages"] rather than a new query

        provider = _build_chat_provider()
        try:
            assistant_message_id = create_regenerate_attempt(
                conn, conversation_id, message_id, provider.provider_name, provider.model_name,
            )
        except ParentMessageNotFound:
            raise HTTPException(status_code=404, detail=f"message {message_id} not found")
        except ConversationMismatch:
            raise HTTPException(status_code=404, detail=f"message {message_id} not found")
        except InvalidRegenerateTarget:
            raise HTTPException(status_code=400, detail="message is not a regenerable user message")
        except RegenerateAlreadyInProgress:
            raise HTTPException(status_code=409, detail="a response is already being generated for this message")
        conn.commit()

        parent_content = parent_message["content"]  # validated to exist by the try/except above having succeeded
        prior_messages = [m for m in detail["messages"] if m["id"] != message_id]

    is_diagnostic = looks_like_diagnostic_question(parent_content)
    provider_messages = _build_provider_messages(prior_messages, parent_content, role_mode)
    return StreamingResponse(
        generate(assistant_message_id, provider, provider_messages, request, is_diagnostic, _build_embedding_provider),
        media_type="text/event-stream",
    )
```

Note: `parent_message` is looked up from `detail["messages"]` (fetched
*before* `create_regenerate_attempt` runs) purely to get `content` for the
provider call — it is **not** used as the source of truth for the
404/400/409 decisions above, which come entirely from
`create_regenerate_attempt`'s own exceptions (the real, lock-protected
validation). If `detail["messages"]` somehow didn't contain the id (e.g. a
narrow race where the message was inserted between the two reads — not
actually possible here since both reads are in the same transaction/
connection, but stated for clarity), `create_regenerate_attempt` is still
the authoritative check; `parent_message` being `None` after it succeeds
would only happen if that invariant were ever violated, which is treated
as a bug to catch in testing, not a runtime case to defensively code
around further.

## 5. `_get_message_content` — resolved, not assumed

**Checked against the actual code, per your instruction not to assume**:
`get_conversation_with_active_messages`'s `messages` list is built from
`SELECT * FROM chat_messages WHERE conversation_id = :id AND is_active = true`
— full row, no column projection, no truncation. User messages are never
given `is_active = false` anywhere in the codebase (only assistant
attempts are ever toggled, by `create_regenerate_attempt`'s own
`UPDATE ... SET is_active = false`) — so a user message, once inserted,
remains `is_active = true` for its entire lifetime and will always appear
in this list with its full `content`.

**Conclusion: no new query needed.** `detail["messages"]` (already fetched
in Phase A for `role_mode`/`archived_at` anyway) is sufficient to look up
the parent user message's content by id, exactly as shown in section 4's
code. No `_get_message_content` helper is added.

## 6. Regenerate in-flight guard — atomic, inside `create_regenerate_attempt`'s existing lock (Option A)

**The route-level pre-check from the first draft is removed entirely** —
replaced with a check inside `create_regenerate_attempt` itself, after the
existing `FOR UPDATE` lock is acquired and role/conversation validation
passes, before computing the new attempt number:

```python
class RegenerateAlreadyInProgress(Exception):
    """Raised by create_regenerate_attempt when the parent's current
    active attempt is still status='streaming'. The caller maps this to
    a 409. This check runs INSIDE the FOR UPDATE-locked transaction on
    the parent row -- not a separate pre-check -- specifically so two
    concurrent regenerate calls for the same parent cannot both pass a
    stale read before either commits (Codex-style review finding: a
    route-level SELECT-then-create has a TOCTOU race; only a check made
    inside the same lock scope that also performs the create is race-free)."""


def create_regenerate_attempt(conn, conversation_id, parent_user_message_id, provider, model) -> int:
    parent = conn.execute(
        text("SELECT id, conversation_id, role FROM chat_messages WHERE id = :id FOR UPDATE"),
        {"id": parent_user_message_id},
    ).mappings().first()
    if parent is None:
        raise ParentMessageNotFound(parent_user_message_id)
    if parent["role"] != "user":
        raise InvalidRegenerateTarget(parent_user_message_id)
    if parent["conversation_id"] != conversation_id:
        raise ConversationMismatch(parent_user_message_id)

    # NEW: fetch id AND status together (previously only `id`) -- reused
    # below for old_active_message_id, so this does not add a query, it
    # widens an existing one.
    old_active = conn.execute(
        text(
            "SELECT id, status FROM chat_messages "
            "WHERE parent_user_message_id = :parent_user_message_id AND is_active = true"
        ),
        {"parent_user_message_id": parent_user_message_id},
    ).mappings().first()
    if old_active is not None and old_active["status"] == "streaming":
        raise RegenerateAlreadyInProgress(parent_user_message_id)
    old_active_message_id = old_active["id"] if old_active else None

    # ... unchanged from here: max_attempt query, retire old attempt, insert new one
```

**Why this is race-free where the route pre-check was not**: the
`FOR UPDATE` lock on the parent row is acquired *before* the streaming
check runs, and every regenerate call for the same parent takes this same
lock — so two concurrent calls are fully serialized at this point. The
first call to acquire the lock sees whatever the active attempt's real
status is, creates its new attempt (which becomes the active, `streaming`
one), and commits (releasing the lock). The second call, having waited on
the lock, acquires it only after that commit and therefore *always* sees
the first call's new attempt as `is_active=true AND status='streaming'` —
there is no window where both calls can read "not streaming" before either
writes. This is the same lock that already serializes attempt-number
computation; this revision asks it to also enforce the streaming-rejection
invariant, rather than adding a second, unsynchronized check path.

**Original first-attempt creation is unaffected**: `create_streaming_assistant_placeholder`
(the very first attempt for a brand-new user message) still does not take
this lock, per Sub-step 1's documented carve-out — but that is fine here,
because by the time any regenerate call targets that same parent, the
first attempt's row (whatever its status) is already committed and
visible to the regenerate call's own lock-protected read. There is no
race between "a message's first send" and "a regenerate for that same
message", because the parent user message must already exist (and be
committed) before any regenerate call can reference its id at all.

## 7. Active attempt switching rules

Unchanged from Sub-step 1's already-implemented, already-proven logic:
retire the current `is_active=true` attempt, insert the new one as
`is_active=true`, both before the caller's single commit. 3C's only change
here is the new streaming-rejection check (section 6), inserted before
that logic runs, not a change to the switching logic itself.

## 8. Recovery strategy (unchanged from the reviewed proposal)

- **`failed`**: recoverable only via `POST .../regenerate`. No backend
  auto-retry.
- **`aborted`**: same — recoverable only via regenerate.
- **`streaming`** found on a read: resolved by section 3's read-time
  cleanup (if old enough) or is a genuinely in-progress generation (if
  not) — the client cannot tell these apart itself, which is exactly why
  this is a server-side concern, not a client heuristic.
- **No backend auto-retry, no background worker** — explicitly reaffirmed,
  not reopened by this revision.

### Reconnect vs. retry — stated explicitly for the API surface

- **Reconnect to an existing SSE stream is NOT supported** in this slice
  (or any prior one) — there is no `Last-Event-ID`/resumable-stream
  mechanism anywhere in this design (`docs/step12_substep3_plan.md` §4
  already established this for the original send; regenerate does not
  add one either).
- **Retry means calling `.../regenerate`**, which always creates a **new**
  assistant attempt (a new `chat_messages` row, new `attempt_number`) — it
  never resumes or replays a previous attempt's token stream. A client
  that dropped its SSE connection has no way to see the remainder of
  whatever the original attempt would have produced; once it observes
  (via a fresh `GET`) that the message ended up `aborted`, its only option
  is to regenerate, which starts over from the same parent user message,
  producing genuinely new model output.

## 9. Test strategy and files

### Fixture fix required (not new functionality, a correctness fix)

`backend/tests/test_conversations_queries_integration.py`'s
`seeded_parent_message` fixture must call `finalize_assistant_message(setup_conn,
first_attempt_id, "seeded answer", "completed", None, "stop", None)` (and
commit) after creating the placeholder, before yielding — otherwise the
existing `test_concurrent_regenerate_calls_serialize_and_produce_no_duplicate_attempt_numbers`
test breaks under the new in-flight guard (both concurrent calls would see
a `streaming` active attempt and get rejected, where the test currently
asserts both succeed). This is a precondition fix, not a change to what
that test proves.

### New files

- `backend/tests/test_startup_reconciliation.py`:
  - fake-connection unit test: `lifespan`'s reconciliation call marks a
    seeded `streaming` row `failed` (test 1).
  - fake-connection unit test: no `streaming` rows → no-op, no warning log
    (test 2).
  - fake-connection unit test: `mark_stale_streaming_messages_as_failed`
    monkeypatched to raise → `lifespan` catches it, logs at `ERROR`, still
    `yield`s (app still starts) (test 3).
  - real-Postgres test: seed a `streaming` row directly, invoke the
    `lifespan` context manager function against the real DB, assert the
    row flips to `failed` with `error_message='interrupted by server
    restart'`.
- `backend/tests/test_regenerate_api.py`:
  - 404 conversation missing/archived; 404 parent message missing; 404
    parent message in a different conversation; 400 role != user; 409
    already-streaming (fake-connection, monkeypatching
    `create_regenerate_attempt` to raise each exception in turn); happy
    path via `generate()` with a fake `ChatProvider` proving
    `attempt_number` increments and `is_active` switches correctly
    (test 7, 8, 9, 11, 13, 14).
  - test 8 specifically: seed a `failed` and an `aborted` first attempt in
    two separate cases, regenerate succeeds for both (not just
    `completed`).
- Extend `backend/tests/test_conversations_queries.py`:
  - `create_regenerate_attempt` raises `RegenerateAlreadyInProgress` when
    the active attempt is `streaming` (test 9's query-layer equivalent).
  - `create_regenerate_attempt` still succeeds normally when the active
    attempt is `completed`/`failed`/`aborted` (confirms the guard is
    status-specific, not a blanket rejection).
  - `mark_stale_streaming_attempts_for_conversation`: marks a `streaming`
    row older than `stale_before` as `failed` with the expected
    `error_message` (test 5); does NOT touch a `streaming` row newer than
    `stale_before` (test 4); does NOT touch non-`streaming` rows; does NOT
    touch `streaming` rows in a *different* conversation.
- Extend `backend/tests/test_conversations_queries_integration.py`:
  - the fixture fix above.
  - **new real-DB concurrency test** (test 10): two threads call
    `create_regenerate_attempt` concurrently for the same (now-completed)
    seeded parent; assert exactly one succeeds (returns a new id) and the
    other raises `RegenerateAlreadyInProgress`; assert exactly 2 attempts
    exist afterward (1 seeded + 1 new), not 3 — proving the `FOR UPDATE`
    lock ordering genuinely prevents the second call from ever seeing a
    stale "not streaming" read.
  - test 6 (cleanup vs. concurrent finalize never overwrites a terminal
    status): seed a `streaming` row old enough to be stale, then in one
    connection call `finalize_assistant_message` (transitioning it to
    `completed`) *before* calling `mark_stale_streaming_attempts_for_conversation` —
    assert the row stays `completed`, not overwritten to `failed` (the
    `WHERE status='streaming'` guard on the cleanup query is what
    prevents this).
  - test 12/15: full regenerate HTTP-level cycle against a real DB and a
    fake `ChatProvider` (via monkeypatching `_build_chat_provider`, same
    pattern as `test_conversations_streaming_integration.py`'s existing
    tests) — proves Phase C uses a fresh connection (same technique
    already established) and that no row is left in a non-terminal
    `streaming` state after the full cycle completes.

### Modified files

- `backend/app/conversations_queries.py` — `RegenerateAlreadyInProgress`
  exception; `create_regenerate_attempt`'s widened `old_active` query +
  new check (section 6); new `mark_stale_streaming_attempts_for_conversation`
  function (section 3). `finalize_assistant_message` and
  `mark_stale_streaming_messages_as_failed` remain untouched.
- `backend/app/main.py` — `lifespan` (section 2), `STREAMING_STALE_AFTER_SECONDS`
  constant, the two-line cleanup-call addition to `get_conversation` and
  `get_conversation_messages` (section 3), the new regenerate route
  (section 4), `app = FastAPI(lifespan=lifespan)`.
- `backend/tests/fakes.py` — `FakeConversationsConnection`'s existing
  "`SELECT id FROM chat_messages WHERE parent_user_message_id ... AND
  is_active = true`" branch widened to also return `status` (matching the
  real SQL's widened column list); new branch for the stale-cleanup
  `UPDATE`.

## Explicitly out of scope for this slice

Periodic/background reconciliation sweep (remains deferred), multi-worker-
safe reconciliation (remains deferred per `docs/step12_substep3_plan.md`
§8), resumable/reconnectable SSE streams (explicitly not supported, stated
in section 8), frontend changes, schema/migration changes (no new
columns — `error_message`/`completed_at`/`updated_at` all already exist),
new package installs, `PROGRESS.md` updates, Codex calls, `AGENTS.md`,
`worktrees/`, `runpane`.
