"""Tests for Step 6 Sub-step 6 blue-green chunk lifecycle logic.

Uses an in-memory fake connection (with a real transactional undo log, so
commit()/rollback() behave like a real single-connection transaction: writes
are visible to subsequent reads on the same connection immediately, but are
only made permanent on commit() and are reverted on rollback()). This is not
a real database and does not validate raw SQL correctness -- that is covered
by the manual integration smoke test against the real Docker Postgres +
pgvector container (see spike/run_embedding_ingestion.py), consistent with
the existing test_vector_store.py fake.

Run from the project root: python -m pytest spike/tests -v
"""

from spike.chunker import Chunk
from spike.embedding_provider import EmbeddingBatchError, EmbeddingBatchResult, EmbeddingResult
from spike.pdf_parser import PageParseResult
from spike.vector_store import (
    ChunkLifecycleAnomalyError,
    cutover_document_version,
    execute_cutover_if_needed,
    get_or_create_document,
    upsert_chunks,
)


class _FakeExecResult:
    def __init__(self, rows=None, scalar=None, rowcount=0):
        self._rows = rows or []
        self._scalar = scalar
        self.rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one(self):
        return self._scalar


class FakeLifecycleConnection:
    """In-memory stand-in for the subset of a SQLAlchemy Connection used by
    spike/vector_store.py's document/chunk lifecycle functions."""

    def __init__(self):
        self.documents: dict[int, dict] = {}
        self.chunks: dict[str, dict] = {}
        self._next_doc_id = 1
        self._undo_log: list = []
        self.raise_on_deactivate = False  # test hook for simulating cutover failure

    def _stage(self, undo_fn):
        self._undo_log.append(undo_fn)

    def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}

        if "SELECT id FROM spike_documents WHERE document_content_hash" in sql:
            for doc_id, doc in self.documents.items():
                if doc["hash"] == params["h"]:
                    return _FakeExecResult(rows=[{"id": doc_id}])
            return _FakeExecResult(rows=[])

        if "SELECT DISTINCT d.id" in sql:
            for doc_id, doc in self.documents.items():
                if doc["filename"] == params["filename"] and any(
                    c["document_id"] == doc_id and c["is_active"] for c in self.chunks.values()
                ):
                    return _FakeExecResult(rows=[{"id": doc_id}])
            return _FakeExecResult(rows=[])

        if "INSERT INTO spike_documents" in sql:
            doc_id = self._next_doc_id
            self._next_doc_id += 1
            self.documents[doc_id] = {
                "filename": params["filename"],
                "hash": params["hash"],
                "total_pages": params["pages"],
                "supersedes_document_id": params["supersedes"],
            }
            self._stage(lambda d=doc_id: self.documents.pop(d, None))
            return _FakeExecResult(scalar=doc_id)

        if "SELECT chunk_id, chunk_metadata_hash FROM spike_document_chunks" in sql:
            ids = params["ids"]
            rows = [
                {"chunk_id": cid, "chunk_metadata_hash": self.chunks[cid]["chunk_metadata_hash"]}
                for cid in ids
                if cid in self.chunks
            ]
            return _FakeExecResult(rows=rows)

        if "INSERT INTO spike_document_chunks" in sql:
            cid = params["chunk_id"]
            self.chunks[cid] = {
                "document_id": params["document_id"],
                "chunk_metadata_hash": params["chunk_metadata_hash"],
                "is_active": params["is_active"],
            }
            self._stage(lambda c=cid: self.chunks.pop(c, None))
            return _FakeExecResult()

        if "SET chunk_metadata_hash" in sql:
            cid = params["chunk_id"]
            if cid in self.chunks:
                old_hash = self.chunks[cid]["chunk_metadata_hash"]
                self.chunks[cid]["chunk_metadata_hash"] = params["chunk_metadata_hash"]
                self._stage(lambda c=cid, h=old_hash: self.chunks[c].__setitem__("chunk_metadata_hash", h))
            return _FakeExecResult()

        if "COUNT(*) AS total" in sql:
            doc_id = params["document_id"]
            total = active = inactive = 0
            for c in self.chunks.values():
                if c["document_id"] == doc_id:
                    total += 1
                    active += 1 if c["is_active"] else 0
                    inactive += 1 if not c["is_active"] else 0
            return _FakeExecResult(rows=[{"total": total, "active": active, "inactive": inactive}])

        if "is_active = true" in sql and "new_id" in params:
            new_id = params["new_id"]
            count = 0
            for c in self.chunks.values():
                if c["document_id"] == new_id and not c["is_active"]:
                    c["is_active"] = True
                    count += 1
                    self._stage(lambda cc=c: cc.__setitem__("is_active", False))
            return _FakeExecResult(rowcount=count)

        if "is_active = false" in sql and "old_id" in params:
            if self.raise_on_deactivate:
                raise RuntimeError("simulated cutover failure")
            old_id = params["old_id"]
            for c in self.chunks.values():
                if c["document_id"] == old_id and c["is_active"]:
                    c["is_active"] = False
                    self._stage(lambda cc=c: cc.__setitem__("is_active", True))
            return _FakeExecResult()

        if "SELECT supersedes_document_id FROM spike_documents" in sql:
            doc = self.documents.get(params["id"])
            return _FakeExecResult(rows=[{"supersedes_document_id": doc["supersedes_document_id"]}] if doc else [])

        return _FakeExecResult()

    def commit(self):
        self._undo_log.clear()

    def rollback(self):
        while self._undo_log:
            self._undo_log.pop()()


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
    """Fails on a specific call number (1-indexed), succeeds otherwise."""

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


