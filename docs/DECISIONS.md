# Technical Decisions

> 用途：記錄會影響架構、資料、成本、安全或後續維護的重要技術決策。  
> 原則：只記需要長期追蹤的決策；一般進度放 `PROGRESS.md`。

---

## Decision Index

| ID | Date | Decision | Status |
|---|---|---|---|
| ADR-001 | 2026-07-11 | Enum validation (ems_mode, equipment_status) lives in the application layer, not as a database CHECK constraint | Accepted |
| ADR-002 | 2026-07-14 | Structured data queries use controlled tool-calling, not unrestricted Text-to-SQL | Accepted |
| ADR-003 | 2026-07-14 | OCR is a required MVP capability, with a tiered scope (must-do / can-simplify / later) | Accepted |
| ADR-004 | 2026-07-14 | Embedding/LLM provider must be replaceable; config centralized; model/version recorded in metadata | Accepted |
| ADR-005 | 2026-07-14 | Data lifecycle: prefer Archive over Delete; schema stays simple now but confirmed extensible | Accepted |
| ADR-006 | 2026-07-14 | AI Assistant answers use a four-layer structure with citations distinguishing internal sources from general knowledge | Accepted |
| ADR-007 | 2026-07-14 | MVP development order: RAG Feasibility Spike inserted before Step 6, ahead of Frontend/Dashboard | Accepted |

---

## Decision Template

### ADR-XXX — Decision Title

- Date:
- Status: Proposed / Accepted / Superseded
- Related Step:

#### Context
為什麼需要做這個決策？

#### Decision
最後採用什麼方案？

#### Alternatives Considered
- 

#### Trade-offs
- Benefits:
- Costs / Risks:

#### Consequences
這個決策會如何影響後續開發？

#### Verification / Review Date
- 

---

## Accepted Decisions

<!-- 最新決策放上方。 -->

### ADR-001 — Enum validation lives in the application layer

- Date: 2026-07-11
- Status: Accepted
- Related Step: Step 4 (Dataset Ingestion)

#### Context

`docs/DATA_SCHEMA.md` defines canonical allowed values for `ems_mode` and `equipment_status`. `database/schema.sql` stores both columns as plain `TEXT` with no `CHECK` constraint. A documentation consistency fix unified the canonical enum lists across docs, which exposed that `backend/app/ingestion.py` was not validating these two columns against those lists (it only trimmed whitespace), unlike `battery_health_status`, which already had enum validation.

#### Decision

Enum validation for `ems_mode` and `equipment_status` is implemented in `backend/app/ingestion.py` (application layer), following the same pattern already used for `battery_health_status`: normalize (trim + lowercase), check membership against a canonical Python `set`, emit a warning for invalid values, and store `"unknown"` instead of the invalid value. The database schema keeps these columns as `TEXT` with no `CHECK` constraint.

#### Alternatives Considered

- Add a PostgreSQL `CHECK` constraint or native `ENUM` type on `ems_mode` / `equipment_status`. Rejected for MVP v1: it would reject the whole insert on an invalid value instead of allowing a warn-and-continue path, and would require a migration whenever `docs/DATA_SCHEMA.md` changes the allowed list.

#### Trade-offs

- Benefits: consistent with the existing `battery_health_status` pattern; keeps the "warn, don't reject" ingestion philosophy from `docs/DATA_SCHEMA.md` section 7; no schema migration needed to adjust the allowed list.
- Costs / Risks: the canonical value list now exists in two places — `docs/DATA_SCHEMA.md` and `backend/app/ingestion.py` — and must be kept in sync manually. `docs/DATA_SCHEMA.md` is the source of truth; any future change to the allowed values must update both.

#### Consequences

Future enum-like columns should follow the same application-layer pattern unless a future decision explicitly changes this (e.g. moving to DB-level `CHECK` constraints once the schema stabilizes).

#### Verification / Review Date

- Verified via `backend/tests/test_ingestion.py` (valid values, case/whitespace normalization, invalid value → warning + `unknown` fallback, canonical set matches `docs/DATA_SCHEMA.md`).

---

### ADR-002 — Structured data queries use controlled tool-calling, not unrestricted Text-to-SQL

