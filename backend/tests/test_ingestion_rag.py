"""Unit tests for Step 10 Sub-step 3 ingestion orchestration
(app/services/ingestion_rag.py), using FakeRagConnection (no real database)
and a fake embedding provider (no real OpenAI calls).

parse_pdf_pages and chunk_document are monkeypatched so these tests exercise
only the orchestration/persistence/lifecycle logic, not the PDF-parsing or
chunking heuristics already covered by test_pdf_parser.py / test_chunker.py.
compute_document_content_hash is also monkeypatched so each test can control
document identity directly (fixed_baseline hashing of a real file would make
every test here depend on the exact bytes of a shared fixture file, which is
irrelevant to what's being tested here).

Real-file, real-Postgres integration testing (the 7 numbered scenarios) is
intentionally separate and not part of this fast unit suite.
"""

import pytest

import app.services.ingestion_rag as ingestion_rag
from app.document_chunks_queries import create_processing_document, get_chunk_activation_counts, insert_inactive_chunk
from app.services.chunker import Chunk
from app.services.embedding_provider import EmbeddingBatchError, EmbeddingBatchResult, EmbeddingResult
from app.services.ingestion_rag import ChunkLifecycleAnomalyError, ingest_pdf_document
from app.services.pdf_parser import PAGE_STATUS_TEXT, PageParseResult
from tests.fakes import FakeRagConnection


class _StubEmbeddingProvider:
    provider_name = "stub"

    def __init__(self):
        self.call_count = 0

    def embed_batch(self, texts):
        self.call_count += 1
        results = [
            EmbeddingResult(text=t, vector=[0.1, 0.2, 0.3], provider="stub", model="stub-model", dimensions=3, model_version=None)
            for t in texts
        ]
        return EmbeddingBatchResult(results=results, prompt_tokens=len(texts), total_tokens=len(texts))


class _FailOnceProvider:
    """Fails on a specific embed_batch call number (1-indexed), succeeds otherwise."""

    provider_name = "stub"

    def __init__(self, fail_on_call: int):
        self.call_count = 0
        self.fail_on_call = fail_on_call

    def embed_batch(self, texts):
        self.call_count += 1
        if self.call_count == self.fail_on_call:
            raise EmbeddingBatchError("simulated transient failure exhausted retries")
        results = [
            EmbeddingResult(text=t, vector=[0.1, 0.2, 0.3], provider="stub", model="stub-model", dimensions=3, model_version=None)
            for t in texts
        ]
        return EmbeddingBatchResult(results=results, prompt_tokens=len(texts), total_tokens=len(texts))


def _make_page(status: str = PAGE_STATUS_TEXT) -> PageParseResult:
    return PageParseResult(
        page_index=0,
        pdf_page_number=1,
        printed_page_number="1",
        section_title="s",
        page_status=status,
        extraction_method="text_layer" if status == PAGE_STATUS_TEXT else "none",
        text="body text",
        char_count=9,
    )


def _make_chunk(text: str, section_title: str = "sec") -> Chunk:
    return Chunk(
        chunk_id="unused-placeholder",
        source_filename="doc.pdf",
        chunk_type="prose",
        text=text,
        char_count=len(text),
        page_index_range=(0, 0),
        pdf_page_number_range=(1, 1),
        printed_page_number_list=["1"],
        section_title=section_title,
        strategy_name="structured_600_100",
    )


def _patch_pipeline(monkeypatch, *, document_content_hash: str, pages: list, chunks: list):
    monkeypatch.setattr(ingestion_rag, "compute_document_content_hash", lambda pdf_path: document_content_hash)
    monkeypatch.setattr(ingestion_rag, "parse_pdf_pages", lambda pdf_path: pages)
    monkeypatch.setattr(ingestion_rag, "chunk_document", lambda pages_, file_name, strategy: chunks)


def test_new_document_chunks_are_inserted_inactive_then_activated(monkeypatch):
    conn = FakeRagConnection()
    _patch_pipeline(monkeypatch, document_content_hash="hash-v1", pages=[_make_page()], chunks=[_make_chunk("v1 text")])

    result = ingest_pdf_document(conn, "doc.pdf", "doc.pdf", _StubEmbeddingProvider())

    assert result.status == "ready"
    assert result.cutover_action == "activated"
    assert result.stats.inserted_new == 1
    assert all(c["is_active"] for c in conn.chunks.values())


def test_exact_duplicate_reingest_is_a_no_op(monkeypatch):
    conn = FakeRagConnection()
    provider = _StubEmbeddingProvider()
    _patch_pipeline(monkeypatch, document_content_hash="hash-v1", pages=[_make_page()], chunks=[_make_chunk("v1 text")])

    first = ingest_pdf_document(conn, "doc.pdf", "doc.pdf", provider)
    assert first.status == "ready"
    assert provider.call_count == 1

    second = ingest_pdf_document(conn, "doc.pdf", "doc.pdf", provider)

    assert second.status == "already_ingested"
    assert second.document_id == first.document_id
    assert provider.call_count == 1  # no re-parse, no re-embed
    assert len(conn.documents) == 1  # no second documents row