def _make_page() -> PageParseResult:
    return PageParseResult(
        page_index=0,
        pdf_page_number=1,
        printed_page_number="1",
        section_title="s",
        page_status="text",
        extraction_method="text_layer",
        text="",
        char_count=0,
    )


def _make_chunk(text: str) -> Chunk:
    return Chunk(
        chunk_id="unused-placeholder",
        source_filename="doc.pdf",
        chunk_type="prose",
        text=text,
        char_count=len(text),
        page_index_range=(0, 0),
        pdf_page_number_range=(1, 1),
        printed_page_number_list=["1"],
        section_title="sec",
        strategy_name="structured_600_100",
    )


def test_new_chunks_are_written_inactive_by_default():
    conn = FakeLifecycleConnection()
    provider = _StubEmbeddingProvider()
    doc_id = get_or_create_document(conn, "doc.pdf", "hash-v1", total_pages=1)
    upsert_chunks(conn, doc_id, "hash-v1", [_make_page()], [_make_chunk("v1 text")], provider)

    assert all(c["is_active"] is False for c in conn.chunks.values())


def test_same_content_rerun_produces_no_lifecycle_change():
    conn = FakeLifecycleConnection()
    provider = _StubEmbeddingProvider()
    doc_id = get_or_create_document(conn, "doc.pdf", "hash-v1", total_pages=1)
    upsert_chunks(conn, doc_id, "hash-v1", [_make_page()], [_make_chunk("v1 text")], provider)
    execute_cutover_if_needed(conn, doc_id)  # bring v1 live

    # Re-run with identical content: same document_id, same chunk_id, nothing new to embed.
    doc_id_again = get_or_create_document(conn, "doc.pdf", "hash-v1", total_pages=1)
    stats = upsert_chunks(conn, doc_id_again, "hash-v1", [_make_page()], [_make_chunk("v1 text")], provider)
    action = execute_cutover_if_needed(conn, doc_id_again)

    assert doc_id_again == doc_id
    assert stats.embedding_api_calls == 0
    assert stats.unchanged_skipped == 1
    assert action == "already_active"
    assert all(c["is_active"] is True for c in conn.chunks.values())


