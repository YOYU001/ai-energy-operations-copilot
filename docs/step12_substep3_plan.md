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

- **3A is pure plumbing**: conversation CRUD endpoints, a `ChatProvider`
  abstraction with no tool-calling, and the SSE streaming lifecycle
  (connect → stream tokens → finalize). This is testable in isolation with
  a fake `ChatProvider` and has no dependency on the Internal Knowledge
  Only rules or tool orchestration at all.
- **3B is the ADR-002 / MVP1_RULES §8-governed layer**: turning the fixed
  query-layer functions listed in section 1 into a bounded tool registry,
  wiring Internal Knowledge Only enforcement, and producing the seven-part
  response structure. This has real product-rule content (confidence
  thresholds, citation typing, disabled external-search guard) that
  deserves its own focused review, separate from the streaming plumbing.
- **3C is hardening**: `create_regenerate_attempt` wiring at the API layer,
  startup reconciliation lifespan wiring, and the disconnect/cancellation/
  provider-failure persistence paths. This depends on 3A's SSE lifecycle
  already existing and is the natural place to stress-test it.

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
  "content": "為什麼 12 號電池今天沒有依排程放電？",
  "role_mode": "engineer"
}
```

`role_mode` here is a per-message override; if omitted, falls back to the
conversation's stored `role_mode`. This endpoint's *response* is not JSON —
see the SSE contract below.

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

Exactly one of `message_completed` / `message_failed` terminates every
stream. The client's reconnection story (browser `EventSource` reconnect
semantics, `Last-Event-ID`) is explicitly **not** designed in this document
— MVP v1 treats a dropped SSE connection as equivalent to a client
disconnect (section 6), with the conversation history endpoint
(`GET /conversations/{id}`) as the recovery path (client re-fetches and
sees whatever got persisted), not a resumable stream.

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
(`docs/step12_substep1_plan.md` §3 point 4): the request-scoped
`Depends(get_db_dependency)` connection is used only for the pre-stream
steps (`insert_user_message`, `create_streaming_assistant_placeholder`,
committed before streaming begins) and is **not** held open during the
provider call. Proposed lifecycle for `POST /conversations/{id}/messages`:

1. **Phase A** (request-scoped `conn`): validate conversation exists,
   `insert_user_message`, `create_streaming_assistant_placeholder`, commit,
   close this connection (end of `Depends` scope — FastAPI does this
   automatically once phase A's synchronous work returns control).
2. **Phase B** (no DB connection held): call `ChatProvider.stream_chat`,
   yield `token` SSE events to the client as they arrive. Optionally
   (3B) invoke tools mid-stream, each tool call opening its own short-lived
   `with get_connection()` block for its one query, closed immediately
   after.
3. **Phase C** (a *fresh* `with get_connection() as conn` opened
   specifically for this call, per the Sub-step 1 constraint): call
   `finalize_assistant_message`, commit, close.

This is the concrete design that satisfies the connection-lifecycle
contract Sub-step 1 already wrote down as a hard requirement for "whoever
implements the Streaming API sub-step" — Sub-step 3A is that sub-step.

## 7. Disconnect, cancellation, and provider-failure persistence

Three distinct failure/interruption modes, each must reach a terminal
`chat_messages` row — no row may be left `status='streaming'` forever
except across an actual process crash (handled by startup reconciliation,
section 8):

- **Client disconnects mid-stream** (closes tab, network drop): FastAPI/
  Starlette surfaces this as the request's `is_disconnected()` becoming
  true, or an exception when writing to the response. The streaming
  generator must catch this, stop consuming the provider stream, and still
  run Phase C with whatever partial content was accumulated so far,
  `status='aborted'`. This must happen inside a `finally`/`except`
  around the generator body, not assumed to happen automatically.
- **Provider call raises** (timeout, API error, malformed response): caught
  around the `stream_chat` iteration; Phase C runs with `status='failed'`,
  `error_message` set to a sanitized internal-safe string, and a
  `message_failed` SSE event is emitted with the same public-facing message
  (section 10) before the stream closes — *if* the connection is still
  open enough to write; if not, this degrades to the same handling as
  client disconnect above (best-effort SSE emission, but Phase C's DB write
  is the actual source of truth).
- **Process crash / server restart mid-stream**: no code path in this
  request ever runs Phase C. This is not handled per-request at all — it
  is exactly what `mark_stale_streaming_messages_as_failed` plus startup
  reconciliation (section 8) is for.

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
requests — every `status='streaming'` row present at that moment is by
definition orphaned by a prior crash (nothing else can leave a row in that
state while the new process was not yet running), so there is no race to
guard against here, unlike Sub-step 1's `chat_messages` migration guard.
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
- **Internal Knowledge Only enforcement**: the tool registry itself *is*
  the enforcement mechanism — since every tool maps to an existing,
  already-scoped query-layer function (datasets/documents/cases/rules), the
  LLM structurally cannot reach anything outside those four internal
  sources. No separate runtime "check if this is internal" filter is
  needed beyond keeping the registry closed.
- **Deferred capability guard (external search toggle)**: per
  `.claude/rules/frontend/react.md`, the frontend's internal/external
  toggle must remain UI-only and disabled. On the backend side, this plan
  proposes a deterministic guard: if a request ever arrives with an
  external-mode flag set (defensive coding against a future or malicious
  client, not an expected code path today), the backend must reject it
  with a clear 4xx rather than silently ignoring the flag or attempting any
  real external call — "reject and say why," not "silently downgrade."
- **Seven-part response structure (MVP1_RULES.md §8) applicability**: the
  seven-part structure applies specifically when the assistant is
  "explaining diagnosis results, similar-case matches, or document-based
  evidence" (the exact language in §8) — i.e. whenever at least one tool
  call actually happened and produced evidence to cite. A purely
  conversational reply with no tool call (e.g. clarifying a question, or
  restating something already in the conversation) is not required to be
  forced into all seven sections; forcing empty "Evidence:"/"Citations:"
  sections onto an answer with nothing to cite would itself violate the
  "insufficient data" principle in §8's Confidence rule. 3B must implement
  this as an explicit branch (tool-call-backed answer → full seven-part
  structure; no-tool-call answer → plain response), not leave it to the
  LLM's discretion.

## 10. Public error vs. internal log separation

`message_failed`'s `error` field and `chat_messages.error_message` are
**not necessarily the same string**. Proposed convention: `error_message`
(DB column, already exists from Sub-step 1) stores the actual exception
detail for operator debugging; the SSE `error` field and any HTTP error
body use a small fixed set of public-safe strings (e.g. `"assistant
response failed, please try again"`, `"request was cancelled"`) chosen by
exception type, never the raw provider exception text or stack trace. This
mirrors the existing known-limitation flagged in `PROGRESS.md` about
`error.tsx` leaking backend URLs — Sub-step 3 should not introduce a new
instance of the same class of leak in the chat path.

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

- **3A**: fake-connection unit tests for the new endpoint request/response
  shapes (matching `test_cases_api.py`'s existing pattern), a fake
  `ChatProvider` that yields deterministic token events for SSE contract
  tests, and a real-DB integration test proving the Phase A → B → C
  connection lifecycle actually opens/closes distinct connections (not
  just asserted by code review) — mirroring how Sub-step 1's `FOR UPDATE`
  locking claim was proven with `test_conversations_queries_integration.py`
  rather than trusted from unit tests alone.
- **3B**: fake-connection tests per tool (valid args, invalid/unknown tool
  name rejection, max-round-cap enforcement), plus at least one real-DB or
  real-provider-adjacent test that a genuine tool call round-trips through
  a real query-layer function (not just a mocked return value) — matching
  the project's established pattern of pairing fake-connection tests with
  one real-database check for anything the fakes can't structurally prove.
- **3C**: extends the existing regenerate concurrency test pattern
  (`test_conversations_queries_integration.py`) up to the API layer, plus
  explicit tests for the disconnect/timeout/provider-failure paths in
  section 7 and a startup-reconciliation test that seeds a `streaming` row
  directly, boots the app (or calls the lifespan function directly in a
  test), and asserts it flips to `failed`.
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
