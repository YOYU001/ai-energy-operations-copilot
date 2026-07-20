"""Tests for Step 6 Sub-step 4 vector_store idempotency logic.

Uses an in-memory fake connection that exercises the Python-side
to_embed/to_update/unchanged branching and batching logic in
spike/vector_store.py. It is not a real database and does not validate raw
SQL correctness -- that is covered by the manual integration smoke test
against the real Docker Postgres + pgvector container (see
spike/run_embedding_ingestion.py), not by this pytest suite.

Run from the project root: python -m pytest spike/tests -v
"""

from spike.chunker import Chunk
from spike.embedding_provider import EmbeddingBatchResult, EmbeddingResult
from spike.pdf_parser import PageParseResult
from spike.vector_store import upsert_chunks


class _FakeExecResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one(self):
        return self._scalar


class FakeVectorStoreConnection:
    """Minimal in-memory stand-in for the subset of a SQLAlchemy Connection
    used by spike/vector_store.py."""

    def __init__(self):
        self.documents: dict[str, int] = {}
        self.chunks: dict[str, dict] = {}
        self._next_doc_id = 1
        self.executed: list = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append((sql, params))
        params = params or {}

        if "SELECT id FROM spike_documents" in sql:
            doc_id = self.documents.get(params["h"])
            return _FakeExecResult(rows=[{"id": doc_id}] if doc_id else [])

        if "INSERT INTO spike_documents" in sql:
            doc_id = self._next_doc_id
            self._next_doc_id += 1
            self.documents[params["hash"]] = doc_id
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
            self.chunks[cid] = {"chunk_metadata_hash": params["chunk_metadata_hash"]}
            return _FakeExecResult()

        if "UPDATE spike_document_chunks" in sql:
            cid = params["chunk_id"]
            if cid in self.chunks:
                self.chunks[cid]["chunk_metadata_hash"] = params["chunk_metadata_hash"]
            return _FakeExecResult()

        return _FakeExecResult()

    def commit(self):
        pass


class _StubEmbeddingProvider:
    provider_name = "stub"
    model_name = "stub-model"
    dimensions = 3

    def __init__(self):
        self.call_count = 0
        self.embedded_texts: list[str] = []

    def embed_batch(self, texts):
        self.call_count += 1
        self.embedded_texts.extend(texts)
        results = [
            EmbeddingResult(text=t, vector=[0.1, 0.2, 0.3], provider="stub", model="stub-model", dimensions=3, model_version=None)
            for t in texts
        ]
        return EmbeddingBatchResult(results=results, prompt_tokens=len(texts), total_tokens=len(texts))


def _make_page(page_index: int) -> PageParseResult:
    return PageParseResult(
        page_index=page_index,
        pdf_page_number=page_index + 1,
        printed_page_number=str(page_index + 1),
        section_title="s",
        page_status="text",
        extraction_method="text_layer",
        text="",
        char_count=0,
    )


def _make_chunk(text: str, section_title="四、實驗結果", page_index_range=(0, 0)) -> Chunk:
    return Chunk(
        chunk_id="unused-placeholder",  # vector_store recomputes a deterministic chunk_id; this field is not trusted
        source_filename="doc.pdf",
        chunk_type="prose",
        text=text,
        char_count=len(text),
        page_index_range=page_index_range,
        pdf_page_number_range=(page_index_range[0] + 1, page_index_range[1] + 1),
        printed_page_number_list=[str(page_index_range[0] + 1)],
        section_title=section_title,
        strategy_name="structured_600_100",
    )


def test_first_ingestion_embeds_and_inserts_all_new_chunks():
    conn = FakeVectorStoreConnection()
    provider = _StubEmbeddingProvider()
    pages = [_make_page(0)]
    chunks = [_make_chunk("chunk one text"), _make_chunk("chunk two text")]

    stats = upsert_chunks(conn, document_id=1, document_content_hash="doc-hash-A", pages=pages, chunks=chunks, provider=provider)

    assert stats.inserted_new == 2
    assert stats.unchanged_skipped == 0
    assert stats.updated_metadata_only == 0
    assert stats.embedding_api_calls == 1  # single batch call for both chunks
    assert provider.call_count == 1


def test_second_ingestion_of_identical_input_makes_zero_new_embedding_calls():
    conn = FakeVectorStoreConnection()
    provider = _StubEmbeddingProvider()
    pages = [_make_page(0)]
    chunks = [_make_chunk("chunk one text"), _make_chunk("chunk two text")]

    upsert_chunks(conn, document_id=1, document_content_hash="doc-hash-A", pages=pages, chunks=chunks, provider=provider)
    stats_second_run = upsert_chunks(conn, document_id=1, document_content_hash="doc-hash-A", pages=pages, chunks=chunks, provider=provider)

    assert stats_second_run.embedding_api_calls == 0
    assert stats_second_run.inserted_new == 0
    assert stats_second_run.unchanged_skipped == 2
    assert provider.call_count == 1  # still only the first run's call


def test_metadata_only_change_updates_without_reembedding():
    conn = FakeVectorStoreConnection()
    provider = _StubEmbeddingProvider()
    pages = [_make_page(0)]
    original = [_make_chunk("same text", section_title="old section")]

    upsert_chunks(conn, document_id=1, document_content_hash="doc-hash-A", pages=pages, chunks=original, provider=provider)

    changed_metadata = [_make_chunk("same text", section_title="new section")]
    stats = upsert_chunks(conn, document_id=1, document_content_hash="doc-hash-A", pages=pages, chunks=changed_metadata, provider=provider)

    assert stats.updated_metadata_only == 1
    assert stats.embedding_api_calls == 0
    assert provider.call_count == 1  # unchanged since the first run -- no new embedding call


def test_text_change_produces_a_new_chunk_id_and_gets_embedded():
    conn = FakeVectorStoreConnection()
    provider = _StubEmbeddingProvider()
    pages = [_make_page(0)]
    original = [_make_chunk("version A text")]

    upsert_chunks(conn, document_id=1, document_content_hash="doc-hash-A", pages=pages, chunks=original, provider=provider)

    changed_text = [_make_chunk("version B text")]
    stats = upsert_chunks(conn, document_id=1, document_content_hash="doc-hash-A", pages=pages, chunks=changed_text, provider=provider)

    assert stats.inserted_new == 1  # a genuinely new chunk_id (embedding_content_hash changed)
    assert stats.embedding_api_calls == 1
    assert provider.call_count == 2  # one call per run
    assert len(conn.chunks) == 2  # old row still present, not deleted (no archival in this sub-step)