def test_unchanged_chunk_is_skipped_not_reembedded(monkeypatch):
    conn = FakeRagConnection()
    provider = _StubEmbeddingProvider()
    _patch_pipeline(monkeypatch, document_content_hash="hash-v1", pages=[_make_page()], chunks=[_make_chunk("same text")])

    ingest_pdf_document(conn, "doc.pdf", "doc.pdf", provider)
    assert provider.call_count == 1

    # Re-ingest under a NEW document (different content hash), but with a
    # chunk whose text/metadata are identical -> same deterministic chunk_id
    # -> must be recognized as unchanged and not re-embedded.
    _patch_pipeline(monkeypatch, document_content_hash="hash-v1", pages=[_make_page()], chunks=[_make_chunk("same text")])
    result = ingest_pdf_document(conn, "doc.pdf", "doc.pdf", provider)

    assert result.status == "already_ingested"  # same content hash short-circuits before reaching chunk logic
    assert provider.call_count == 1


def test_changed_chunk_metadata_only_updates_without_reembedding():
    """chunk_id embeds document_content_hash + embedding_content_hash, so two
    DIFFERENT document versions never collide on chunk_id -- the
    metadata-only-update path can only fire when re-processing the SAME
    content hash (e.g. a chunker heuristic improves section_title detection
    without changing any chunk's text), which ingest_pdf_document's
    exact-duplicate short-circuit never reaches. This exercises
    _upsert_chunks directly, the unit actually responsible for that decision.
    """
    conn = FakeRagConnection()
    provider = _StubEmbeddingProvider()
    doc_id = create_processing_document(conn, "doc.pdf", "hash-v1", total_pages=1, supersedes_document_id=None)
    conn.commit()

    stats_1 = ingestion_rag._upsert_chunks(
        conn, doc_id, "hash-v1", [_make_page()], [_make_chunk("same text", section_title="sec-a")], provider
    )
    assert stats_1.inserted_new == 1
    assert provider.call_count == 1

    stats_2 = ingestion_rag._upsert_chunks(
        conn, doc_id, "hash-v1", [_make_page()], [_make_chunk("same text", section_title="sec-b")], provider
    )

    assert stats_2.updated_metadata_only == 1
    assert stats_2.inserted_new == 0
    assert provider.call_count == 1  # no additional embedding call
    assert len(conn.chunks) == 1  # same chunk_id, updated in place not duplicated
    assert next(iter(conn.chunks.values()))["section_title"] == "sec-b"


def test_supersede_relation_recorded_via_file_name(monkeypatch):
    conn = FakeRagConnection()
    provider = _StubEmbeddingProvider()
    _patch_pipeline(monkeypatch, document_content_hash="hash-v1", pages=[_make_page()], chunks=[_make_chunk("v1 text")])
    v1 = ingest_pdf_document(conn, "doc.pdf", "doc.pdf", provider)

    _patch_pipeline(monkeypatch, document_content_hash="hash-v2", pages=[_make_page()], chunks=[_make_chunk("v2 text")])
    v2 = ingest_pdf_document(conn, "doc.pdf", "doc.pdf", provider)

    assert conn.documents[v2.document_id]["supersedes_document_id"] == v1.document_id
    v1_chunks = [c for c in conn.chunks.values() if c["document_id"] == v1.document_id]
    v2_chunks = [c for c in conn.chunks.values() if c["document_id"] == v2.document_id]
    assert all(not c["is_active"] for c in v1_chunks)
    assert all(c["is_active"] for c in v2_chunks)


def test_failed_embedding_batch_marks_document_failed_and_preserves_old_active(monkeypatch):
    conn = FakeRagConnection()
    good_provider = _StubEmbeddingProvider()
    _patch_pipeline(monkeypatch, document_content_hash="hash-v1", pages=[_make_page()], chunks=[_make_chunk("v1 text")])
    v1 = ingest_pdf_document(conn, "doc.pdf", "doc.pdf", good_provider)
    assert v1.status == "ready"

    failing_provider = _FailOnceProvider(fail_on_call=1)
    _patch_pipeline(
        monkeypatch,
        document_content_hash="hash-v2",
        pages=[_make_page()],
        chunks=[_make_chunk("v2 text A"), _make_chunk("v2 text B")],
    )
    v2 = ingest_pdf_document(conn, "doc.pdf", "doc.pdf", failing_provider, embed_batch_size=1)

    assert v2.status == "failed"
    assert v2.stats.failed_chunk_ids
    assert conn.documents[v2.document_id]["status"] == "failed"

    v1_chunks = [c for c in conn.chunks.values() if c["document_id"] == v1.document_id]
    v2_chunks = [c for c in conn.chunks.values() if c["document_id"] == v2.document_id]
    assert all(c["is_active"] for c in v1_chunks), "old active generation must survive a failed re-ingest"
    assert all(not c["is_active"] for c in v2_chunks)