- Date: 2026-07-14
- Status: Accepted
- Related Step: New Step 6 (RAG Feasibility Spike) / new Step 12 (Copilot Chat / AI Assistant integration)

#### Context

Full context and alternatives comparison: `docs/PROJECT_ALIGNMENT_REVIEW.md` (Decision Log #4, Phase 5 tool-calling vs Text-to-SQL comparison). The AI Assistant must be able to answer natural-language questions about structured energy time-series data without giving the LLM the ability to generate and execute arbitrary SQL.

#### Decision

The AI Assistant detects user intent and calls one of a fixed set of predefined dataset APIs / statistics functions / analysis tools (reusing the Step 5 query functions in `backend/app/datasets_queries.py`); the backend executes fixed, parameterized SQL; the LLM only explains the result. Unrestricted Text-to-SQL is explicitly out of scope for MVP.

#### Alternatives Considered

- Unrestricted Text-to-SQL (LLM generates arbitrary SQL). Rejected for MVP: larger attack surface (SQL injection–adjacent risk from semantically wrong but syntactically valid queries), harder to test (open-ended natural language input vs. enumerable tool calls), harder to apply per-field/per-row permission control later.

#### Trade-offs

- Benefits: reuses already-tested Step 5 query functions; testable the same way (query-layer + HTTP-layer tests); no new SQL-injection-class risk; access control can be added per-tool later without redesigning the query layer.
- Costs / Risks: the AI Assistant can only answer questions that map to an existing tool; new question types require adding a new tool, not just a prompt change.

#### Consequences

Any new structured-data question type the AI Assistant needs to answer requires a new, explicitly defined tool function (following the Step 5 query-function pattern), not a change to how the LLM is allowed to query the database.

#### Verification / Review Date

- To be verified when new Step 12 (AI Assistant integration) is implemented; no code exists yet.

---

### ADR-003 — OCR is a required MVP capability, with a tiered scope

- Date: 2026-07-14
- Status: Accepted
- Related Step: New Step 6 (RAG Feasibility Spike)

#### Context

Full context: `docs/PROJECT_ALIGNMENT_REVIEW.md` (Decision Log #6). Company-internal PDFs relevant to the confirmed first scenario (`BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT`) include scanned files; without OCR, these cannot enter chunking/embedding/retrieval/citation at all.

#### Decision

OCR is treated as a required MVP capability, not an optional future feature, but scoped narrowly for MVP:
- Must do: detect text-layer vs scanned PDF; run OCR on scanned PDFs; feed OCR output into chunking/embedding; preserve citation to original PDF + page; flag low-confidence/failed OCR as a warning; retain the original file, not just OCR text.
- Can simplify: Chinese + English only; general scanned PDFs only; tables/handwriting/complex diagrams treated as known limitations.
- Later: table structure recognition, handwriting recognition, engineering-drawing understanding, OCR confidence scoring + manual correction UI, multi-language OCR, large-scale batch processing.

#### Alternatives Considered

- Defer OCR entirely to post-MVP. Rejected: the confirmed data source for the RAG spike and MVP already includes scanned PDFs, so deferring OCR would make a meaningful share of the intended source material unusable from day one.
- Full enterprise-grade OCR (all languages, tables, handwriting) in MVP. Rejected: far exceeds MVP scope and the stated learning/demo goals.

#### Trade-offs

- Benefits: MVP can actually use the real documents it has access to; failure modes (low-confidence OCR) are surfaced as warnings instead of silently degrading answer quality.
- Costs / Risks: adds a new technical dependency (an OCR library/service) and a new class of parsing failure to handle and test.

#### Consequences

The RAG Feasibility Spike (`docs/RAG_SPIKE_PLAN.md`) must include OCR as a required validation item, not an open question of "whether it's needed."

#### Verification / Review Date

- To be verified by the RAG Feasibility Spike's OCR success/failure case results.

---

### ADR-004 — Embedding/LLM provider must be replaceable

- Date: 2026-07-14
- Status: Accepted
- Related Step: New Step 6 (RAG Feasibility Spike) / new Step 10 (Knowledge Base / RAG)

#### Context

Full context: `docs/PROJECT_ALIGNMENT_REVIEW.md` (Decision Log #8). MVP will call an external API (OpenAI Embeddings + LLM) for the spike and initial RAG work because the data used is non-confidential and the goal is fast uncertainty reduction, not infrastructure completeness. On-prem embedding/LLM is deferred until confidential data must be handled, which will likely require swapping providers later.

#### Decision

The embedding provider and LLM provider must not be hardcoded into core RAG/AI Assistant logic. Model name, embedding dimension, and API configuration must be centrally managed (not scattered across files). Every document/chunk's metadata must record which embedding model/version produced it. The design must support re-embedding and index rebuild when the model changes.

#### Alternatives Considered

- Hardcode OpenAI calls directly in RAG logic for speed. Rejected: would make the already-anticipated future provider swap (to on-prem models, for confidential data) a rewrite instead of a configuration change.

#### Trade-offs

- Benefits: provider swap later becomes a configuration/adapter change, not a rewrite; embedding-model-version tracking prevents silently mixing incompatible vector spaces after a future model change.
- Costs / Risks: adds a small amount of abstraction overhead now, for a benefit that only materializes when a provider swap actually happens.

#### Consequences

Any RAG/embedding code written from the spike onward should keep provider-specific calls behind a thin, swappable interface, even though the spike itself is throwaway exploration code.

#### Verification / Review Date

- To be verified when the RAG Feasibility Spike and later Step 10 implementation actually record embedding model/version in metadata.

---

### ADR-005 — Data lifecycle: prefer Archive over Delete; schema stays simple now

- Date: 2026-07-14
- Status: Accepted
- Related Step: Future (post-MVP), extensibility confirmed during Project Alignment Review

#### Context

Full context: `docs/PROJECT_ALIGNMENT_REVIEW.md` (Decision Log #14) and the data-lifecycle discussion earlier in the same review. The system currently has no delete, archive, versioning, or retention capability (append-only). An extensibility audit confirmed `database/schema.sql` can add `status`/`version`/`effective_from`/`effective_until`/`archived_at`/`deleted_at`/`superseded_by`/`retention_until` later as nullable columns without redesigning primary keys or existing queries (existing queries use explicit column lists, not `SELECT *`).

#### Decision

MVP does not implement full data lifecycle management now. When it is implemented (post-MVP), old-but-historically-valuable data (old rules, past case records) should default to **Archive**, not Delete. Default queries use Active data only; historical queries explicitly opt into Archived data. Delete is reserved for test data, duplicates, no-retention-value data, or policy-mandated deletion.

#### Alternatives Considered

- Add the lifecycle columns now, even unused. Rejected for this round: no current consumer of these fields, and the extensibility audit already confirmed adding them later carries no rework cost — adding them now would be speculative.

#### Trade-offs

- Benefits: avoids premature schema complexity; the Archive-over-Delete default protects the historical-reference value called out for old rules, case records, and past decisions.
- Costs / Risks: rows inserted before this decision is implemented will lack `updated_at`/history, so historical auditability for early data will always be incomplete — a permanent, accepted gap, not something a later migration can retroactively fix.

#### Consequences

Any future Step that introduces document/case versioning or retention enforcement should follow this Archive-first default rather than re-deciding it from scratch.

#### Verification / Review Date

- To be verified when data lifecycle fields are actually added to the schema (no target Step assigned yet; timing deferred).

---

### ADR-006 — AI Assistant answer structure: four layers + source-typed citations

- Date: 2026-07-14
- Status: Accepted
- Related Step: New Step 6 (RAG Feasibility Spike) / new Step 9 (Rule-Based Analysis) / new Step 12 (AI Assistant integration)

#### Context

Full context: `docs/PROJECT_ALIGNMENT_REVIEW.md` (Decision Log #12, #13). `docs/MVP1_RULES.md` section 8 already defined an answer structure (`Finding / Evidence / Possible cause / Suggested action / Confidence`) before this review. The review's interview surfaced a more specific requirement: the AI must clearly separate confirmed case-specific facts from LLM-supplied general engineering background knowledge, and must not present a guess as a confirmed cause when evidence is insufficient.

#### Decision

`docs/MVP1_RULES.md` section 8 is updated (not replaced) to a seven-part structure that keeps every existing field and adds the two new requirements: **Confirmed facts/Finding, Evidence, Possible causes, General engineering background, Suggested actions/Next checks, Confidence, Citations.** Case-specific facts may only come from structured data, Rule Engine output, retrieved documents, or case records. General engineering background knowledge may only be used to explain concepts, suggest possible directions, or propose next checks — never presented as a confirmed cause. Citations must distinguish internal sources (with an actual reference) from general background knowledge (explicitly labeled as such, never disguised as an internal source). When evidence is insufficient, the assistant must say so rather than guess.

#### Alternatives Considered

- Keep `docs/MVP1_RULES.md` section 8 as-is and only add the new rules to `docs/MVP_V1_SPEC.md`. Rejected: `docs/MVP1_RULES.md` is the implementation source of truth for rule-based logic; leaving it out of sync with the newly confirmed format would recreate the exact kind of documentation-vs-code drift already fixed once in ADR-001.

#### Trade-offs

- Benefits: single, consistent answer contract across `docs/MVP_V1_SPEC.md` and `docs/MVP1_RULES.md`; the general-knowledge/case-fact separation directly targets the hallucination and trust risks identified in `docs/PROJECT_ALIGNMENT_REVIEW.md` section 6.
- Costs / Risks: prompt design and future response schemas must implement all seven fields, not the original five; concrete similarity thresholds and confidence-level cutoffs are still undefined and must come from the RAG Feasibility Spike's actual retrieval results, not be guessed now.

#### Consequences

Any future Step implementing the Rule Engine's explanation output or the AI Assistant's RAG-based answers must follow this seven-part structure; similarity-threshold/confidence-level definitions are an open follow-up item, not resolved by this ADR.

#### Verification / Review Date

- To be verified when the RAG Feasibility Spike tests whether this four-way separation (facts / possible causes / general knowledge / next steps) is achievable in practice.

---

### ADR-007 — MVP development order: RAG Feasibility Spike before Step 6

- Date: 2026-07-14
- Status: Accepted
- Related Step: New Step 6 (RAG Feasibility Spike)

#### Context

Full context and alternatives comparison: `docs/PROJECT_ALIGNMENT_REVIEW.md` (Decision Log #16, Phase 5 sequencing comparison). The original `docs/DEVELOPMENT_WORKFLOW.md` build order validated the RAG/OCR/citation capabilities (originally Step 9) only after Frontend, Dashboard, and Rule Engine (originally Steps 6–8) were built — deferring validation of the product's biggest technical unknowns to late in the build order.

#### Decision

A new Step 6, RAG Feasibility Spike (full spec: `docs/RAG_SPIKE_PLAN.md`), is inserted before the original Step 6 (Frontend Foundation). All subsequent Steps are renumbered: original Step 6–12 become new Step 7–13. The spike validates PDF parsing, OCR, chunking, retrieval accuracy, citation accuracy, and confidence/evidence separation on a small set of real non-confidential documents before committing to the full Frontend/Dashboard/Rule Engine/RAG build-out.

#### Alternatives Considered

- Keep the original order (Dashboard/Rule Engine first, RAG validated later — "Version 1" in `docs/PROJECT_ALIGNMENT_REVIEW.md`). Rejected: defers validation of the highest-uncertainty, highest-value part of the product.
- Interleave Dashboard/Rule Engine and RAG work ("Version 3"). Rejected for a solo, learning-focused developer: context-switching between two tracks was judged less effective than finishing one deep validation first, based on the version comparison in Phase 5.

#### Trade-offs

- Benefits: the biggest product risk (RAG/OCR/citation feasibility) is tested early and cheaply, before Dashboard/Rule Engine time is invested; produces an honest, concrete story (risk identification → spike design → evaluation → architecture adjustment) for interview use regardless of outcome.
- Costs / Risks: no visible UI progress during the spike period; if the spike takes longer than expected, it may feel like "no output" even though the risk-reduction work has value.

#### Consequences

`docs/DEVELOPMENT_WORKFLOW.md` section 6 is renumbered accordingly; the spike's deliverables (per `docs/RAG_SPIKE_PLAN.md`) must include an explicit recommendation on whether to proceed to full RAG development and whether the Step 6–13 roadmap needs further adjustment.

#### Verification / Review Date

- To be verified by the RAG Feasibility Spike's deliverables once the spike is executed.