def test_full_success_activates_new_and_deactivates_old():
    conn = FakeLifecycleConnection()
    provider = _StubEmbeddingProvider()

    doc_v1 = get_or_create_document(conn, "doc.pdf", "hash-v1", total_pages=1)
    upsert_chunks(conn, doc_v1, "hash-v1", [_make_page()], [_make_chunk("v1 text")], provider)
    assert execute_cutover_if_needed(conn, doc_v1) == "activated"

    doc_v2 = get_or_create_document(conn, "doc.pdf", "hash-v2", total_pages=1)
    assert conn.documents[doc_v2]["supersedes_document_id"] == doc_v1
    upsert_chunks(conn, doc_v2, "hash-v2", [_make_page()], [_make_chunk("v2 text")], provider)
    action = execute_cutover_if_needed(conn, doc_v2)

    assert action == "activated"
    v1_chunks = [c for c in conn.chunks.values() if c["document_id"] == doc_v1]
    v2_chunks = [c for c in conn.chunks.values() if c["document_id"] == doc_v2]
    assert all(c["is_active"] is False for c in v1_chunks)  # old deactivated, still present (not deleted)
    assert all(c["is_active"] is True for c in v2_chunks)
    assert len(v1_chunks) == 1 and len(v2_chunks) == 1


def test_partial_embedding_failure_leaves_old_active_new_inactive():
    conn = FakeLifecycleConnection()
    good_provider = _StubEmbeddingProvider()

    doc_v1 = get_or_create_document(conn, "doc.pdf", "hash-v1", total_pages=1)
    upsert_chunks(conn, doc_v1, "hash-v1", [_make_page()], [_make_chunk("v1 text")], good_provider)
    execute_cutover_if_needed(conn, doc_v1)

    # v2 has two chunks embedded one-batch-at-a-time; the 2nd batch fails.
    failing_provider = _FailOnceProvider(fail_on_call=2)
    doc_v2 = get_or_create_document(conn, "doc.pdf", "hash-v2", total_pages=1)
    stats = upsert_chunks(
        conn, doc_v2, "hash-v2", [_make_page()], [_make_chunk("v2 text A"), _make_chunk("v2 text B")],
        failing_provider, embed_batch_size=1,
    )

    assert stats.failed_chunk_ids  # a real failure occurred
    # Per the documented contract, the caller must NOT invoke cutover when
    # failed_chunk_ids is non-empty -- we do not call it here, and assert the
    # resulting state directly.
    v1_chunks = [c for c in conn.chunks.values() if c["document_id"] == doc_v1]
    v2_chunks = [c for c in conn.chunks.values() if c["document_id"] == doc_v2]
    assert all(c["is_active"] is True for c in v1_chunks)
    assert all(c["is_active"] is False for c in v2_chunks)
    assert len(v2_chunks) == 1  # only the successful chunk landed


def test_cutover_transaction_failure_rolls_back_completely():
    conn = FakeLifecycleConnection()
    provider = _StubEmbeddingProvider()

    doc_v1 = get_or_create_document(conn, "doc.pdf", "hash-v1", total_pages=1)
    upsert_chunks(conn, doc_v1, "hash-v1", [_make_page()], [_make_chunk("v1 text")], provider)
    execute_cutover_if_needed(conn, doc_v1)

    doc_v2 = get_or_create_document(conn, "doc.pdf", "hash-v2", total_pages=1)
    upsert_chunks(conn, doc_v2, "hash-v2", [_make_page()], [_make_chunk("v2 text")], provider)

    conn.raise_on_deactivate = True
    try:
        cutover_document_version(conn, new_document_id=doc_v2, old_document_id=doc_v1)
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass

    v1_chunks = [c for c in conn.chunks.values() if c["document_id"] == doc_v1]
    v2_chunks = [c for c in conn.chunks.values() if c["document_id"] == doc_v2]
    assert all(c["is_active"] is True for c in v1_chunks), "old version must remain active after rollback"
    assert all(c["is_active"] is False for c in v2_chunks), "new version's activation must be rolled back too"