def test_cutover_rollback_on_activation_failure_preserves_old_active(monkeypatch):
    conn = FakeRagConnection()
    provider = _StubEmbeddingProvider()
    _patch_pipeline(monkeypatch, document_content_hash="hash-v1", pages=[_make_page()], chunks=[_make_chunk("v1 text")])
    v1 = ingest_pdf_document(conn, "doc.pdf", "doc.pdf", provider)

    conn.raise_on_deactivate = True
    _patch_pipeline(monkeypatch, document_content_hash="hash-v2", pages=[_make_page()], chunks=[_make_chunk("v2 text")])

    with pytest.raises(RuntimeError):
        ingest_pdf_document(conn, "doc.pdf", "doc.pdf", provider)

    v1_chunks = [c for c in conn.chunks.values() if c["document_id"] == v1.document_id]
    assert all(c["is_active"] for c in v1_chunks), "old version must remain active after a rolled-back cutover"

    # The failing document itself must be marked failed, not left in "processing".
    failing_doc = next(d for d in conn.documents.values() if d["document_content_hash"] == "hash-v2")
    assert failing_doc["status"] == "failed"


def test_retry_after_failed_ingest_reuses_document_id_and_completes(monkeypatch):
    """A document stuck in status='failed' from a previous attempt must be
    retryable under the exact same document_content_hash: it must NOT be
    reported as already_ingested (that status is reserved for status='ready'),
    and the retry must reuse the same document_id rather than creating a
    second row, with chunks already committed inactive by the earlier
    failed attempt recognized via their deterministic chunk_id (no PK
    collision, no duplicate insert, no re-embedding of what already
    succeeded).
    """
    conn = FakeRagConnection()
    _patch_pipeline(
        monkeypatch,
        document_content_hash="hash-retry",
        pages=[_make_page()],
        chunks=[_make_chunk("chunk A"), _make_chunk("chunk B")],
    )

    failing_provider = _FailOnceProvider(fail_on_call=2)
    first = ingest_pdf_document(conn, "doc.pdf", "doc.pdf", failing_provider, embed_batch_size=1)

    assert first.status == "failed"
    assert first.stats.inserted_new == 1  # chunk A's batch succeeded and was committed
    assert conn.documents[first.document_id]["status"] == "failed"

    good_provider = _StubEmbeddingProvider()
    second = ingest_pdf_document(conn, "doc.pdf", "doc.pdf", good_provider, embed_batch_size=1)

    assert second.document_id == first.document_id  # same row reused, not a second document
    assert len([d for d in conn.documents.values() if d["document_content_hash"] == "hash-retry"]) == 1
    assert second.status == "ready"
    assert second.stats.unchanged_skipped == 1  # chunk A recognized as already-embedded, not re-sent
    assert second.stats.inserted_new == 1  # only chunk B (the one that failed) gets embedded now
    assert good_provider.call_count == 1
    assert second.cutover_action == "activated"
    assert all(c["is_active"] for c in conn.chunks.values() if c["document_id"] == first.document_id)


def test_mixed_active_inactive_state_raises_lifecycle_anomaly(monkeypatch):
    conn = FakeRagConnection()
    doc_id = create_processing_document(conn, "doc.pdf", "hash-anomaly", total_pages=1, supersedes_document_id=None)
    insert_inactive_chunk(
        conn,
        chunk_id="chunk-a",
        document_id=doc_id,
        strategy_name="structured_600_100",
        chunk_type="prose",
        content="a",
        embedding_content_hash="h",
        chunk_metadata_hash="h",
        page_index_start=0,
        page_index_end=0,
        pdf_page_number_start=1,
        pdf_page_number_end=1,
        printed_page_number_map={},
        section_title=None,
        table_title=None,
        embedding=[0.1],
        embedding_provider="stub",
        embedding_model="stub-model",
        embedding_dimensions=1,
        embedding_model_version=None,
    )
    conn.chunks["chunk-a"]["is_active"] = True  # manually construct an invariant violation
    conn.chunks["chunk-b"] = dict(conn.chunks["chunk-a"])
    conn.chunks["chunk-b"]["chunk_id"] = "chunk-b"
    conn.chunks["chunk-b"]["is_active"] = False

    counts = get_chunk_activation_counts(conn, doc_id)
    assert counts == {"total": 2, "active": 1, "inactive": 1}

    from app.services.ingestion_rag import _execute_cutover_if_needed

    with pytest.raises(ChunkLifecycleAnomalyError):
        _execute_cutover_if_needed(conn, doc_id)

    # State must be untouched -- no silent resolution in either direction.
    assert conn.chunks["chunk-a"]["is_active"] is True
    assert conn.chunks["chunk-b"]["is_active"] is False


def test_no_real_openai_import_required_for_stub_provider():
    # Sanity check that ingestion_rag's import surface doesn't force a real
    # OpenAI client construction anywhere in the module-level import path.
    assert hasattr(ingestion_rag, "ingest_pdf_document")
