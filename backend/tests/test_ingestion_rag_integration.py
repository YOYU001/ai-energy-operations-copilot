"""Step 10 Sub-step 3: real dev PostgreSQL integration tests for
app/services/ingestion_rag.py + app/document_chunks_queries.py.

Unlike test_ingestion_rag.py / test_document_chunks_queries.py (FakeRagConnection,
no real DB), these tests connect to the real dev Postgres + pgvector container
(docker compose's `db` service) via app.db.get_connection(), to verify actual
transaction/FK/UNIQUE/JSONB/vector(1536) behavior that a fake connection
cannot validate.

No real OpenAI API calls: embeddings use DeterministicFakeEmbeddingProvider
(same text -> same 1536-dim vector, different text -> different vector, no
network). Fixture PDFs are generated at test runtime via PyMuPDF (already a
project dependency) -- nothing is committed to the repo.

Isolation: every row this file writes uses a file_name starting with
INTEGRATION_TEST_PREFIX. Cleanup runs in a fixture teardown (try/finally)
regardless of test outcome, deleting only rows matching that prefix -- never
a broader reset/truncate/drop.
"""

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

import app.services.ingestion_rag as ingestion_rag
from app.db import get_connection
from app.document_chunks_queries import (
    get_active_chunks,
    get_chunk_activation_counts,
    insert_inactive_chunk,
)
from app.services.ingestion_rag import ingest_pdf_document
from app.services.pdf_parser import PAGE_STATUS_TEXT, TEXT_LENGTH_THRESHOLD, parse_pdf_pages
from tests.pdf_fixtures import DeterministicFakeEmbeddingProvider, build_fixture_pdf, deterministic_vector

INTEGRATION_TEST_PREFIX = "integration_test_substep3_"

_build_fixture_pdf = build_fixture_pdf  # local alias, kept for minimal diff below
_deterministic_vector = deterministic_vector

_V1_PAGES = [
    "Sub-step 3 integration fixture, version 1, page 1.\n"
    "This paragraph exists only to give the structured_600_100 chunker\n"
    "enough text to work with, well past the near_empty/scanned threshold.\n"
    "It repeats a filler sentence several times for that purpose.\n"
    "Filler sentence filler sentence filler sentence filler sentence.\n"
    "Filler sentence filler sentence filler sentence filler sentence.",
    "Sub-step 3 integration fixture, version 1, page 2.\n"
    "A second page continues the same fixture document with different\n"
    "filler content, still deterministic and still synthetic test data.\n"
    "Filler sentence filler sentence filler sentence filler sentence.\n"
    "Filler sentence filler sentence filler sentence filler sentence.",
]

_V2_PAGES = [
    "Sub-step 3 integration fixture, version 2, page 1 -- CHANGED CONTENT.\n"
    "This version has different text from v1 so its document_content_hash\n"
    "and every chunk's embedding_content_hash differ from v1's.\n"
    "Different filler sentence different filler sentence different filler.\n"
    "Different filler sentence different filler sentence different filler.",
]

_V3_PAGES = [
    "Sub-step 3 integration fixture, version 3 (embedding-failure lineage), page 1.\n"
    "Independent lineage used only for the embedding-failure and\n"
    "cutover-rollback scenarios, kept separate from the v1/v2 supersede pair.\n"
    "Filler sentence filler sentence filler sentence filler sentence.\n"
    "Filler sentence filler sentence filler sentence filler sentence.\n"
    "Filler sentence filler sentence filler sentence filler sentence.",
    "Sub-step 3 integration fixture, version 3 (embedding-failure lineage), page 2.\n"
    "A second page of filler content, long enough that the structured_600_100\n"
    "chunker packs this document into more than one chunk, which is required\n"
    "for the embedding-failure scenario (one batch must succeed before another fails).\n"
    "Filler sentence filler sentence filler sentence filler sentence.\n"
    "Filler sentence filler sentence filler sentence filler sentence.",
]

