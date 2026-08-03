# Step 12 Sub-step 3B — Analysis and Implementation Plan (Controlled Tool Orchestration, Internal Knowledge Only, Seven-Part Answer)

> Builds directly on Sub-step 3A (Slices 1–4, all merged to
> `feature/step12-streaming-api`: `ChatProvider`, conversation CRUD, message
> read model, SSE streaming with the minimum-safety lifecycle). Scoped per
> `docs/step12_substep3_plan.md` §9 (already approved: closed tool registry
> + deterministic capability guard + seven-part structure), resolving the
> concrete implementation decisions that document deliberately left open.
>
> **Decisions confirmed and implemented (this revision)**: Option A for the
> seven-part structure (free-text Markdown headings, natural token
> streaming preserved, deterministic post-hoc validation only — no
> structured-JSON output, no retry-to-fix-format); closed registry +
> deterministic capability guard with 3 rounds / 5 total tool calls;
> conversation history capped at 20 completed messages plus a total
> character cap, chronological order preserved; role_mode reuses the
> existing 4 enum values and only affects tone/depth, never tool
> eligibility or evidence rules; tool/citation persistence via a new
> `record_tool_activity` query primitive, `finalize_assistant_message`
> unchanged; the `chat_provider.py` tool-call parsing gap is fixed. Sections
> below are updated in place to describe the implemented design, not a
> proposal awaiting confirmation.
>
> **Post-implementation review fix (Internal Knowledge Only gap)**: the
> first implementation streamed every orchestration round's content live,
> token-by-token, before it was known whether that round would end up
> discarded by a tool call, the capability guard, or the round/call cap --
> meaning the client could see model text the DB never ends up persisting,
> including ungrounded text with no tool-call evidence behind it. Fixed by
> splitting `generate()` into two strictly separate phases: **Phase 1**
> (tool orchestration rounds, `tools=TOOL_SCHEMAS`) buffers every round's
> content locally and never yields it as a `token` SSE frame; a round's
> buffered text is unconditionally discarded once the round ends, whether
> it led to a tool call, the capability-guard rejection, or the cap.
> **Phase 2** (final synthesis, `tools=None`) is the only place `token`
> frames are ever emitted from live provider output, and is only reached
> once orchestration ends in a genuinely trustworthy state (a round
> naturally stopped requesting no further tool call, and the capability
> guard does not reject it) -- so the exact text streamed to the client is
> always exactly what gets persisted. The two backend-authored fallback
> answers (capability-guard rejection, cap exceeded) skip Phase 2 entirely
> and stream their fixed string directly, which is byte-for-byte identical
> to what gets persisted by construction. One accepted cost: a
> conversational message that needs no tool at all now costs 2 model calls
> instead of 1 (one discarded orchestration round, one synthesis round) --
> traded deliberately for the stronger guarantee that no ungrounded model
> text can ever reach the client before the DB decides to keep it.

## 0. What 3A already gives this slice to build on

- `generate()` (`backend/app/main.py`) already has exactly one loop
  consuming `ChatProvider.stream_chat(messages, tools=None)` and one
  finalize call site. 3B's job is to turn `tools=None` into a real
  registry and extend the loop into a multi-round orchestration loop, not
  to redesign the minimum-safety lifecycle itself (terminal-state handling,
  timeouts, disconnect detection all carry over unchanged).
- `_build_provider_messages(prior_messages, user_content, role_mode)`
  already exists but only emits a single placeholder system message
  (`f"Respond in {role_mode} mode."`) — this is the extension point for
  role_mode framing (section 3) and conversation history assembly
  (section 4).
- **A real gap found while re-reading `chat_provider.py` for this
  analysis**: `OpenAIChatProvider.stream_chat` already accepts and forwards
  a `tools` parameter to the OpenAI API call, but its response-parsing loop
  only ever reads `choice.delta.content` — it never reads
  `choice.delta.tool_calls` at all. If 3B passed a real tool registry
  through today, any tool-call response from the model would be **silently
  dropped** (no exception, just no tool-call information surfaced) because
  nothing in the current parsing loop looks at that field. This is not a
  design choice to preserve; `chat_provider.py` needs a new event type and
  parsing branch (section 7) before tool-calling can work at all.
- `chat_messages.citations` (JSONB) and `chat_messages.tool_calls` (JSONB)
  columns already exist in the schema (Sub-step 1), unused until now — 3B
  is the first slice that has data to put in them.

