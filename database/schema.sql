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

-- Upgrade path for any case_records table created before Sub-step 2B's
-- case_id NOT NULL UNIQUE requirement and the embedding provenance/hash
-- columns existed. CREATE TABLE IF NOT EXISTS above is a no-op against an
-- already-existing table, so an older dev/prod database would otherwise
-- silently keep case_id nullable/non-unique and be missing these columns
-- (Codex PR #37 review, P1). Safe to re-run: every ALTER is IF NOT EXISTS
-- or guarded by an existence check against pg_constraint/information_schema,
-- and it NEVER deletes or rewrites an existing case_id value to make it
-- conform -- if any row already violates the new constraint, it raises and
-- stops so the operator can fix the data deliberately, not have it silently
-- coerced.
DO $$
BEGIN
    ALTER TABLE case_records ADD COLUMN IF NOT EXISTS embedding_provider TEXT;
    ALTER TABLE case_records ADD COLUMN IF NOT EXISTS embedding_model TEXT;
    ALTER TABLE case_records ADD COLUMN IF NOT EXISTS embedding_dimensions INTEGER;
    ALTER TABLE case_records ADD COLUMN IF NOT EXISTS embedding_model_version TEXT;
    ALTER TABLE case_records ADD COLUMN IF NOT EXISTS embedding_content_hash TEXT;
    ALTER TABLE case_records ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMP;
    ALTER TABLE case_records ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT now();
    ALTER TABLE case_records ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT now();

    IF EXISTS (SELECT 1 FROM case_records WHERE case_id IS NULL) THEN
        RAISE EXCEPTION 'case_records upgrade aborted: % row(s) have a NULL case_id -- back-fill case_id manually, then re-run schema.sql',
            (SELECT count(*) FROM case_records WHERE case_id IS NULL);
    END IF;

    IF EXISTS (
        SELECT case_id FROM case_records GROUP BY case_id HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'case_records upgrade aborted: duplicate case_id value(s) exist -- resolve duplicates manually, then re-run schema.sql';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'case_records' AND column_name = 'case_id' AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE case_records ALTER COLUMN case_id SET NOT NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'case_records_case_id_key'
    ) THEN
        ALTER TABLE case_records ADD CONSTRAINT case_records_case_id_key UNIQUE (case_id);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS analysis_runs (
    id SERIAL PRIMARY KEY,
    dataset_id INTEGER REFERENCES datasets(id),
    analysis_type TEXT,
    rule_version TEXT,
    result_json JSONB,
    created_at TIMESTAMP,
    UNIQUE (dataset_id, analysis_type, rule_version)
);

-- Step 12 Sub-step 1: conversations + chat_messages. See
-- docs/step12_substep1_plan.md for full design rationale (guarded upgrade
-- pattern, regenerate locking contract, connection-ownership contract);
-- reviewed end-to-end by an independent read-only Codex pass across three
-- iterations before implementation.
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    title TEXT,
    role_mode TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    archived_at TIMESTAMP
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'conversations_role_mode_check'
          AND conrelid = 'conversations'::regclass
    ) THEN
        ALTER TABLE conversations ADD CONSTRAINT conversations_role_mode_check
            CHECK (role_mode IS NULL OR role_mode IN ('operator', 'engineer', 'executive', 'training'));
    END IF;
END $$;

-- chat_messages was a Step 1-era placeholder (id, session_id, role,
-- content, created_at) with zero rows in every known dev DB. Rather than
-- a one-time DROP TABLE (which would destroy real conversation data the
-- next time anyone re-runs schema.sql after this ships), this is a
-- guarded upgrade: ADD COLUMN IF NOT EXISTS for every new column, then
-- existence-checked ALTER/ADD CONSTRAINT statements, so re-running this
-- block against an already-upgraded table is always a no-op. Any legacy
-- row still missing conversation_id (impossible to have any other way,
-- since the old schema never had that column) aborts the migration loudly
-- rather than guessing which conversation it belongs to.
CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    session_id TEXT,
    role TEXT,
    content TEXT,
    created_at TIMESTAMP
);

