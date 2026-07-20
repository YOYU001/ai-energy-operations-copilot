# PROGRESS.md

## Current Goal
Build **AI Energy Operations Copilot MVP v1** as a NVIDIA interview portfolio project and AI engineering technical showcase.

## Current Phase
Step 5 completed → Project Alignment Review completed → Step 6: RAG Document Ingestion Spike — Sub-step 1, 2, 3, 4 (Embedding and Vector Storage Spike), 5 (Hybrid Retrieval Scoring), 6 (Active Chunk Lifecycle / Blue-Green Cutover), 7 (Retrieval Evaluation Dataset Expansion), and 8 (doc4 Table Detection + Ingestion, both Phase 1 offline and Phase 2 real ingestion) completed. `is_active` retention/cleanup policy remains deferred.

## Completed
- Defined MVP v1 product scope, tech stack, internal-knowledge-only principle, initial data schema, and Claude Code learning-by-building / incremental development workflow.
- Created project skeleton folders (frontend/, backend/, database/, data/, scripts/).
- Implemented minimal FastAPI backend with GET /health and GET /version.
- Implemented database foundation: PostgreSQL + pgvector via Docker, initial 7-table schema (database/schema.sql), SQLAlchemy connection, GET /db-check.
- Step 4 — Dataset Ingestion: POST /datasets/upload (CSV validation, type conversion, warning report, insertion into datasets/energy_timeseries). Added canonical enum validation for ems_mode/equipment_status (see docs/DECISIONS.md ADR-001). 6 tests passing.
- Defined "Beginner Teaching Mode" and "Execution and Teaching Must Be Separate" process rules in docs/WORKFLOW_SHORT.md (single canonical 7-step workflow: plan → confirm → execute → test → report → confirm → teach).
- Step 5 — Dataset API: GET /datasets, /datasets/{id}, /datasets/{id}/summary, /datasets/{id}/timeseries, built on DI-based db connection for testability. 36 tests passing total. Verified against real dev database.
- Completed a five-phase Project Alignment Review before Step 6 (confirmed energy-vertical scope, locked 16 product/architecture decisions, reordered Step 6–13 roadmap). Full record: docs/PROJECT_ALIGNMENT_REVIEW.md.
- Step 6 Sub-step 1 — Test Corpus and Evaluation Set: selected 4 spike PDFs, drafted 17 fixed test questions (spike/test_questions.json) as the evaluation baseline. Details: docs/RAG_SPIKE_PLAN.md.
- Step 6 Sub-step 2 — PDF Parsing and OCR Validation: built spike/pdf_parser.py, spike/ocr_fallback.py; 4-state page classification (text/near_empty/scanned/ocr_failed). 7 tests passing. Details: docs/RAG_SPIKE_PLAN.md §3.1, §8.
- Step 6 Sub-step 3 — Chunking Design: built spike/chunker.py (4 strategies, table-aware row-group packing). Recommended structured_600_100. 12 tests passing. Details: docs/RAG_SPIKE_PLAN.md §9.
- Step 6 Sub-step 4 — Embedding and Vector Storage Spike: built spike/hashing.py, embedding_provider.py, vector_store.py, schema_spike.sql; idempotent upsert verified against real DB (124 chunks, 0 duplicates). 29 tests passing total. Details: docs/RAG_SPIKE_PLAN.md §10.
- Step 6 Sub-step 5 — Hybrid Retrieval Scoring: built spike/query_parser.py, hybrid_retrieval.py (semantic + date-match + table-match weighted scoring). Verified against real DB; corrected a Sub-step 4 preview-truncation misreading (q06 retrieval was correct all along). 43 tests passing total. Details: docs/RAG_SPIKE_PLAN.md §11.
- Step 6 Sub-step 6 — Active Chunk Lifecycle / Blue-Green Cutover: added supersedes_document_id to schema; new chunks always ingest is_active=false then atomically cut over (activate new, deactivate superseded) in one transaction, with rollback and anomaly guards. Retrieval queries now filter on is_active=true. 9 new tests, 52 total passing. Verified against real DB with a throwaway document (existing 124 doc1/doc3 chunks untouched). Details: docs/RAG_SPIKE_PLAN.md §13.
- Step 6 Sub-step 7 — Retrieval Evaluation Dataset Expansion: expanded test set from 17 to 29 questions; built spike/retrieval_metrics.py and spike/run_retrieval_benchmark.py. 69 tests passing total. Real-DB benchmark: hybrid retrieval beat vector-only on hit@1 (7/11 vs 5/11), no regressions; global scope revealed real cross-document interference (16.4%). Details: docs/RAG_SPIKE_PLAN.md §14.
- Step 6 Sub-step 8 Phase 1 — doc4 Table Detection (offline, no ingestion): added a second "caption-first" table-detection path to spike/chunker.py for doc4's caption-before-data table style, independent of doc3's existing path. 8 new tests, 77 total passing. Real-doc4 results: 14/18 tables now correctly detected (4 undetected ones have no extractable grid text, confirmed not a heuristic gap); doc1/doc2/doc3 unaffected. Details: docs/RAG_SPIKE_PLAN.md §15.
- Step 6 Sub-step 8 Phase 2 — doc4 Ingestion: ingested doc4 (157 chunks: 143 prose + 14 table) into spike_document_chunks via the existing blue-green lifecycle; 2 embedding API calls, 72,049 tokens, 0 failures, idempotency re-verified (0 calls/0 inserts on re-run). DB-verified: 157/157 active, 0 null embeddings, 0 duplicate chunk_ids. q27/q28 flipped to retrieval_eval_eligible=true (hit@3/5 confirmed); q15 kept false — ground truth chunk confirmed present in DB but real vector-similarity search never surfaces it within pool_size=30 (documented, not fixed this round). Formal benchmark re-run: doc1/doc3 metrics identical to Sub-step 7 (hybrid 7/11 vs vector-only 5/11 on hit@1), zero regression. 113 tests passing total. Details: docs/RAG_SPIKE_PLAN.md §16.
- Local dev-tooling architecture (not a RAG-spike sub-step; built alongside Sub-step 8): `.claude/agents/` (research.md haiku, qa.md sonnet, reviewer.md sonnet, each with restricted tool access) and `.claude/skills/` (db-bootstrap, progress-lint, chunk-inspect, embed-cost-estimate, ocr-page-diagnose, retrieval-debug script skills, plus /research, /qa, /review command skills that invoke the corresponding agents). All 9 verified against real project data and real subagent invocations (db-bootstrap ran for real; /qa, /research, /review each actually invoked their agent and returned correctly-formatted reports).
- reviewer subagent's first real review (spike/hybrid_retrieval.py) found 2 real LOW-severity issues, both fixed: `fetch_candidates`'s `ORDER BY` recomputed the vector-distance expression instead of reusing the `distance` SELECT alias; `run_hybrid_query`'s `filename_filter` type hint was `str` instead of `str | None`, disagreeing with `fetch_candidates`'s documented unscoped-query support. 113 tests passing after fix, no regressions.