_V3B_PAGES = [
    "Sub-step 3 integration fixture, version 3, revision B -- CHANGED CONTENT, page 1.\n"
    "Supersedes v3 within the same independent lineage, for the cutover\n"
    "transaction-failure/rollback and embedding-failure-then-retry scenarios.\n"
    "Different filler sentence different filler sentence different filler.\n"
    "Different filler sentence different filler sentence different filler.\n"
    "Different filler sentence different filler sentence different filler.",
    "Sub-step 3 integration fixture, version 3, revision B -- CHANGED CONTENT, page 2.\n"
    "A second page of different filler content, long enough that the\n"
    "structured_600_100 chunker packs this revision into more than one chunk\n"
    "too, for the same reason as revision v3's page 2 above.\n"
    "Different filler sentence different filler sentence different filler.\n"
    "Different filler sentence different filler sentence different filler.",
]


# ---------------------------------------------------------------------------
# DB fixture: real connection + guaranteed cleanup of this file's rows only
# ---------------------------------------------------------------------------


@pytest.fixture
def real_conn():
    with get_connection() as conn:
        try:
            yield conn
        finally:
            conn.rollback()  # discard anything left uncommitted by a failed assertion mid-test
            conn.execute(
                text(
                    "DELETE FROM document_chunks WHERE document_id IN "
                    "(SELECT id FROM documents WHERE file_name LIKE :prefix)"
                ),
                {"prefix": f"{INTEGRATION_TEST_PREFIX}%"},
            )
            conn.execute(
                text("DELETE FROM documents WHERE file_name LIKE :prefix AND supersedes_document_id IS NOT NULL"),
                {"prefix": f"{INTEGRATION_TEST_PREFIX}%"},
            )
            conn.execute(
                text("DELETE FROM documents WHERE file_name LIKE :prefix"),
                {"prefix": f"{INTEGRATION_TEST_PREFIX}%"},
            )
            conn.commit()


def _row_counts(conn) -> dict:
    documents = conn.execute(text("SELECT COUNT(*) FROM documents")).scalar_one()
    chunks = conn.execute(text("SELECT COUNT(*) FROM document_chunks")).scalar_one()
    return {"documents": documents, "document_chunks": chunks}


# ---------------------------------------------------------------------------
# Scenarios 1-4: first ingestion, exact duplicate, supersede, cutover
# ---------------------------------------------------------------------------


def test_scenarios_1_to_4_first_ingest_duplicate_supersede_cutover(real_conn, tmp_path):
    conn = real_conn
    before = _row_counts(conn)

    file_name = f"{INTEGRATION_TEST_PREFIX}lineage_a.pdf"
    v1_path = tmp_path / "v1.pdf"
    _build_fixture_pdf(v1_path, _V1_PAGES)

    # Fixture sanity check: pages must classify as "text", never scanned/near_empty.
    pages = parse_pdf_pages(str(v1_path))
    assert len(pages) == 2
    assert all(p.page_status == PAGE_STATUS_TEXT and p.char_count >= TEXT_LENGTH_THRESHOLD for p in pages)

    provider = DeterministicFakeEmbeddingProvider()

    # --- Scenario 1: first ingestion ---
    result_v1 = ingest_pdf_document(conn, str(v1_path), file_name, provider)

    assert result_v1.status == "ready"
    assert result_v1.stats.inserted_new >= 1

    doc_row = conn.execute(
        text("SELECT * FROM documents WHERE id = :id"), {"id": result_v1.document_id}
    ).mappings().first()
    assert doc_row["status"] == "ready"
    assert doc_row["document_content_hash"] == ingestion_rag.compute_document_content_hash(str(v1_path))

    v1_chunks = conn.execute(
        text("SELECT * FROM document_chunks WHERE document_id = :id"), {"id": result_v1.document_id}
    ).mappings().all()
    assert len(v1_chunks) == result_v1.stats.inserted_new
    for chunk in v1_chunks:
        assert chunk["document_id"] == result_v1.document_id
        assert chunk["is_active"] is True
        assert chunk["embedding_provider"] == "fake-deterministic"
        assert chunk["embedding_model"] == "fake-embedding-v1"
        assert chunk["embedding_dimensions"] == 1536

    # --- Scenario 2: exact duplicate ingestion ---
    counts_after_v1 = _row_counts(conn)
    duplicate_result = ingest_pdf_document(conn, str(v1_path), file_name, provider)
    counts_after_duplicate = _row_counts(conn)

    assert duplicate_result.status == "already_ingested"
    assert duplicate_result.document_id == result_v1.document_id
    assert counts_after_duplicate == counts_after_v1  # zero new rows
    assert provider.call_count == 1  # no re-embedding call from the duplicate attempt

    # --- Scenario 3: same file_name, changed content ---
    v2_path = tmp_path / "v2.pdf"
    _build_fixture_pdf(v2_path, _V2_PAGES)
    result_v2 = ingest_pdf_document(conn, str(v2_path), file_name, provider)

    assert result_v2.status == "ready"
    assert result_v2.document_id != result_v1.document_id
    v2_doc_row = conn.execute(
        text("SELECT * FROM documents WHERE id = :id"), {"id": result_v2.document_id}
    ).mappings().first()
    assert v2_doc_row["supersedes_document_id"] == result_v1.document_id
    assert v2_doc_row["document_content_hash"] != doc_row["document_content_hash"]

    # --- Scenario 4: blue-green cutover, verified via direct SQL ---
    v1_active_count = conn.execute(
        text("SELECT COUNT(*) FROM document_chunks WHERE document_id = :id AND is_active = true"),
        {"id": result_v1.document_id},
    ).scalar_one()
    v1_inactive_count = conn.execute(
        text("SELECT COUNT(*) FROM document_chunks WHERE document_id = :id AND is_active = false"),
        {"id": result_v1.document_id},
    ).scalar_one()
    v2_active_count = conn.execute(
        text("SELECT COUNT(*) FROM document_chunks WHERE document_id = :id AND is_active = true"),
        {"id": result_v2.document_id},
    ).scalar_one()

    assert v1_active_count == 0
    assert v1_inactive_count == len(v1_chunks)
    assert v2_active_count == result_v2.stats.inserted_new

    # No lineage member has both active and inactive chunks at once.
    for doc_id in (result_v1.document_id, result_v2.document_id):
        counts = get_chunk_activation_counts(conn, doc_id)
        assert not (counts["active"] > 0 and counts["inactive"] > 0)

    conn.commit()