def test_retry_after_partial_failure_eventually_completes_cutover():
    conn = FakeLifecycleConnection()
    provider = _StubEmbeddingProvider()

    doc_v1 = get_or_create_document(conn, "doc.pdf", "hash-v1", total_pages=1)
    upsert_chunks(conn, doc_v1, "hash-v1", [_make_page()], [_make_chunk("v1 text")], provider)
    execute_cutover_if_needed(conn, doc_v1)

    chunks_v2 = [_make_chunk("v2 text A"), _make_chunk("v2 text B")]
    failing_provider = _FailOnceProvider(fail_on_call=2)
    doc_v2 = get_or_create_document(conn, "doc.pdf", "hash-v2", total_pages=1)
    stats1 = upsert_chunks(conn, doc_v2, "hash-v2", [_make_page()], chunks_v2, failing_provider, embed_batch_size=1)
    assert stats1.failed_chunk_ids

    # Retry: same document_content_hash -> same document_id; only the missing
    # chunk needs to be (re)attempted.
    doc_v2_retry = get_or_create_document(conn, "doc.pdf", "hash-v2", total_pages=1)
    assert doc_v2_retry == doc_v2
    good_provider = _StubEmbeddingProvider()
    stats2 = upsert_chunks(conn, doc_v2_retry, "hash-v2", [_make_page()], chunks_v2, good_provider, embed_batch_size=1)
    assert not stats2.failed_chunk_ids

    action = execute_cutover_if_needed(conn, doc_v2_retry)
    assert action == "activated"

    v1_chunks = [c for c in conn.chunks.values() if c["document_id"] == doc_v1]
    v2_chunks = [c for c in conn.chunks.values() if c["document_id"] == doc_v2]
    assert all(c["is_active"] is False for c in v1_chunks)
    assert all(c["is_active"] is True for c in v2_chunks)
    assert len(v2_chunks) == 2


def test_mixed_active_inactive_state_raises_anomaly_and_does_not_switch():
    conn = FakeLifecycleConnection()
    doc_id = get_or_create_document(conn, "doc.pdf", "hash-v1", total_pages=1)
    # Manually construct an invariant-violating state: one active, one inactive
    # chunk under the same document_id (should never happen via normal code paths).
    conn.chunks["chunk-a"] = {"document_id": doc_id, "chunk_metadata_hash": "h", "is_active": True}
    conn.chunks["chunk-b"] = {"document_id": doc_id, "chunk_metadata_hash": "h", "is_active": False}

    try:
        execute_cutover_if_needed(conn, doc_id)
        assert False, "expected ChunkLifecycleAnomalyError"
    except ChunkLifecycleAnomalyError:
        pass

    # State must be untouched -- no silent resolution in either direction.
    assert conn.chunks["chunk-a"]["is_active"] is True
    assert conn.chunks["chunk-b"]["is_active"] is False


def test_metadata_only_update_does_not_change_is_active():
    conn = FakeLifecycleConnection()
    provider = _StubEmbeddingProvider()
    doc_id = get_or_create_document(conn, "doc.pdf", "hash-v1", total_pages=1)
    upsert_chunks(conn, doc_id, "hash-v1", [_make_page()], [_make_chunk("same text")], provider)
    execute_cutover_if_needed(conn, doc_id)
    assert all(c["is_active"] is True for c in conn.chunks.values())

    changed_metadata_chunk = _make_chunk("same text")
    changed_metadata_chunk.section_title = "a different section title"
    stats = upsert_chunks(conn, doc_id, "hash-v1", [_make_page()], [changed_metadata_chunk], provider)

    assert stats.updated_metadata_only == 1
    assert all(c["is_active"] is True for c in conn.chunks.values())


def test_first_ingestion_has_no_supersedes_and_cutover_only_activates():
    conn = FakeLifecycleConnection()
    provider = _StubEmbeddingProvider()
    doc_id = get_or_create_document(conn, "doc.pdf", "hash-v1", total_pages=1)
    assert conn.documents[doc_id]["supersedes_document_id"] is None
    upsert_chunks(conn, doc_id, "hash-v1", [_make_page()], [_make_chunk("v1 text")], provider)

    action = execute_cutover_if_needed(conn, doc_id)
    assert action == "activated"
    assert all(c["is_active"] is True for c in conn.chunks.values())
