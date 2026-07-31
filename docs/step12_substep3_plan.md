# Step 12 Sub-step 3 — Architecture Investigation and Planning

> Planning document only. No functional code, schema, or migration has been
> written yet. This is an architecture investigation followed by a proposed
> split of Sub-step 3 into smaller sub-steps, produced before any
> implementation begins, matching the review-before-code precedent set by
> `docs/step12_substep1_plan.md`.

## 1. What already exists (read directly from the repo, not assumed)

- **Schema + query layer (Sub-step 1, PR #38)**: `conversations` /
  `chat_messages` tables and `backend/app/conversations_queries.py` already
  implement `create_conversation`, `list_conversations`,
  `get_conversation_with_active_messages`, `update_conversation`,
  `archive_conversation`, `insert_user_message`,
  `create_streaming_assistant_placeholder`, `finalize_assistant_message`,
  `create_regenerate_attempt` (concurrency-safe via `FOR UPDATE`), and
  `mark_stale_streaming_messages_as_failed`. All ten functions follow the
  connection-ownership contract: they accept an external `conn` and never
  commit/rollback themselves.
- **No chat/conversation HTTP route exists at all.** `backend/app/main.py`
  has zero references to `chat` or `conversation` — Sub-step 1 delivered
  schema + query layer only, by design.
- **No `ChatProvider` abstraction exists.** The only provider abstraction in
  the codebase is `backend/app/services/embedding_provider.py`
  (`EmbeddingProvider` Protocol, `OpenAIEmbeddingProvider` implementation,
  injected via a `_build_embedding_provider()` factory seam in `main.py` so
  tests can monkeypatch it). This is the pattern a `ChatProvider` should
  mirror, not something to invent from scratch.
- **No FastAPI lifespan/startup handler exists.** `main.py` only has
  `app = FastAPI()` with no `@app.on_event("startup")` or `lifespan=`
  context manager — startup reconciliation for
  `mark_stale_streaming_messages_as_failed` has nowhere to attach yet.
- **DB dependency (`backend/app/db.py`)**: `get_connection()` returns a
  plain `engine.connect()`; `get_db_dependency()` wraps it in a `with` block
  as a FastAPI `Depends` generator, request-scoped (one connection open for
  the whole request). This is the connection Sub-step 1's plan document
  already flagged as unsafe to reuse across a streaming/orchestration gap
  for `finalize_assistant_message`.
- **Existing structured-data query layer to reuse as tool-calling targets**
  (per ADR-002, no unrestricted Text-to-SQL): `backend/app/datasets_queries.py`
  (`list_datasets`, `get_dataset_by_id`, `get_dataset_summary`,
  `get_dataset_timeseries`, `get_analysis_run`), `backend/app/services/rule_engine.py`
  (`evaluate_battery_should_discharge_but_did_not`), `backend/app/services/retrieval.py`
  (`retrieve_chunks` — already designed with a docstring noting it is "meant
  to be called directly by a future Step 12 tool-calling layer, not through
  app/main.py"), `backend/app/services/case_retrieval.py`
  (`find_similar_to_case`, `search_by_text`), `backend/app/case_records_queries.py`.
  All of these are plain Python functions taking `conn` plus typed
  parameters — exactly the shape a fixed tool registry needs.
- **Frontend**: `/assistant` (`frontend/app/(dashboard)/assistant/page.tsx`)
  is still an explicit placeholder ("尚未開放，等待 Step 12") with no API
  contract assumptions baked in yet — nothing to preserve compatibility
  with.
- **Dependencies (`requirements.txt`)**: `openai==2.48.0` is already
  installed (used today only for embeddings) and its SDK also exposes chat
  completions/streaming, so a `ChatProvider` can reuse the same package
  with no new install. FastAPI's own `StreamingResponse` can serve SSE
  without adding a package like `sse-starlette`. No package addition is
  proposed in this plan.

## 2. Should Sub-step 3 be split? Yes — recommended 3A / 3B / 3C

The original framing ("ChatProvider + SSE + full tool orchestration in one
sub-step") bundles three concerns with different risk profiles and
different testability:

- **3A is plumbing, but must ship a complete minimum-safety lifecycle**:
  conversation CRUD endpoints, a `ChatProvider` abstraction with no
  tool-calling, and the full SSE streaming lifecycle (connect → stream
  tokens → finalize on success, on provider failure, and on client
  disconnect/cancellation). "No tool-calling" is the only thing deferred to
  3B — 3A must not merge with any known path that leaves a `chat_messages`
  row permanently stuck in `status='streaming'` (see the revised section 7
  below; this was corrected from an earlier draft that deferred
  disconnect/failure persistence to 3C).
- **3B is the ADR-002 / MVP1_RULES §8-governed layer**: turning the fixed
  query-layer functions listed in section 1 into a bounded tool registry,
  wiring Internal Knowledge Only enforcement, and producing the seven-part
  response structure. This has real product-rule content (confidence
  thresholds, citation typing, disabled external-search guard) that
  deserves its own focused review, separate from the streaming plumbing.
- **3C is hardening, not a safety-net for gaps left by 3A**:
  `create_regenerate_attempt` wiring at the API layer, startup
  reconciliation lifespan wiring, precise timeout tuning, disconnect/
  cancellation stress testing, and finalize-fallback/recovery hardening.
  3A already delivers a correct (if not battle-hardened) terminal-state
  guarantee on its own; 3C exists to stress-test and harden that guarantee
  under concurrency, timing edge cases, and process restarts — not to
  supply the guarantee for the first time.

Recommendation: **proceed with 3A → 3B → 3C in that order**, each as its own
reviewed plan/implementation/test cycle (mirroring how Step 10 and Step 6
were sub-divided). This section documents the reasoning; sections 3–11
below describe the design questions that span all three so the split
doesn't leave gaps at the seams.

## 3. API endpoints and request/response schemas

Proposed REST surface (naming follows the existing `snake_case` JSON body /
`Response` model convention in `backend/app/schemas.py`):

| Endpoint | Sub-step | Purpose |
|---|---|---|
| `POST /conversations` | 3A | Create a conversation (`role_mode` optional). Wraps `create_conversation`. |
| `GET /conversations` | 3A | Paginated list, non-archived. Wraps `list_conversations`. |
| `GET /conversations/{id}` | 3A | Conversation + active messages. Wraps `get_conversation_with_active_messages`. |
| `PATCH /conversations/{id}` | 3A | Update `title`/`role_mode`. Wraps `update_conversation`. |
| `DELETE /conversations/{id}` | 3A | Archive (soft-delete). Wraps `archive_conversation`. |
| `POST /conversations/{id}/messages` | 3A (plumbing) / 3B (content) | Submit a user message; streams the assistant reply via SSE. |
| `POST /conversations/{id}/messages/{message_id}/regenerate` | 3C | Regenerate the assistant reply for a given parent user message; streams via SSE. Wraps `create_regenerate_attempt`. |

`POST /conversations/{id}/messages` request body:

```json
{
  "content": "為什麼 12 號電池今天沒有依排程放電？"
}
```

**No per-message `role_mode` override.** An earlier draft of this plan
allowed `role_mode` in this request body; that is corrected here. Every
`chat_messages` row records `role_mode` nowhere, so an earlier answer's
mode could not be audited after the fact if the mode could vary
message-by-message with no persisted record of which mode applied. 3A
always uses the conversation's own stored `role_mode` (read via
`get_conversation_with_active_messages`/the conversation row) for every
message in it. To change mode mid-conversation, the client must call
`PATCH /conversations/{id}` first — that call is itself an auditable,
timestamped state change (`updated_at` bumps), unlike a bare per-message
field. This endpoint's *response* is not JSON — see the SSE contract
below.

## 4. SSE event contract

`POST /conversations/{id}/messages` and the regenerate endpoint both return
`text/event-stream` via FastAPI's `StreamingResponse`. Proposed event types
(each SSE frame is `event: <type>\ndata: <json>\n\n`):

| `event` | `data` payload | Meaning |
|---|---|---|
| `message_started` | `{"message_id": int, "attempt_number": int}` | Assistant placeholder row created; client can now render a pending bubble. |
| `token` | `{"delta": str}` | One incremental content chunk from the provider. |
| `tool_call` | `{"tool_name": str, "arguments": dict}` | 3B only: the assistant is invoking a fixed tool (rendered as a transient "checking dataset X…" indicator, not part of final content). |
| `tool_result` | `{"tool_name": str, "summary": str}` | 3B only: tool call completed; `summary` is a short, non-sensitive description (never the raw row dump) for client display. |
| `message_completed` | `{"message_id": int, "finish_reason": str, "usage": {...} \| null}` | Terminal success event. |
| `message_failed` | `{"message_id": int, "error": str}` | Terminal failure event. `error` is the **public**, sanitized message (see section 10) — never a raw provider exception or stack trace. |

**What is actually guaranteed vs. best-effort** (corrected from an earlier
draft that overstated this): every `chat_messages` row reaches exactly one
terminal **DB** status (`completed`/`failed`/`aborted`) — that DB row is
the source of truth, not the SSE stream. Emitting a terminal SSE event
(`message_completed`/`message_failed`) back to the client is **best
effort only**: if the client has already disconnected, there is no
guarantee any frame — terminal or otherwise — can still be written, and
the server does not treat a failed final write as an error condition, only
as "client no longer listening." A stream that never got a terminal SSE
frame because the client disconnected first is not a bug; a `chat_messages`
row with no terminal DB status is.

**Client is `fetch()`-based, not `EventSource`.** The planned frontend
consumption model for this endpoint is a `fetch()` call reading the
response body as a stream (so it can `POST` a JSON body, which `EventSource`
cannot do), not a native browser `EventSource`. This plan does **not**
assume `EventSource`'s automatic-reconnect behavior or `Last-Event-ID`
semantics — there is no resumable/replayable stream in MVP v1. Recovery
after a dropped connection is: the client calls
`GET /conversations/{id}`, which reflects whatever the DB's terminal status
already is (including `streaming` if the assistant call is still genuinely
in progress server-side) — not a resumed byte stream.

## 5. `ChatProvider` injection pattern

Mirrors `EmbeddingProvider` exactly:

```python
class ChatStreamEvent(Protocol):
    ...  # delta text or finish signal, shape TBD in 3A implementation

class ChatProvider(Protocol):
    provider_name: str
    model_name: str

    def stream_chat(self, messages: list[dict], tools: list[dict] | None = None) -> Iterator[ChatStreamEvent]: ...

class OpenAIChatProvider:
    provider_name = "openai"
    def __init__(self, model: str = "gpt-4o-mini", client=None): ...
```

Same factory-seam pattern as `_build_embedding_provider()` in `main.py`, so
tests inject a fake streaming provider instead of calling OpenAI. `tools`
parameter exists in the Protocol from 3A onward (even though 3A itself
passes `None`/empty) so 3B doesn't have to change the Protocol shape later
— only start populating it.

## 6. DB connection lifecycle across the streaming gap

Directly inherits Sub-step 1's already-documented constraint
(`docs/step12_substep1_plan.md` §3 point 4). **Corrected from an earlier
draft**: that draft relied on `Depends(get_db_dependency)`'s generator
cleanup timing to guarantee the connection closes before Phase B begins.
That is not a safe assumption to build this design on — `Depends` cleanup
timing relative to a `StreamingResponse` generator's execution is an
implementation detail of FastAPI/Starlette's dependency-resolution
internals, not a guarantee this design should depend on. The streaming
message endpoint therefore does **not** use
`Depends(get_db_dependency)` at all; it manages its own connection
explicitly:

```python
@app.post("/conversations/{conversation_id}/messages")
def post_message(conversation_id: int, body: PostMessageRequest):
    with get_connection() as conn:
        # Phase A: validate conversation exists, insert_user_message,
        # create_streaming_assistant_placeholder
        conn.commit()
    # `with` block has exited here -- connection is closed and returned to
    # the pool *before* the generator/StreamingResponse is even constructed,
    # not merely "expected to be closed by the time streaming starts."

    def generate():
        # Phase B: call ChatProvider.stream_chat, yield SSE frames.
        # Any tool call (3B) opens its own short-lived
        # `with get_connection() as tool_conn:` block per call.
        # Phase C: a *fresh* `with get_connection() as conn:` opened here,
        # specifically for finalize_assistant_message, per Sub-step 1's
        # connection-lifecycle contract.
        ...

    return StreamingResponse(generate(), media_type="text/event-stream")
```

Ordinary conversation CRUD endpoints (`GET`/`PATCH`/`DELETE
/conversations...`, `GET /conversations/{id}`) are unaffected by this and
continue to use `Depends(get_db_dependency)` exactly like every other
existing route in `main.py` — this change is scoped to the one streaming
endpoint (and the regenerate endpoint in 3C, which has the same shape).

1. **Phase A** (a plain `with get_connection() as conn:` block, opened and
   closed before the generator exists): validate conversation exists,
   `insert_user_message`, `create_streaming_assistant_placeholder`, commit.
2. **Phase B** (no DB connection held, runs inside the generator): call
   `ChatProvider.stream_chat`, yield `token` SSE events to the client as
   they arrive. Optionally (3B) invoke tools mid-stream, each tool call
   opening its own short-lived `with get_connection()` block for its one
   query, closed immediately after.
3. **Phase C** (a *fresh* `with get_connection() as conn` opened
   specifically for this call, inside the generator, per the Sub-step 1
   constraint): call `finalize_assistant_message`, commit, close.

This is the concrete design that satisfies the connection-lifecycle
contract Sub-step 1 already wrote down as a hard requirement for "whoever
implements the Streaming API sub-step" — Sub-step 3A is that sub-step.

## 7. Disconnect, cancellation, and provider-failure persistence (3A scope)

**This entire section is 3A scope, not deferred to 3C** (corrected from an
earlier draft that pushed disconnect/failure persistence into 3C — that
would have let 3A merge with a known, normal-operation path that leaves a
row permanently `status='streaming'`, which is exactly the defect class
Sub-step 1's whole design was built to avoid). 3A must ship all three
paths below as its minimum-safety lifecycle. 3C's job is to *stress-test
and harden* these same paths (timing precision, load, concurrent
disconnects), not to implement the first version of them.

Three distinct failure/interruption modes, each must reach a terminal
`chat_messages` row — no row may be left `status='streaming'` forever
except across an actual process crash (handled by startup reconciliation,
section 8, and hardened further in 3C):

- **Client disconnects mid-stream** (closes tab, network drop): FastAPI/
  Starlette surfaces this as the request's `is_disconnected()` becoming
  true, or an exception when writing to the response. The streaming
  generator must catch this, stop consuming the provider stream, and still
  run Phase C with whatever partial content was accumulated so far,
  `status='aborted'`. This must happen inside a `finally`/`except`
  around the generator body, not assumed to happen automatically.
- **Provider call raises** (timeout, API error, malformed response): caught
  around the `stream_chat` iteration; Phase C runs with `status='failed'`
  and a sanitized `error_message` (see section 10 — never the raw
  exception), and a best-effort `message_failed` SSE event carrying the
  same public-facing message is written to the stream *if* the connection
  is still open enough to accept it. Phase C's DB write, not the SSE
  emission, is what actually matters here.
- **Any other unexpected exception in Phase B** (a catch-all, not just the
  two named cases above): the generator's outermost handler must be
  fail-closed — any exception that is not the specific "client
  disconnected" signal is treated as a provider/orchestration failure and
  still routes through Phase C with `status='failed'`. There is no
  "unhandled exception silently ends the generator with no DB write" path
  in 3A.
- **`finalize_assistant_message`'s rowcount must be checked.** Per its own
  docstring, it is a conditional `UPDATE ... WHERE status = 'streaming'`
  and returns rows affected (0 or 1). Phase C must inspect this return
  value; a `0` means the row was already finalized by something else (e.g.
  a race with startup reconciliation) and must not be treated as a
  successful completion of *this* call — it is logged, not silently
  ignored, since it indicates the row's terminal state was set by a
  different code path than the one that thinks it just finalized it.
- **Process crash / server restart mid-stream**: no code path in this
  request ever runs Phase C. This is not handled per-request at all — it
  is exactly what `mark_stale_streaming_messages_as_failed` plus startup
  reconciliation (section 8) is for; 3C additionally hardens the fresh-
  connection finalize path and recovery behavior around this case.

## 8. Startup reconciliation

`mark_stale_streaming_messages_as_failed` already exists
(`conversations_queries.py`) but is uncalled anywhere. Per the user's
explicit steer, this is planned as a **one-shot startup reconciliation**,
not a recurring background sweep (which Sub-step 1 already deferred and
this plan does not reopen):

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    with get_connection() as conn:
        mark_stale_streaming_messages_as_failed(conn)
        conn.commit()
    yield

app = FastAPI(lifespan=lifespan)
```

This runs exactly once, synchronously, before the app starts accepting
requests.

**Explicit single-process assumption (corrected from an earlier draft).**
An earlier draft claimed every `status='streaming'` row at startup is
*unconditionally* orphaned, with no race to guard against. That is only
true under a specific deployment assumption, which must be stated rather
than left implicit:

> **Assumption: exactly one backend process/worker.** Startup
> reconciliation, as designed here, is **not** multi-worker safe. If a
> second worker starts while a first worker is still actively streaming a
> response (e.g. a rolling deploy, or `uvicorn --workers 2`), the second
> worker's startup reconciliation would incorrectly mark the first worker's
> in-progress row as `failed` out from under it. MVP v1 runs a single
> backend process, and this plan does not attempt to make startup
> reconciliation safe beyond that. Multi-worker coordination (e.g. a
> worker-scoped claim/lease on streaming rows, or moving reconciliation to
> a separate one-time migration-style step outside of app startup) remains
> explicitly deferred, matching Sub-step 1's existing deferral of any
> recurring background sweep.

Scope boundary: this lifespan hook does only this one reconciliation call;
it is not a place to add other future startup logic without a separate,
explicit decision.

## 9. Tool-calling design (3B, ADR-002-governed)

- **Eligibility / fixed registry**: tools are a hardcoded Python list
  mapping `tool_name -> (query-layer function, typed argument schema)`,
  built directly from the functions in section 1 (`get_dataset_summary`,
  `get_dataset_timeseries`, `get_analysis_run`,
  `evaluate_battery_should_discharge_but_did_not`, `retrieve_chunks`,
  `find_similar_to_case`, `search_by_text`, etc.). The LLM selects a tool
  name and arguments (via the provider's native function-calling, not
  free-text SQL); the backend validates the tool name against this fixed
  registry and the arguments against a Pydantic schema before calling the
  underlying function. **Any tool name not in the registry is rejected
  before any DB call is made** — there is no fallback that attempts to
  interpret an unknown tool name as SQL or a dynamic query.
- **Max rounds / max calls**: propose a hard cap (e.g. 3 tool-call rounds,
  5 total tool calls per user message) enforced in the orchestration loop,
  independent of whatever limit the provider API itself might have. Exact
  numbers are a 3B implementation decision, not fixed here — this plan only
  establishes that a hard, backend-enforced cap must exist (fail closed:
  if the cap is hit, the assistant must say so in its answer rather than
  silently truncating tool use).
- **Internal Knowledge Only enforcement is more than the closed registry**
  (corrected from an earlier draft that treated the registry alone as
  sufficient). The registry only constrains *which data the LLM can
  fetch* — it does nothing to stop the LLM from answering a diagnostic/
  evidence-seeking question directly from its own general training
  knowledge without calling any tool at all, which would violate Internal
  Knowledge Only just as much as an unrestricted-SQL leak would, just
  through a different mechanism. 3B must additionally implement:
  - **A deterministic capability guard**, independent of the registry:
    a server-side classification of whether the current user message is a
    diagnostic/evidence-seeking request (as opposed to a purely
    conversational one — e.g. "why did battery 12 not discharge" vs. "what
    does SOC stand for"). This classification decides tool *eligibility*,
    not just tool *validity*.
  - **Server-side enforcement, not LLM discretion**: for a message
    classified as diagnostic/evidence-seeking, the backend requires at
    least one successful tool call before the answer is allowed to present
    itself as evidence-backed. If the LLM produces zero tool calls for such
    a message, the backend does not simply forward whatever text the LLM
    generated — it fails closed into an explicit "insufficient data,
    specify what dataset/document/case this concerns" response (matching
    the Confidence rule's own "insufficient data" language in
    MVP1_RULES.md §8), rather than accepting a fabricated-sounding
    zero-citation answer to a diagnostic question.
  - **General background knowledge is clearly labeled, and is a ceiling,
    not a support**: the LLM may still add general engineering background
    (§8's "General engineering background" field exists precisely for
    this), but general knowledge must never be used to *support* Evidence,
    Possible causes, Confidence, or Citations for this specific case — only
    to explain concepts generally. This is a content-shape rule 3B must
    validate/enforce in the response-construction step, not merely
    instruct the LLM to follow via prompt and hope for compliance.
  - **The registry remains necessary** (every tool call the LLM does make
    is still validated against the closed, fixed set — nothing here
    relaxes that), it is just not *sufficient* on its own for Internal
    Knowledge Only.
- **Deferred capability guard (external search toggle)**: per
  `.claude/rules/frontend/react.md`, the frontend's internal/external
  toggle must remain UI-only and disabled. On the backend side, this plan
  proposes a deterministic guard: if a request ever arrives with an
  external-mode flag set (defensive coding against a future or malicious
  client, not an expected code path today), the backend must reject it
  with a clear 4xx rather than silently ignoring the flag or attempting any
  real external call — "reject and say why," not "silently downgrade."
- **Seven-part response structure (MVP1_RULES.md §8) applicability is
  decided by request intent/analysis type, not merely by whether a tool
  call happened to occur** (corrected from an earlier draft that branched
  on "did a tool call happen" alone). Using tool-call-occurrence as the
  sole signal is backwards: it lets the LLM sidestep the seven-part
  structure simply by not calling a tool for a question that should have
  required one (which is exactly the failure mode the new capability guard
  above exists to prevent), and conversely could force the full structure
  onto an incidental tool call that isn't actually the basis of a
  diagnostic claim. The two decisions are related but distinct: the
  capability guard above decides *whether a tool call is required at all*
  for this message; **this** decision — driven by the same server-side
  classification of the request as diagnostic/evidence-seeking vs.
  conversational — decides *whether the seven-part structure applies* to
  the resulting answer. In practice: a message classified as diagnostic/
  evidence-seeking always renders through the seven-part structure (either
  with real tool-call-backed evidence, or as the capability guard's
  explicit "insufficient data" response, itself expressed in the same
  structure with Evidence/Citations stating what's missing); a message
  classified as purely conversational renders as a plain response. 3B must
  implement this as an explicit, server-side branch on the classification,
  not leave the choice to the LLM's discretion.

## 10. Public error vs. internal log separation

**Three separate representations, not two** (corrected from an earlier
draft that proposed storing the actual exception detail in
`chat_messages.error_message` and only sanitizing at the SSE layer — that
would persist provider payloads, SQL error text, or potentially document/
prompt content into the database indefinitely, which conflicts with this
project's existing security posture around not leaking internal detail
outward, and a DB row is a far more durable, more widely-read artifact than
a single log line):

- **`chat_messages.error_message` (DB column)**: a small, stable, enum-like
  sanitized code/short message, e.g. `provider_timeout`, `provider_error`,
  `stream_cancelled`, `persistence_failed`. Never the raw
  `str(exception)`, never a stack trace, never provider response payloads.
  This is what `GET /conversations/{id}` returns to the client and what any
  future analytics/debugging query over `chat_messages` reads — it must be
  safe to display and safe to retain long-term.
- **SSE `message_failed` `error` field / HTTP error body**: a public-safe,
  human-readable message derived from the same sanitized code (e.g.
  `provider_timeout` → `"assistant response failed, please try again"`).
  May be a small lookup keyed by the DB code above rather than an
  independent set of strings, so the two stay in sync by construction
  rather than by convention.
- **Server log (not persisted in the DB at all)**: the actual exception
  detail, stack trace, and any provider error payload, written to
  application logs only, for operator debugging. This is the *only* place
  the raw detail is allowed to exist.

This mirrors the existing known-limitation flagged in `PROGRESS.md` about
`error.tsx` leaking backend URLs — Sub-step 3 should not introduce a new
instance of the same class of leak, and should not create a second,
DB-persisted instance of it either.

## 11. Timeouts and sync provider blocking

`OpenAIEmbeddingProvider.embed_batch` today blocks synchronously with
`time.sleep` retries — acceptable for a background task, but a chat
endpoint under FastAPI's async request handling must not block the event
loop the same way. Two options to evaluate in 3A implementation (not
decided here): (a) run the provider's blocking streaming call in a thread
via `run_in_threadpool`/`anyio.to_thread`, matching FastAPI's own
recommended pattern for sync-blocking work inside async routes, or (b) use
the OpenAI SDK's async client directly. Either way, a request-level timeout
(the whole Phase B) must exist so a hung provider call cannot hold a
streaming response (and, if held open, an SSE connection) open forever;
timing out must route through the same "provider call raises" path in
section 7, ending in `status='failed'`.

## 12. Test strategy and sub-step boundaries

- **3A** (must cover the full minimum-safety lifecycle from section 7, not
  just the happy path — corrected from an earlier draft that left
  disconnect/failure testing to 3C): fake-connection unit tests for the new
  endpoint request/response shapes (matching `test_cases_api.py`'s existing
  pattern), a fake `ChatProvider` that yields deterministic token events
  for SSE contract tests, explicit tests for each of the four paths in
  section 7 (successful completion, provider-raises → `failed`, simulated
  client disconnect → `aborted`, catch-all unexpected exception → `failed`,
  and a `finalize_assistant_message` rowcount-already-zero case), and a
  real-DB integration test proving the Phase A → B → C connection lifecycle
  actually opens/closes distinct connections (not just asserted by code
  review) — mirroring how Sub-step 1's `FOR UPDATE` locking claim was
  proven with `test_conversations_queries_integration.py` rather than
  trusted from unit tests alone.
- **3B**: fake-connection tests per tool (valid args, invalid/unknown tool
  name rejection, max-round-cap enforcement), tests for the deterministic
  capability guard (diagnostic-intent message with zero tool calls →
  forced "insufficient data" response, conversational-intent message → no
  guard triggered), a test that general-background content never leaks
  into Evidence/Citations construction, plus at least one real-DB or
  real-provider-adjacent test that a genuine tool call round-trips through
  a real query-layer function (not just a mocked return value) — matching
  the project's established pattern of pairing fake-connection tests with
  one real-database check for anything the fakes can't structurally prove.
- **3C** (hardening/stress-testing what 3A already delivers, not first
  implementation of it): extends the existing regenerate concurrency test
  pattern (`test_conversations_queries_integration.py`) up to the API
  layer, load/timing-precision tests for the timeout path, concurrent-
  disconnect stress tests, and a startup-reconciliation test that seeds a
  `streaming` row directly, boots the app (or calls the lifespan function
  directly in a test), and asserts it flips to `failed` — plus an explicit
  test/assertion documenting the single-process assumption from section 8
  (e.g. a test that two concurrent reconciliation calls against the same
  row are idempotent, since that is the one multi-process interaction this
  plan does still consider in-scope to verify, short of true multi-worker
  coordination).
- Full-repo `pytest` must stay green across every incremental commit within
  each of 3A/3B/3C, matching the existing per-sub-step convention (Sub-step
  1 kept `pytest` green through the migration; Sub-step 2 was frontend-only
  and left `pytest` untouched).

## Explicitly out of scope for this planning document

No code, schema, or migration changes. No package installs. No PROGRESS.md
update (already done in the prior docs-only PR #40). No decision is made
here about the exact tool-call round/cap numbers, the exact SSE
reconnection story, or the exact public error string set — those are 3A/3B
implementation-time decisions within the boundaries this document sets.