# ---------------------------------------------------------------------------
# Scenario 5 + chief concern: embedding failure, then retry without PK collision
# ---------------------------------------------------------------------------


def test_scenario_5_embedding_failure_preserves_old_active_then_retry_succeeds(real_conn, tmp_path):
    conn = real_conn
    file_name = f"{INTEGRATION_TEST_PREFIX}lineage_b.pdf"

    v3_path = tmp_path / "v3.pdf"
    _build_fixture_pdf(v3_path, _V3_PAGES)
    good_provider = DeterministicFakeEmbeddingProvider()
    v1_result = ingest_pdf_document(conn, str(v3_path), file_name, good_provider)
    assert v1_result.status == "ready"

    v3b_path = tmp_path / "v3b.pdf"
    _build_fixture_pdf(v3b_path, _V3B_PAGES)

    # This fixture's chunker output has >= 2 chunks (two paragraphs across
    # different filler sentences); force failure on the 2nd embed_batch call
    # with embed_batch_size=1 so at least one chunk succeeds (and is
    # committed) before the failure.
    failing_provider = DeterministicFakeEmbeddingProvider(fail_on_call=2)
    failed_result = ingest_pdf_document(conn, str(v3b_path), file_name, failing_provider, embed_batch_size=1)

    assert failed_result.status == "failed"
    assert failed_result.stats.failed_chunk_ids

    failed_doc_row = conn.execute(
        text("SELECT * FROM documents WHERE id = :id"), {"id": failed_result.document_id}
    ).mappings().first()
    assert failed_doc_row["status"] == "failed"  # never left in "processing"

    # Old (v1) generation must remain fully active, untouched by the failure.
    v1_chunks = conn.execute(
        text("SELECT is_active FROM document_chunks WHERE document_id = :id"), {"id": v1_result.document_id}
    ).mappings().all()
    assert v1_chunks and all(row["is_active"] for row in v1_chunks)

    # Whatever new inactive chunks the failed attempt DID manage to commit
    # must all still be inactive -- not retrieval-visible.
    new_chunks_before_retry = conn.execute(
        text("SELECT is_active FROM document_chunks WHERE document_id = :id"), {"id": failed_result.document_id}
    ).mappings().all()
    assert all(not row["is_active"] for row in new_chunks_before_retry)
    committed_before_retry = len(new_chunks_before_retry)
    assert committed_before_retry == failed_result.stats.inserted_new

    # --- Chief concern: retry the exact same failed document_content_hash.
    # Must reuse the same document_id (no PK collision on the previously
    # committed inactive chunk_id(s)), must not re-embed what already
    # succeeded, and must complete this time. ---
    retry_provider = DeterministicFakeEmbeddingProvider()
    retry_result = ingest_pdf_document(conn, str(v3b_path), file_name, retry_provider, embed_batch_size=1)

    assert retry_result.document_id == failed_result.document_id  # same row reused, no second document
    assert retry_result.status == "ready"
    assert retry_result.stats.unchanged_skipped == committed_before_retry  # already-embedded chunk(s) recognized, not resent
    assert retry_provider.call_count == retry_result.stats.total_chunks_considered - committed_before_retry

    only_one_v3b_document = conn.execute(
        text("SELECT COUNT(*) FROM documents WHERE document_content_hash = :hash"),
        {"hash": failed_doc_row["document_content_hash"]},
    ).scalar_one()
    assert only_one_v3b_document == 1

    v1_chunks_after_retry = conn.execute(
        text("SELECT is_active FROM document_chunks WHERE document_id = :id"), {"id": v1_result.document_id}
    ).mappings().all()
    assert all(not row["is_active"] for row in v1_chunks_after_retry)  # correctly cut over now
    v3b_chunks_after_retry = conn.execute(
        text("SELECT is_active FROM document_chunks WHERE document_id = :id"), {"id": retry_result.document_id}
    ).mappings().all()
    assert all(row["is_active"] for row in v3b_chunks_after_retry)

    conn.commit()