## 1. Internal Knowledge Only guard

Two independent mechanisms, matching the overall plan's already-approved
correction (registry alone is necessary but not sufficient):

- **Closed fixed tool registry** (new file, `backend/app/services/tool_registry.py`):
  a hardcoded list of tool definitions, each pairing an OpenAI
  function-calling JSON schema with the existing query-layer function it
  invokes:

  | Tool name | Wraps | Args |
  |---|---|---|
  | `get_dataset_summary` | `datasets_queries.get_dataset_summary` | `dataset_id: int` |
  | `get_dataset_timeseries` | `datasets_queries.get_dataset_timeseries` | `dataset_id: int, limit: int, offset: int` |
  | `get_dataset_analysis` | `datasets_queries.get_analysis_run` + `rule_engine.evaluate_battery_should_discharge_but_did_not` | `dataset_id: int` |
  | `search_documents` | `services.retrieval.retrieve_chunks` | `query_text: str, document_id: int \| None, top_k: int` |
  | `search_similar_cases` | `services.case_retrieval.search_by_text` | `query_text: str, event_type: str \| None, tags: str \| None, top_k: int` |

  Any tool name the model returns that is not one of these five is
  rejected **before any DB call** — logged, and reported back to the model
  as a tool error result (`"unknown tool"`) rather than silently ignored,
  so the model can recover within the same round instead of the request
  failing outright.
- **Deterministic capability guard, independent of the registry** — this
  is the piece the registry alone cannot provide (a model can choose not
  to call any tool and answer from general knowledge instead). **Concrete
  algorithm proposed for this slice** (flagged for your confirmation, not
  assumed — see "Open decisions" section 10): a keyword-based classifier,
  `_looks_like_diagnostic_question(content: str) -> bool` — case-insensitive
  substring match against a fixed domain-term list covering both Chinese
  and English (`電池`/`battery`, `異常`/`anomaly`, `排程`/`schedule`,
  `SOC`, `dataset`/`資料集`, `案件`/`case`, `文件`/`document`, `成本`/`cost`,
  `綠能`/`green`, `contract`/`契約容量`, etc.). This is a blunt heuristic,
  not an NLP intent classifier — it will have false positives (routed
  through the stricter path unnecessarily, which is safe, just possibly
  overly cautious) and false negatives (a diagnostic question phrased with
  none of the listed terms would slip through as "conversational" and skip
  the guard). This tradeoff is accepted for MVP scope but must be stated
  as a known limitation, not hidden.
- **Enforcement**: if `_looks_like_diagnostic_question(content)` is `True`
  and the model's first-round response contains **zero** tool calls, the
  backend does not forward that response as the final answer. It
  discards it and finalizes with a fixed "insufficient data" seven-part
  answer (section 2) instead — this is a genuinely different code path
  from a normal completion, not a retry, matching MVP1_RULES.md §8's
  "insufficient data" principle.