## Important Decisions
- Frontend: Next.js
- Backend: FastAPI
- Database: PostgreSQL
- Vector Search: pgvector first, Chroma fallback only
- Default mode: Internal Knowledge Only
- MVP v1 uses rule-based analysis first, not optimization algorithms.
- MVP v1 should focus on dashboard + structured analytics + AI assistant, not only chat.

## MVP v1 Scope
MVP v1 should include:
- Internal document Q&A
- CSV energy time-series ingestion and analysis
- Fixed dashboard charts
- Rule-based anomaly diagnosis
- Simplified similar case search
- Rule-based battery scheduling suggestions
- Cost estimation
- Green Operations Index
- Role-based response modes
- Analysis report generation

## Out of Scope for MVP v1
Do not implement unless explicitly approved:
- Real EMS control
- Real web search
- Optimization algorithms
- Self-trained PV/load forecasting models
- Multi-agent architecture
- Full carbon accounting or ESG reporting
- Real power trading integration
- Real ancillary service revenue calculation

## Current Known Issues
- Frontend is not implemented yet.
- Sample CSV datasets are not created yet.
- RAG ingestion pipeline is not implemented yet.
- Rule-based analysis logic is not implemented yet.
- No ORM model yet.
- No Alembic migration yet.
- Docker Desktop must stay running for database-dependent endpoints.
- No authentication yet.
- No duplicate upload prevention.
- Current batch insert approach is suitable for MVP-scale datasets but has not been benchmarked or optimized for large-volume ingestion.
- `DOCUMENTATION_FIX_REPORT.md` and `VALIDATION_RESULTS.md` remain at the repository root; kept there for now, to be archived or removed after a later decision.
- Repository is not yet a git repository; git initialization is planned as its own dedicated, fully-taught Step rather than a side effect of another Step.
- No automated integration tests against a real database yet (Step 5 tests use a fake connection); deferred as an independent follow-up, not part of Step 5 or the RAG spike.
- Data lifecycle fields (status/version/effective_from/effective_until/archived_at/deleted_at/superseded_by/retention_until) are confirmed addable to the schema without rework, but have not been added yet; timing is deferred until actually needed.
- Detailed risks and blind spots (hallucination, citation accuracy, OCR quality, confidence thresholds, cost, etc.) are tracked in `docs/PROJECT_ALIGNMENT_REVIEW.md` section 6, not duplicated here.