# ---------------------------------------------------------------------------
# Scenario 6: cutover transaction failure / rollback (real Postgres transaction)
# ---------------------------------------------------------------------------


def test_scenario_6_cutover_transaction_failure_rolls_back_on_real_postgres(real_conn, tmp_path, monkeypatch):
    conn = real_conn
    file_name = f"{INTEGRATION_TEST_PREFIX}lineage_c.pdf"

    v1_path = tmp_path / "c_v1.pdf"
    _build_fixture_pdf(v1_path, _V3_PAGES)
    provider = DeterministicFakeEmbeddingProvider()
    v1_result = ingest_pdf_document(conn, str(v1_path), file_name, provider)
    assert v1_result.status == "ready"

    v2_path = tmp_path / "c_v2.pdf"
    _build_fixture_pdf(v2_path, _V3B_PAGES)

    def _activate_then_raise_before_deactivate(conn_, new_document_id, old_document_id):
        result = conn_.execute(
            text(
                "UPDATE document_chunks SET is_active = true, updated_at = now() "
                "WHERE document_id = :new_id AND is_active = false"
            ),
            {"new_id": new_document_id},
        )
        assert result.rowcount > 0
        raise RuntimeError("simulated cutover failure between activate and deactivate, on a real Postgres transaction")

    monkeypatch.setattr(ingestion_rag, "activate_new_and_deactivate_old_chunks", _activate_then_raise_before_deactivate)

    with pytest.raises(RuntimeError, match="simulated cutover failure"):
        ingest_pdf_document(conn, str(v2_path), file_name, DeterministicFakeEmbeddingProvider())

    # Old version must still be fully active; new version's activation must
    # have been rolled back (real Postgres transaction rollback, not a fake
    # undo-log) -- no partial cutover.
    v1_chunks = conn.execute(
        text("SELECT is_active FROM document_chunks WHERE document_id = :id"), {"id": v1_result.document_id}
    ).mappings().all()
    assert all(row["is_active"] for row in v1_chunks)

    v2_doc_row = conn.execute(
        text("SELECT * FROM documents WHERE file_name = :fn AND id != :v1_id"),
        {"fn": file_name, "v1_id": v1_result.document_id},
    ).mappings().first()
    assert v2_doc_row is not None
    assert v2_doc_row["status"] == "failed"

    v2_chunks = conn.execute(
        text("SELECT is_active FROM document_chunks WHERE document_id = :id"), {"id": v2_doc_row["id"]}
    ).mappings().all()
    assert v2_chunks  # the inactive rows themselves were committed (per-batch), just never activated
    assert all(not row["is_active"] for row in v2_chunks)

    # The connection's transaction state must still be usable after the
    # rollback (i.e. rollback() didn't leave the connection broken).
    sanity = conn.execute(text("SELECT 1")).scalar_one()
    assert sanity == 1

    conn.commit()