- **Max rounds / max calls** (concrete numbers, committed here, not left
  as "TBD" per the overall plan's instruction not to leave placeholders):
  **3 tool-call rounds, 5 total tool calls** per user message. If the cap
  is hit before the model produces a final non-tool-call answer, the
  backend stops the loop and finalizes with the seven-part structure's
  Confidence field forced to state the cap was hit and answer accordingly
  (not a silent truncation).

## 2. Seven-part answer structure — structured output, not free-text-plus-validation

**This is the single biggest open design fork in this slice; flagged
explicitly for your decision before implementation** (see section 10)
rather than silently picked. Two real options exist:

- **Option A — Free-text with post-hoc validation**: system prompt
  instructs the model to emit the seven sections as labeled free text
  (matching the exact labels in MVP1_RULES.md §8's example); backend does
  a best-effort string check (are the 7 labels present in order?) and logs
  a warning if not, but still streams whatever the model produced. Pro:
  trivially compatible with today's token-by-token SSE streaming (no
  change to `generate()`'s streaming shape). Con: no real enforcement —
  compliance is prompt-only, and MVP1_RULES.md §8's strict requirements
  (general background never blended into Confirmed facts, citations
  correctly typed) are exactly the kind of thing free-text compliance is
  weakest at.
- **Option B — Structured output (OpenAI JSON-schema/structured-output
  mode)**: the model is constrained to emit a JSON object matching a
  Pydantic `SevenPartAnswer` schema (`confirmed_facts`, `evidence`,
  `possible_causes`, `general_background`, `suggested_actions`,
  `confidence`, `citations`) as its final (non-tool-call) response. Pro:
  structurally guarantees every field exists and citations are typed data
  (not embedded prose), which is what actually lets the backend separate
  "general background" from "evidence" mechanically rather than trusting
  the model's formatting. Con: **breaks today's token-by-token `token` SSE
  event** as currently defined — a JSON object under structured-output
  mode is not meaningfully streamable field-by-field with the current
  event shape; this would require either (a) not streaming this final
  answer at all (wait for the complete JSON object, then emit it as one
  event or re-render it as formatted text and chunk that for display), or
  (b) a new SSE event shape (e.g. per-field `answer_field` events) that
  changes the client contract established in 3A.

**Recommendation (not yet a decision — needs your confirmation)**: Option
B for correctness, accepting that the `token` SSE event's granularity
changes specifically for tool-call-backed diagnostic answers (still
streamed as they arrive for the *tool-call/reasoning* phase, but the final
structured answer arrives as a small number of larger chunks or one
complete block rather than word-by-word). Plain conversational answers
(capability guard says no tool call required) are unaffected and keep
today's exact token-by-token streaming, since they don't go through
structured output at all.

## 3. `role_mode` → system prompt framing

**No existing product-level definition of what the four modes should
actually change about tone/depth exists anywhere in the docs** —
`docs/DEVELOPMENT_WORKFLOW.md`'s Step 12 section only names the four modes
(Operator/Engineer/Executive/Training Mode) with no further specification.
This is a real content gap, not something this plan can respond to with
existing project decisions. **Proposed concrete framing** (flagged for
confirmation, section 10):

| `role_mode` | Framing added to the system prompt |
|---|---|
| `operator` | Prioritize concrete, actionable next steps; minimize jargon; assume no deep EMS/battery engineering background. |
| `engineer` | Full technical detail is expected; use precise terminology (SOC, C-rate, BMS protection logic) without simplification. |
| `executive` | Lead with business/operational impact and risk framing; keep technical detail available but secondary; avoid unexplained jargon. |
| `training` | Explain underlying concepts and reasoning in more depth than an operator/engineer answer would normally include, even at the cost of length — this mode is explicitly for learning, not fast lookup. |
| `None` (unset) | No mode-specific framing added — behavior identical to today's placeholder. |

This only changes prompt wording, not which sections/fields are required —
the seven-part structure (section 2) applies uniformly across all four
modes whenever the capability guard says it should.

## 4. Conversation history assembly

Today, `_build_provider_messages` includes **all** `prior_messages` with no
cap. This slice adds tool-call/tool-result messages into that same history
(section 7), which grows message count faster per turn than before.
**Proposed concrete decision**: cap history to the last **20 messages**
(a fixed count, not a token budget — token-based truncation is a
meaningfully bigger feature involving a tokenizer dependency, out of scope
for this slice), oldest-first messages beyond that cutoff dropped. This
is a hardcoded constant (matching `MAX_ANALYSIS_ROWS`/timeout constants'
existing convention in `main.py`), not user-configurable in 3B. Flagged as
a proposed default, not an already-settled number, since no prior decision
fixed one.

## 5. Document retrieval and case retrieval wiring

Both `services.retrieval.retrieve_chunks` and `services.case_retrieval.search_by_text`
are registered as tools (section 1's table) exactly as
`docs/step12_substep3_plan.md` anticipated (`retrieve_chunks`'s own
docstring already says "meant to be called directly by a future Step 12
tool-calling layer"). Each tool call opens its own short-lived
`with get_connection() as conn:` block (per `docs/step12_substep3_plan.md`
§6 Phase B point — tool calls do not reuse Phase A's already-closed
connection), calls the underlying function, and returns a JSON-serializable
result to the model as the tool's return content.

- `search_documents` calls `retrieve_chunks(conn, query_text, embedding_provider=_build_embedding_provider(), document_id=..., top_k=...)`
  — reuses the **existing** `_build_embedding_provider()` factory seam
  already in `main.py` (Step 10/11), not a new one.
- `search_similar_cases` calls `search_by_text(conn, _build_embedding_provider(), query_text, event_type=..., tags=..., top_k=...)`.

## 6. Citations / evidence metadata: model-facing vs. frontend-facing vs. persisted

Three different shapes of the same underlying tool result, deliberately
different from each other (matching the existing "summary is short and
non-sensitive, never a raw row dump" principle already stated in
`docs/step12_substep3_plan.md` §4):

- **To the model** (as the tool result message content): a compact JSON
  object with the fields the model needs to reason and cite correctly —
  e.g. for `search_documents`: `[{"file_name": ..., "pdf_page_number_start": ..., "chunk_id": ..., "content": <truncated excerpt>}, ...]`;
  for `search_similar_cases`: `[{"case_id": ..., "event_type": ..., "semantic_score": ..., "matches": [...], "differs": [...]}, ...]`.
  Full chunk `content`/case symptom text is included here (the model needs
  the actual text to reason over), but never the raw embedding vector.
- **To the frontend** (`tool_result` SSE event payload): per
  `docs/step12_substep3_plan.md` §4, a short human-readable `summary`
  string (e.g. `"found 3 matching document excerpts"`), **not** the full
  JSON blob sent to the model — the frontend only needs enough to render
  a transient "checking documents…" indicator, not the underlying data
  (which arrives properly structured in the final answer's `citations`
  field once the answer completes).
- **Persisted** (`chat_messages.citations` JSONB, `chat_messages.tool_calls`
  JSONB — both columns already exist, unused since Sub-step 1): `tool_calls`
  stores the tool name + arguments + a reference to which tool-result rows
  were returned (for audit/debugging); `citations` stores the final
  structured `citations` array from the `SevenPartAnswer` (section 2,
  Option B) or the free-text citations section (Option A) as parsed JSON.
  **This surfaces the same kind of open item Sub-step 1/3A already hit
  once before ("does an existing function's signature need a new
  parameter")**: `finalize_assistant_message`'s current signature has no
  `citations`/`tool_calls` parameters. Two options, structurally identical
  to the earlier provider/model resolution decision:
  1. Add `citations: Optional[dict]` and `tool_calls: Optional[dict]`
     parameters to `finalize_assistant_message` (a real signature change
     to a Sub-step 1 function, the first one since Sub-step 1 shipped).
  2. Add a small separate `record_tool_activity(conn, message_id, tool_calls, citations)`
     query function called once, right after `finalize_assistant_message`,
     within the same Phase C connection/transaction.
  **Proposed default: option 2** (a new, narrowly-scoped function,
  consistent with the precedent set by the provider/model decision, which
  chose "add a new call" over "change an existing function's contract").
  Flagged for confirmation in section 10, not assumed final.

## 7. `tool_call` / `tool_result` SSE events and `ChatProvider` extension

**`chat_provider.py` needs a new event type and parsing branch — this is
required work, not optional polish**, per the gap identified in section 0:

```python
@dataclass(frozen=True)
class ChatToolCallEvent:
    tool_call_id: str
    name: str
    arguments_delta: str  # raw partial JSON string fragment, as OpenAI streams it
```

`OpenAIChatProvider.stream_chat`'s parsing loop gains a branch reading
`choice.delta.tool_calls` (a list of partial tool-call deltas, each
carrying an `index`, optionally `id`/`function.name` on the first delta
for that index, and `function.arguments` as a partial JSON string
fragment on every delta) and yields one `ChatToolCallEvent` per fragment.
**`ChatProvider` still does not know anything about SSE** — it yields
typed events only; assembling the final tool-call name+complete-arguments
JSON and emitting `tool_call`/`tool_result` SSE frames is entirely
`generate()`'s (i.e., `main.py`'s) responsibility, preserving the layering
principle already established and explicitly called out for preservation
in the Slice 1 review.

`generate()`'s loop becomes a **multi-round** loop (was single-round in
3A): accumulate `ChatToolCallEvent` argument fragments by `tool_call_id`
until a round's `ChatFinishEvent.finish_reason == "tool_calls"` signals the
round is complete; execute each accumulated tool call against the registry
(section 1); emit `tool_call` (`{"tool_name":..., "arguments":...}`) then
`tool_result` (`{"tool_name":..., "summary":...}`) SSE frames per call;
append a `{"role": "tool", "tool_call_id":..., "content": <JSON result>}`
message to the conversation for the next round; call `stream_chat` again
with the updated message list; repeat up to the max-rounds cap (section 1).
The existing terminal-state handling (timeout/disconnect/error → finalize)
wraps the **entire** multi-round loop, not just one round — a timeout or
disconnect mid-tool-call-round still finalizes exactly the same way 3A
already does.

## 8. Provider abstraction changes summary

- New `ChatToolCallEvent` (section 7).
- `stream_chat`'s existing `tools` parameter finally gets real content
  passed through (today always `None`) — no signature change needed
  there, `tools: list[dict] | None` already accepts the registry's JSON
  schemas as-is.
- No change to `ChatProviderError`/`ChatProviderTimeout`/`ChatProviderAPIError`
  — tool-call execution failures (e.g. an underlying query-layer function
  raising) are caught and reported back to the model as a tool result
  error string, not raised as a `ChatProviderError` (a tool failing is not
  the same class of problem as the LLM API itself failing).

## 9. Test strategy and files

### New files

- `backend/app/services/tool_registry.py` — tool definitions + a single
  `execute_tool(conn, tool_name, arguments) -> dict` dispatch function that
  validates `tool_name` against the closed registry first.
- `backend/app/services/answer_classifier.py` — `_looks_like_diagnostic_question`
  (or wherever this ends up living; a small, standalone, easily-unit-tested
  module either way).
- `backend/tests/test_tool_registry.py` — valid-args happy path per tool
  (against real query-layer functions + fake connections, matching the
  existing per-function fake-connection convention), unknown-tool-name
  rejection, invalid-argument-shape rejection.
- `backend/tests/test_answer_classifier.py` — a table of representative
  diagnostic vs. conversational messages (Chinese and English) asserting
  the expected classification, explicitly including at least one
  documented false-negative example as a known-limitation regression test
  (so the heuristic's actual boundary is visible in the test suite, not
  hidden).
- `backend/tests/test_chat_streaming_tool_orchestration.py` — extends the
  `test_chat_streaming.py` fake-provider pattern to multi-round scripted
  responses: one tool-call round followed by a final answer; the
  max-rounds-cap path; an unknown-tool-name response from the model;
  a capability-guard-triggered "insufficient data" path (diagnostic-classified
  message, model's first round has no tool calls).

### Modified files

- `backend/app/services/chat_provider.py` — `ChatToolCallEvent`, delta
  parsing branch (section 7).
- `backend/app/main.py` — `generate()`'s loop becomes multi-round;
  `_build_provider_messages` gains role_mode framing (section 3) and
  history capping (section 4).
- `backend/app/conversations_queries.py` — one new `record_tool_activity`
  function (no changes to any of the 10 existing functions).

## 10. Decisions (confirmed and implemented)

Restated as the final, implemented design — not proposals:

1. **Seven-part answer: Option A.** Free-text Markdown headings
   (`SEVEN_PART_HEADINGS` in `main.py`), streamed token-by-token exactly
   like 3A. `_validate_seven_part_structure` runs once after the final
   answer is assembled and only `log.warning`s on a missing heading — it
   never triggers a second model call to "fix" the format.
2. **Capability guard**: the keyword heuristic in section 1
   (`answer_classifier.py`) ships as the MVP first version, explicitly
   documented (in its own docstring and in `test_answer_classifier.py`'s
   known-false-negative test) as a conservative heuristic, not a security
   guarantee.
3. **role_mode framing**: section 3's table is the implemented wording,
   reusing the existing 4 `RoleMode` values with no new mode added; it is
   injected into the system prompt string only and never read anywhere in
   the tool-eligibility, capability-guard, or registry-enforcement code
   paths.
4. **History cap**: `CONVERSATION_HISTORY_MAX_MESSAGES = 20` plus
   `CONVERSATION_HISTORY_MAX_TOTAL_CHARS = 8000`, applied in that order
   (message-count window first, then oldest-first character trimming),
   filtered to `status='completed'` messages only, chronological order
   preserved throughout.
5. **Citations/tool_calls persistence**: `record_tool_activity(conn,
   message_id, tool_calls, citations)` (new function,
   `conversations_queries.py`), called from `_finalize_with_fallback`
   inside the same fresh connection and same two-attempt retry loop as
   `finalize_assistant_message` — no change to that function's signature.
   `citations` is derived from the tool_call_log's successful entries
   (`{"tool_name":..., "summary":...}`), not parsed from the model's
   free-text Citations section — Option A doesn't produce structured
   citation data on its own, and parsing markdown to extract it was judged
   not worth the fragility for MVP.

## Explicitly out of scope for this slice

Regenerate endpoint, startup reconciliation wiring, frontend changes,
schema/migration changes beyond section 6's query-layer addition (no new
columns — `citations`/`tool_calls` JSONB columns already exist),
new package installs, `PROGRESS.md` updates,
Codex calls, `AGENTS.md`, `worktrees/`, `runpane`.
