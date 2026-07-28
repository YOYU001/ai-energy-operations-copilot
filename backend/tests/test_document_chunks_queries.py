"""Unit tests for Step 10 Sub-step 3 query-layer primitives (documents /
document_chunks), using FakeRagConnection (backend/tests/fakes.py) -- no
real database. These test the primitives in isolation; app/services/
ingestion_rag.py's orchestration behavior is covered separately in
test_ingestion_rag.py.
"""

from app.document_chunks_queries import (
    activate_new_and_deactivate_old_chunks,
    create_processing_document,
    find_supersede_candidate,
    get_active_chunks,
    get_chunk_activation_counts,
    get_document_by_content_hash,
    get_document_by_id,
    get_existing_chunk_hashes,
    insert_inactive_chunk,
    update_chunk_metadata,
    update_document_status,
)
from tests.fakes import FakeRagConnection

import pytest


def _insert_chunk(conn, chunk_id, document_id, chunk_metadata_hash="meta-v1", strategy_name="structured_600_100"):
    return insert_inactive_chunk(
        conn,
        chunk_id=chunk_id,
        document_id=document_id,
        strategy_name=strategy_name,
        chunk_type="prose",
        content="some text",
        embedding_content_hash="embed-hash",
        chunk_metadata_hash=chunk_metadata_hash,
        page_index_start=0,
        page_index_end=0,
        pdf_page_number_start=1,
        pdf_page_number_end=1,
        printed_page_number_map={"1": "1"},
        section_title=None,
        table_title=None,
        embedding=[0.1, 0.2, 0.3],
        embedding_provider="stub",
        embedding_model="stub-model",
        embedding_dimensions=3,
        embedding_model_version=None,
    )


def test_get_document_by_content_hash_returns_none_when_absent():
    conn = FakeRagConnection()
    assert get_document_by_content_hash(conn, "missing-hash") is None


def test_create_and_get_document_by_content_hash_and_id():
    conn = FakeRagConnection()
    doc_id = create_processing_document(conn, "a.pdf", "hash-1", total_pages=3, supersedes_document_id=None)

    by_hash = get_document_by_content_hash(conn, "hash-1")
    by_id = get_document_by_id(conn, doc_id)

    assert by_hash["id"] == doc_id
    assert by_hash["status"] == "processing"
    assert by_id["file_name"] == "a.pdf"
    assert by_id["total_pages"] == 3
    assert by_id["supersedes_document_id"] is None


def test_get_document_by_id_returns_none_when_absent():
    conn = FakeRagConnection()
    assert get_document_by_id(conn, 999) is None


def test_find_supersede_candidate_requires_an_active_chunk():
    conn = FakeRagConnection()
    doc_id = create_processing_document(conn, "a.pdf", "hash-1", total_pages=1, supersedes_document_id=None)

    # No chunks yet: not a supersede candidate.
    assert find_supersede_candidate(conn, "a.pdf") is None

    _insert_chunk(conn, "chunk-1", doc_id)
    # Chunk exists but is still inactive: not yet a candidate.
    assert find_supersede_candidate(conn, "a.pdf") is None

    activate_new_and_deactivate_old_chunks(conn, new_document_id=doc_id, old_document_id=None)
    assert find_supersede_candidate(conn, "a.pdf") == doc_id


def test_update_document_status_and_total_pages():
    conn = FakeRagConnection()
    doc_id = create_processing_document(conn, "a.pdf", "hash-1", total_pages=1, supersedes_document_id=None)

    update_document_status(conn, doc_id, "ready")
    assert get_document_by_id(conn, doc_id)["status"] == "ready"


def test_insert_inactive_chunk_is_inactive_by_default_and_idempotent_on_conflict():
    conn = FakeRagConnection()
    doc_id = create_processing_document(conn, "a.pdf", "hash-1", total_pages=1, supersedes_document_id=None)

    inserted_first = _insert_chunk(conn, "chunk-1", doc_id)
    inserted_again = _insert_chunk(conn, "chunk-1", doc_id)  # ON CONFLICT DO NOTHING

    assert inserted_first is True
    assert inserted_again is False
    assert conn.chunks["chunk-1"]["is_active"] is False


def test_get_existing_chunk_hashes_returns_only_known_ids():
    conn = FakeRagConnection()
    doc_id = create_processing_document(conn, "a.pdf", "hash-1", total_pages=1, supersedes_document_id=None)
    _insert_chunk(conn, "chunk-1", doc_id, chunk_metadata_hash="meta-a")

    result = get_existing_chunk_hashes(conn, ["chunk-1", "chunk-missing"])

    assert result == {"chunk-1": "meta-a"}