# ---------------------------------------------------------------------------
# Scenario 7: constraint / persistence integrity
# ---------------------------------------------------------------------------


def test_scenario_7_constraint_and_persistence_integrity(real_conn, tmp_path):
    conn = real_conn
    file_name = f"{INTEGRATION_TEST_PREFIX}lineage_d.pdf"

    v1_path = tmp_path / "d_v1.pdf"
    _build_fixture_pdf(v1_path, _V1_PAGES)
    provider = DeterministicFakeEmbeddingProvider()
    result = ingest_pdf_document(conn, str(v1_path), file_name, provider)
    assert result.status == "ready"
    conn.commit()

    # --- UNIQUE(document_content_hash) ---
    existing_hash = conn.execute(
        text("SELECT document_content_hash FROM documents WHERE id = :id"), {"id": result.document_id}
    ).scalar_one()
    with pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO documents (file_name, document_content_hash, status, uploaded_at) "
                "VALUES (:fn, :hash, 'processing', now())"
            ),
            {"fn": f"{INTEGRATION_TEST_PREFIX}duplicate_hash.pdf", "hash": existing_hash},
        )
    conn.rollback()

    # --- FK(document_chunks.document_id -> documents.id) ---
    with pytest.raises(IntegrityError):
        insert_inactive_chunk(
            conn,
            chunk_id=f"{INTEGRATION_TEST_PREFIX}orphan-chunk",
            document_id=-999999,
            strategy_name="structured_600_100",
            chunk_type="prose",
            content="orphan",
            embedding_content_hash="h",
            chunk_metadata_hash="h",
            page_index_start=0,
            page_index_end=0,
            pdf_page_number_start=1,
            pdf_page_number_end=1,
            printed_page_number_map={},
            section_title=None,
            table_title=None,
            embedding=_deterministic_vector("orphan"),
            embedding_provider="fake-deterministic",
            embedding_model="fake-embedding-v1",
            embedding_dimensions=1536,
            embedding_model_version="v1",
        )
    conn.rollback()

    # --- PK(document_chunks.chunk_id), bypassing insert_inactive_chunk's own
    # ON CONFLICT DO NOTHING to confirm the schema-level constraint itself ---
    existing_chunk_id = conn.execute(
        text("SELECT chunk_id FROM document_chunks WHERE document_id = :id LIMIT 1"), {"id": result.document_id}
    ).scalar_one()
    with pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO document_chunks (chunk_id, document_id, strategy_name, chunk_type, content, "
                "embedding_content_hash, chunk_metadata_hash, page_index_start, page_index_end, "
                "pdf_page_number_start, pdf_page_number_end, is_active) "
                "VALUES (:chunk_id, :document_id, 's', 'prose', 'x', 'h', 'h', 0, 0, 1, 1, false)"
            ),
            {"chunk_id": existing_chunk_id, "document_id": result.document_id},
        )
    conn.rollback()

    # --- JSONB round-trip ---
    active_chunks = get_active_chunks(conn, result.document_id)
    assert active_chunks
    sample = active_chunks[0]
    assert isinstance(sample["printed_page_number_map"], dict)
    assert sample["printed_page_number_map"]  # non-empty: at least one page mapped

    # --- vector(1536) round-trip ---
    embedding_text = conn.execute(
        text("SELECT embedding::text FROM document_chunks WHERE chunk_id = :id"), {"id": sample["chunk_id"]}
    ).scalar_one()
    stored_vector = [float(v) for v in embedding_text.strip("[]").split(",")]
    expected_vector = _deterministic_vector(sample["content"])
    assert len(stored_vector) == 1536
    assert all(abs(a - b) < 1e-4 for a, b in zip(stored_vector, expected_vector))

    # --- transaction rollback leaves no unexpected rows ---
    counts_before = _row_counts(conn)
    conn.execute(
        text(
            "INSERT INTO documents (file_name, document_content_hash, status, uploaded_at) "
            "VALUES (:fn, :hash, 'processing', now())"
        ),
        {"fn": f"{INTEGRATION_TEST_PREFIX}rollback_probe.pdf", "hash": f"{INTEGRATION_TEST_PREFIX}rollback-probe-hash"},
    )
    conn.rollback()
    counts_after = _row_counts(conn)
    assert counts_after == counts_before

    conn.commit()
