-- AI Energy Operations Copilot MVP v1 - Initial Schema
-- See docs/DATA_SCHEMA.md section 6 for field definitions.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    title TEXT,
    file_name TEXT,
    file_type TEXT,
    source_type TEXT,
    uploaded_at TIMESTAMP,
    status TEXT,
    document_content_hash TEXT UNIQUE,
    supersedes_document_id INTEGER REFERENCES documents(id),
    total_pages INTEGER
);

-- embedding dimension (1536) matches OpenAI text-embedding-3-small, validated by
-- the Step 6 RAG Feasibility Spike (see docs/RAG_SPIKE_PLAN.md) -- no longer a
-- placeholder. Schema below mirrors spike/schema_spike.sql's spike_document_chunks
-- (see docs/RAG_SPIKE_PLAN.md §17 for the production migration this reflects):
-- chunk_id is a deterministic hash (not SERIAL) so identical content always maps
-- to the same row, which is what makes the blue-green lifecycle idempotent.
CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    strategy_name TEXT NOT NULL,
    chunk_type TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding_content_hash TEXT NOT NULL,
    chunk_metadata_hash TEXT NOT NULL,
    page_index_start INTEGER NOT NULL,
    page_index_end INTEGER NOT NULL,
    pdf_page_number_start INTEGER NOT NULL,
    pdf_page_number_end INTEGER NOT NULL,
    printed_page_number_map JSONB,
    section_title TEXT,
    table_title TEXT,
    embedding vector(1536),
    embedding_provider TEXT,
    embedding_model TEXT,
    embedding_dimensions INTEGER,
    embedding_model_version TEXT,
    embedded_at TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_doc_strategy
    ON document_chunks (document_id, strategy_name);

CREATE TABLE IF NOT EXISTS datasets (
    id SERIAL PRIMARY KEY,
    name TEXT,
    file_name TEXT,
    description TEXT,
    row_count INTEGER,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS energy_timeseries (
    id SERIAL PRIMARY KEY,
    dataset_id INTEGER REFERENCES datasets(id),
    timestamp TIMESTAMP,
    site_id TEXT,
    pv_forecast_kw NUMERIC,
    pv_actual_kw NUMERIC,
    load_kw NUMERIC,
    load_forecast_kw NUMERIC,
    battery_soc NUMERIC,
    battery_power_kw NUMERIC,
    battery_temperature NUMERIC,
    electricity_price NUMERIC,
    contract_capacity_kw NUMERIC,
    grid_import_kw NUMERIC,
    grid_export_kw NUMERIC,
    weather_condition TEXT,
    ghi NUMERIC,
    temperature NUMERIC,
    humidity NUMERIC,
    ems_mode TEXT,
    equipment_status TEXT,
    battery_soh NUMERIC,
    battery_cycle_count INTEGER,
    battery_equivalent_cycle NUMERIC,
    battery_health_status TEXT,
    battery_is_second_life BOOLEAN,
    battery_rated_capacity_kwh NUMERIC,
    battery_available_capacity_kwh NUMERIC
);

-- embedding dimension (1536) matches OpenAI text-embedding-3-small, validated
-- by the Step 6 RAG Feasibility Spike and already used in production by
-- document_chunks (Step 10) -- no longer a placeholder. Provenance and
-- timestamp columns mirror document_chunks' precedent (ADR-004: provider
-- not hardcoded, model/version recorded per row so a future re-embedding
-- pass can tell which rows are stale), added for Step 11 (Case Similarity).
CREATE TABLE IF NOT EXISTS case_records (
    id SERIAL PRIMARY KEY,
    -- Stable business identifier for a case (Step 11 Sub-step 2B): required
    -- and unique so upsert_case_record can rely on a real DB-level
    -- ON CONFLICT (case_id) for atomic upsert, instead of an application-
    -- level SELECT-then-branch race. UNIQUE alone would still allow
    -- multiple NULLs, hence NOT NULL as well.
    case_id TEXT NOT NULL UNIQUE,
    site_id TEXT,
    event_time TIMESTAMP,
    event_type TEXT,
    symptoms TEXT,
    root_cause TEXT,
    operator_action TEXT,
    resolution_result TEXT,
    severity TEXT,
    tags TEXT,
    related_dataset_id INTEGER REFERENCES datasets(id),
    related_time_range TEXT,
    embedding vector(1536),
    embedding_provider TEXT,
    embedding_model TEXT,
    embedding_dimensions INTEGER,
    embedding_model_version TEXT,
    -- Hash of exactly the text that was embedded (same field name and
    -- purpose as document_chunks.embedding_content_hash, computed by
    -- app/services/hashing.py's compute_embedding_content_hash). Lets
    -- scripts/seed_case_records.py detect an unchanged case and skip
    -- re-calling the embedding API on re-run, instead of re-embedding
    -- every case every time (fix: avoid redundant case embedding requests).
    embedding_content_hash TEXT,
    embedded_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id SERIAL PRIMARY KEY,
    dataset_id INTEGER REFERENCES datasets(id),
    analysis_type TEXT,
    rule_version TEXT,
    result_json JSONB,
    created_at TIMESTAMP,
    UNIQUE (dataset_id, analysis_type, rule_version)
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    session_id TEXT,
    role TEXT,
    content TEXT,
    created_at TIMESTAMP
);