## Next Step
Step 6: RAG Document Ingestion Spike — Sub-step 8 (doc4 Table Detection + Ingestion, Phase 1 and Phase 2) completed; see `docs/RAG_SPIKE_PLAN.md` sections 15-16. Retention/cleanup of superseded (is_active=false) chunks remains deferred to its own future sub-step. Reranking and LLM answer generation have not started. `structured_600_100` remains only the provisional chunking strategy (confirmed still recommended after this round). Other candidates for a future sub-step: establishing expected_content_keywords for q03/q04/q05, tuning multi_chunk_coverage_threshold per question, investigating the q20 cross-chunk retrieval failure, deciding whether q15's real vector-similarity retrieval miss (ground truth exists in DB but never surfaces in the top-30 candidate pool) needs a query-rewrite or architecture fix, or whether the 5 doc4 tables truncated at sentence-ending punctuation (表2-1/3-4/4-1/4-4/4-6) need a follow-up fix.

## Files To Read Next Time
Always read first:
- `CLAUDE.md`
- `PROGRESS.md`
- `docs/WORKFLOW_SHORT.md`

Read before the relevant implementation task:
- `docs/MVP_V1_SPEC.md` for product scope and non-goals
- `docs/DATA_SCHEMA.md` for dataset, validation, and database schema
- `docs/DEVELOPMENT_WORKFLOW.md` for build order and implementation workflow
- `docs/MVP1_RULES.md` for rule-based analysis and scheduling
- `docs/SAMPLE_DATA_PLAN.md` for synthetic demo data
- `docs/PROJECT_ALIGNMENT_REVIEW.md` for the confirmed product definition, decision log, MVP scope, non-goals, risks, and architecture direction
- `docs/RAG_SPIKE_PLAN.md` before starting the new Step 6 RAG Feasibility Spike

Read only when relevant:
- `docs/Claude_Code_Learning_Workflow.md`
- `docs/ANTHROPIC_LEARN_MAP.md`
- `docs/DECISIONS.md`
- `docs/OFFICIAL_UPDATE_LOG.md`
- `docs/LEARNING_LOG.md`
- `skills/*`

## Working Rule
每次只做一小步。修改前先說明，修改後要測試並回報。不要修改無關檔案，不要加入未討論功能。
