-- Step 6 Sub-step 4: spike-only schema.
-- Deliberately separate from database/schema.sql's `documents` /
-- `document_chunks` tables -- this is exploratory spike infrastructure, not
-- a production migration. Nothing here should be assumed stable until the
-- spike concludes and a real Step 10 migration is designed from what was
-- learned here.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS spike_documents (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL,
    document_content_hash TEXT NOT NULL UNIQUE,
    total_pages INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

-- Step 6 Sub-step 6: document-level lineage for blue-green chunk cutover.
-- Points from a newer document row to the older document row it replaces
-- (same filename, different document_content_hash). NULL means this is the
-- first-ever ingestion of this logical document. "Logical document" is
-- identified by filename only in this spike -- a rename is treated as an
-- unrelated new document, and two different files sharing a filename (e.g.
-- from different folders) would be treated as versions of each other. This
-- is a known, accepted limitation, not something this spike solves.
ALTER TABLE spike_documents
    ADD COLUMN IF NOT EXISTS supersedes_document_id INTEGER REFERENCES spike_documents(id);

-- embedding dimension (1536) matches OpenAI text-embedding-3-small, the
-- provider/model chosen for this spike (see spike/embedding_provider.py).
CREATE TABLE IF NOT EXISTS spike_document_chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES spike_documents(id),
    strategy_name TEXT NOT NULL,
    chunk_type TEXT NOT NULL,
    text TEXT NOT NULL,
    embedding_content_hash TEXT NOT NULL,
    chunk_metadata_hash TEXT NOT NULL,
    page_index_start INTEGER NOT NULL,
    page_index_end INTEGER NOT NULL,
    pdf_page_number_start INTEGER NOT NULL,
    pdf_page_number_end INTEGER NOT NULL,
    printed_page_number_map JSONB,
    section_title TEXT,
    table_title TEXT,
    embedding VECTOR(1536),
    embedding_provider TEXT,
    embedding_model TEXT,
    embedding_dimensions INTEGER,
    embedding_model_version TEXT,
    embedded_at TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_spike_chunks_doc_strategy
    ON spike_document_chunks (document_id, strategy_name);

-- No vector index (IVFFlat/HNSW) is created in this sub-step: the spike
-- corpus is far too small (a few hundred chunks) for an index to be
-- meaningful, and index type/parameters should be chosen once real Step 10
-- data volume is known. Retrieval in this sub-step is brute-force
-- (ORDER BY embedding <=> :query_vector LIMIT k).