def test_get_existing_chunk_hashes_empty_list_short_circuits():
    conn = FakeRagConnection()
    assert get_existing_chunk_hashes(conn, []) == {}


def test_update_chunk_metadata_does_not_touch_is_active_or_content():
    conn = FakeRagConnection()
    doc_id = create_processing_document(conn, "a.pdf", "hash-1", total_pages=1, supersedes_document_id=None)
    _insert_chunk(conn, "chunk-1", doc_id, chunk_metadata_hash="meta-a")

    update_chunk_metadata(
        conn,
        chunk_id="chunk-1",
        chunk_metadata_hash="meta-b",
        section_title="new section",
        table_title=None,
        printed_page_number_map={"1": "i"},
    )

    chunk = conn.chunks["chunk-1"]
    assert chunk["chunk_metadata_hash"] == "meta-b"
    assert chunk["section_title"] == "new section"
    assert chunk["is_active"] is False  # untouched


def test_get_chunk_activation_counts():
    conn = FakeRagConnection()
    doc_id = create_processing_document(conn, "a.pdf", "hash-1", total_pages=1, supersedes_document_id=None)
    _insert_chunk(conn, "chunk-1", doc_id)
    _insert_chunk(conn, "chunk-2", doc_id)

    counts = get_chunk_activation_counts(conn, doc_id)
    assert counts == {"total": 2, "active": 0, "inactive": 2}

    activate_new_and_deactivate_old_chunks(conn, new_document_id=doc_id, old_document_id=None)
    counts = get_chunk_activation_counts(conn, doc_id)
    assert counts == {"total": 2, "active": 2, "inactive": 0}


def test_get_active_chunks_filters_by_strategy_and_activity():
    conn = FakeRagConnection()
    doc_id = create_processing_document(conn, "a.pdf", "hash-1", total_pages=1, supersedes_document_id=None)
    _insert_chunk(conn, "chunk-1", doc_id, strategy_name="structured_600_100")
    _insert_chunk(conn, "chunk-2", doc_id, strategy_name="fixed_baseline_600_100")

    assert get_active_chunks(conn, doc_id) == []  # still inactive

    activate_new_and_deactivate_old_chunks(conn, new_document_id=doc_id, old_document_id=None)

    assert len(get_active_chunks(conn, doc_id)) == 2
    assert len(get_active_chunks(conn, doc_id, strategy_name="structured_600_100")) == 1


def test_activate_new_and_deactivate_old_chunks_full_cutover():
    conn = FakeRagConnection()
    doc_v1 = create_processing_document(conn, "a.pdf", "hash-1", total_pages=1, supersedes_document_id=None)
    _insert_chunk(conn, "chunk-v1", doc_v1)
    activate_new_and_deactivate_old_chunks(conn, new_document_id=doc_v1, old_document_id=None)

    doc_v2 = create_processing_document(conn, "a.pdf", "hash-2", total_pages=1, supersedes_document_id=doc_v1)
    _insert_chunk(conn, "chunk-v2", doc_v2)

    activated = activate_new_and_deactivate_old_chunks(conn, new_document_id=doc_v2, old_document_id=doc_v1)

    assert activated == 1
    assert conn.chunks["chunk-v1"]["is_active"] is False
    assert conn.chunks["chunk-v2"]["is_active"] is True


def test_activate_new_and_deactivate_old_chunks_raises_when_nothing_to_activate():
    conn = FakeRagConnection()
    doc_v1 = create_processing_document(conn, "a.pdf", "hash-1", total_pages=1, supersedes_document_id=None)
    _insert_chunk(conn, "chunk-v1", doc_v1)
    activate_new_and_deactivate_old_chunks(conn, new_document_id=doc_v1, old_document_id=None)

    # doc_v2 has zero inactive chunks (none inserted) -- must refuse to touch doc_v1.
    doc_v2 = create_processing_document(conn, "a.pdf", "hash-2", total_pages=1, supersedes_document_id=doc_v1)

    with pytest.raises(RuntimeError):
        activate_new_and_deactivate_old_chunks(conn, new_document_id=doc_v2, old_document_id=doc_v1)

    assert conn.chunks["chunk-v1"]["is_active"] is True  # untouched