DO $$
BEGIN
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS conversation_id INTEGER;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS status TEXT;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS citations JSONB;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS tool_calls JSONB;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS parent_user_message_id INTEGER;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS attempt_number INTEGER;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS is_active BOOLEAN;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS regenerated_from_message_id INTEGER;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS provider TEXT;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS model TEXT;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS model_version TEXT;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS finish_reason TEXT;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS usage JSONB;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS error_message TEXT;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS started_at TIMESTAMP;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_messages' AND column_name = 'updated_at' AND column_default IS NOT NULL
    ) THEN
        ALTER TABLE chat_messages ALTER COLUMN updated_at SET DEFAULT now();
    END IF;
    UPDATE chat_messages SET updated_at = COALESCE(updated_at, created_at, now()) WHERE updated_at IS NULL;
    ALTER TABLE chat_messages ALTER COLUMN updated_at SET NOT NULL;

    -- Never assume "currently empty" is a permanent fact. Any row still
    -- missing conversation_id (the old placeholder schema never had this
    -- column, so any pre-Step-12 row will be NULL here) is treated as
    -- orphaned data this migration cannot safely re-home on its own.
    -- It aborts loudly instead of guessing or discarding.
    IF EXISTS (SELECT 1 FROM chat_messages WHERE conversation_id IS NULL) THEN
        RAISE EXCEPTION 'chat_messages upgrade aborted: % row(s) exist with no conversation_id -- back up/export or manually resolve them before re-running schema.sql. This upgrade never silently discards or auto-assigns orphaned rows to a conversation.',
            (SELECT count(*) FROM chat_messages WHERE conversation_id IS NULL);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_messages' AND column_name = 'conversation_id' AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE chat_messages ALTER COLUMN conversation_id SET NOT NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chat_messages_conversation_id_fkey'
          AND conrelid = 'chat_messages'::regclass
    ) THEN
        ALTER TABLE chat_messages
            ADD CONSTRAINT chat_messages_conversation_id_fkey
            FOREIGN KEY (conversation_id) REFERENCES conversations(id);
    END IF;

    UPDATE chat_messages SET attempt_number = 1 WHERE attempt_number IS NULL;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_messages' AND column_name = 'attempt_number' AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE chat_messages ALTER COLUMN attempt_number SET NOT NULL;
    END IF;
    ALTER TABLE chat_messages ALTER COLUMN attempt_number SET DEFAULT 1;

    UPDATE chat_messages SET is_active = true WHERE is_active IS NULL;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_messages' AND column_name = 'is_active' AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE chat_messages ALTER COLUMN is_active SET NOT NULL;
    END IF;
    ALTER TABLE chat_messages ALTER COLUMN is_active SET DEFAULT true;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_messages' AND column_name = 'status' AND is_nullable = 'NO'
    ) THEN
        UPDATE chat_messages SET status = 'completed' WHERE status IS NULL;
        ALTER TABLE chat_messages ALTER COLUMN status SET NOT NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chat_messages_role_check'
          AND conrelid = 'chat_messages'::regclass
    ) THEN
        ALTER TABLE chat_messages ADD CONSTRAINT chat_messages_role_check
            CHECK (role IN ('user', 'assistant'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chat_messages_status_check'
          AND conrelid = 'chat_messages'::regclass
    ) THEN
        ALTER TABLE chat_messages ADD CONSTRAINT chat_messages_status_check
            CHECK (status IN ('streaming', 'completed', 'aborted', 'failed'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chat_messages_attempt_number_check'
          AND conrelid = 'chat_messages'::regclass
    ) THEN
        ALTER TABLE chat_messages ADD CONSTRAINT chat_messages_attempt_number_check
            CHECK (attempt_number >= 1);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chat_messages_role_shape_check'
          AND conrelid = 'chat_messages'::regclass
    ) THEN
        ALTER TABLE chat_messages ADD CONSTRAINT chat_messages_role_shape_check
            CHECK (
                (role = 'user'
                    AND parent_user_message_id IS NULL
                    AND regenerated_from_message_id IS NULL
                    AND status = 'completed')
                OR
                (role = 'assistant'
                    AND parent_user_message_id IS NOT NULL)
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chat_messages_parent_fkey'
          AND conrelid = 'chat_messages'::regclass
    ) THEN
        ALTER TABLE chat_messages
            ADD CONSTRAINT chat_messages_parent_fkey
            FOREIGN KEY (parent_user_message_id) REFERENCES chat_messages(id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chat_messages_regenerated_from_fkey'
          AND conrelid = 'chat_messages'::regclass
    ) THEN
        ALTER TABLE chat_messages
            ADD CONSTRAINT chat_messages_regenerated_from_fkey
            FOREIGN KEY (regenerated_from_message_id) REFERENCES chat_messages(id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chat_messages_parent_attempt_key'
          AND conrelid = 'chat_messages'::regclass
    ) THEN
        ALTER TABLE chat_messages
            ADD CONSTRAINT chat_messages_parent_attempt_key
            UNIQUE (parent_user_message_id, attempt_number);
    END IF;

    -- session_id has no equivalent in the new model (conversation_id
    -- replaces its role) -- but proving every row now has a conversation_id
    -- does NOT by itself prove session_id's own values are redundant or
    -- safely discardable. Require an explicit, separate check: only drop
    -- the column when every surviving row's session_id is already NULL.
    --
    -- This whole step must be guarded by a column-existence check: once a
    -- prior run has already dropped session_id, a bare
    -- `SELECT ... WHERE session_id IS NOT NULL` on a later run would fail
    -- with "column does not exist" the moment this statement is reached,
    -- breaking re-runnability. Wrapping it in this outer IF means the
    -- value-check query is only ever planned/executed while the column
    -- still exists; once it's gone, this entire branch is skipped and the
    -- migration stays a no-op here on every subsequent run.
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_messages' AND column_name = 'session_id'
    ) THEN
        IF EXISTS (SELECT 1 FROM chat_messages WHERE session_id IS NOT NULL) THEN
            RAISE EXCEPTION 'chat_messages upgrade aborted: % row(s) still have a non-null session_id -- session_id is being retired in favor of conversation_id; export/verify this data is safe to discard, then either NULL it out manually or re-run schema.sql with the session_id DROP COLUMN step skipped for this pass.',
                (SELECT count(*) FROM chat_messages WHERE session_id IS NOT NULL);
        END IF;
        ALTER TABLE chat_messages DROP COLUMN session_id;
    END IF;

    -- created_at was nullable with no default in the old placeholder
    -- schema -- backfill any legacy NULLs, then guardedly add a default
    -- and NOT NULL so both existing rows and the
    -- (conversation_id, created_at, id) index below always have a real,
    -- ordering-safe timestamp.
    UPDATE chat_messages SET created_at = COALESCE(created_at, now()) WHERE created_at IS NULL;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_messages' AND column_name = 'created_at' AND column_default IS NOT NULL
    ) THEN
        ALTER TABLE chat_messages ALTER COLUMN created_at SET DEFAULT now();
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_messages' AND column_name = 'created_at' AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE chat_messages ALTER COLUMN created_at SET NOT NULL;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS chat_messages_active_attempt_key
    ON chat_messages (parent_user_message_id) WHERE is_active;

CREATE INDEX IF NOT EXISTS chat_messages_conversation_created_idx
    ON chat_messages (conversation_id, created_at, id);

CREATE INDEX IF NOT EXISTS conversations_active_updated_idx
    ON conversations (updated_at) WHERE archived_at IS NULL;
