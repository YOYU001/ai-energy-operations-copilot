"""Step 10 Sub-step 5: real dev PostgreSQL integration tests for
app/services/retrieval.py.

Ingests small, deterministic, controlled fixture PDFs via the real
ingestion pipeline (ingest_pdf_document + DeterministicFakeEmbeddingProvider,
no real OpenAI calls) so retrieval runs against real production-schema rows
with real pgvector columns, then calls fetch_candidates/retrieve_chunks
directly against the real DB connection.

Isolation: rows use file_name starting with INTEGRATION_TEST_PREFIX.
Cleanup runs in fixture teardown regardless of test outcome.
"""

from pathlib import Path

import pytest
from sqlalchemy import text

from app.db import get_connection
from app.services.ingestion_rag import ingest_pdf_document
from app.services.pdf_parser import parse_pdf_pages
from app.services.chunker import STRATEGIES, chunk_document
from app.services.retrieval import fetch_candidates, retrieve_chunks
from tests.pdf_fixtures import DeterministicFakeEmbeddingProvider, build_fixture_pdf

INTEGRATION_TEST_PREFIX = "integration_test_retrieval_"


@pytest.fixture
def real_conn():
    with get_connection() as conn:
        try:
            yield conn
        finally:
            conn.rollback()
            conn.execute(
                text(
                    "DELETE FROM document_chunks WHERE document_id IN "
                    "(SELECT id FROM documents WHERE file_name LIKE :prefix)"
                ),
                {"prefix": f"{INTEGRATION_TEST_PREFIX}%"},
            )
            conn.execute(
                text("DELETE FROM documents WHERE file_name LIKE :prefix"),
                {"prefix": f"{INTEGRATION_TEST_PREFIX}%"},
            )
            conn.commit()


# ---------------------------------------------------------------------------
# Fixtures: one document with a genuine table chunk (mirrors the spike
# corpus's own table layout -- unit-annotated header token, then a
# DATE_LINE_RE row, then a trailing "表N." caption closes the table region)
# plus prose paragraphs, so both chunk_type=="table" and =="prose" chunks
# exist for the table-query-boost test.
# ---------------------------------------------------------------------------

_DOC_A_PAGES = [
    "測試場域超約事件說明。\n"
    "以下段落描述一般性背景資訊，與特定日期或表格數據無關的敘述文字。\n"
    "敘述文字敘述文字敘述文字敘述文字敘述文字敘述文字敘述文字敘述文字。",
    "需量 (kW)\n"
    "2024年8月30日\n"
    "10:30~10:45\n"
    "1.2\n"
    "表4. 測試超約事件紀錄",
]

_DOC_B_PAGES = [
    "另一份測試文件的敘述內容，內容與文件 A 不同，用於 filename/document 過濾測試。\n"
    "敘述文字敘述文字敘述文字敘述文字敘述文字敘述文字敘述文字敘述文字。",
]


def _ingest(conn, tmp_path, name, pages):
    path = tmp_path / name
    build_fixture_pdf(path, pages, fontname="china-ts")
    result = ingest_pdf_document(conn, str(path), f"{INTEGRATION_TEST_PREFIX}{name}", DeterministicFakeEmbeddingProvider())
    assert result.status == "ready"
    return result


def test_fixture_actually_produces_a_table_chunk(tmp_path):
    """Precondition check, not a retrieval assertion: confirms the fixture's
    layout genuinely triggers the chunker's table-detection state machine,
    rather than silently testing against zero table chunks."""
    path = tmp_path / "precheck.pdf"
    build_fixture_pdf(path, _DOC_A_PAGES, fontname="china-ts")
    pages = parse_pdf_pages(str(path))
    strategy = next(s for s in STRATEGIES if s["name"] == "structured_600_100")
    chunks = chunk_document(pages, "precheck.pdf", strategy)
    assert any(c.chunk_type == "table" for c in chunks)


def test_semantic_similarity_ordering_and_active_only(real_conn, tmp_path):
    conn = real_conn
    doc_a = _ingest(conn, tmp_path, "doc_a.pdf", _DOC_A_PAGES)

    rows = fetch_candidates(conn, [0.5] * 1536, document_id=doc_a.document_id)
    assert len(rows) >= 1
    distances = [float(r["distance"]) for r in rows]
    assert distances == sorted(distances)  # ORDER BY distance actually applied
    assert all(r["chunk_id"] for r in rows)

    # Superseding doc_a (same file_name) must remove its chunks from candidates.
    doc_a2 = _ingest(conn, tmp_path, "doc_a.pdf", _DOC_B_PAGES)
    assert doc_a2.document_id != doc_a.document_id
    rows_after = fetch_candidates(conn, [0.5] * 1536, document_id=doc_a.document_id)
    assert rows_after == []  # doc_a's chunks are now inactive, never returned


def test_no_metadata_signal_preserves_pure_semantic_order(real_conn, tmp_path):
    conn = real_conn
    doc = _ingest(conn, tmp_path, "plain.pdf", _DOC_A_PAGES)

    results = retrieve_chunks(
        conn,
        "與任何日期或表格都無關的一般性問題",
        query_embedding=[0.3] * 1536,
        document_id=doc.document_id,
        top_k=10,
    )
    assert results
    assert all(r.metadata_boost == 0.0 for r in results)
    scores = [r.final_score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_exact_date_boost_changes_ranking(real_conn, tmp_path):
    conn = real_conn
    doc = _ingest(conn, tmp_path, "dated.pdf", _DOC_A_PAGES)

    query = "2024年8月30日這天記錄了什麼超約事件？"
    results = retrieve_chunks(conn, query, query_embedding=[0.5] * 1536, document_id=doc.document_id, top_k=10)

    date_matching = [r for r in results if r.exact_date_match]
    assert date_matching, "fixture's table row containing the exact date must be recognized as a match"
    assert results[0].exact_date_match is True  # the 0.5 flat bonus dominates the tightly-clustered semantic scores
    assert results[0].metadata_boost >= 0.5


def test_table_query_boost_changes_ranking(real_conn, tmp_path):
    conn = real_conn
    doc = _ingest(conn, tmp_path, "tablequery.pdf", _DOC_A_PAGES)

    query = "表4的內容是什麼？"
    results = retrieve_chunks(conn, query, query_embedding=[0.5] * 1536, document_id=doc.document_id, top_k=10)

    assert results[0].table_query_match is True
    assert results[0].chunk_type == "table"


def test_document_and_file_name_filters(real_conn, tmp_path):
    conn = real_conn
    doc_a = _ingest(conn, tmp_path, "alpha.pdf", _DOC_A_PAGES)
    doc_b = _ingest(conn, tmp_path, "beta.pdf", _DOC_B_PAGES)

    only_a = fetch_candidates(conn, [0.4] * 1536, document_id=doc_a.document_id)
    assert all(r["document_id"] == doc_a.document_id for r in only_a)
    assert only_a  # non-empty

    only_b_by_filename = fetch_candidates(conn, [0.4] * 1536, file_name=f"{INTEGRATION_TEST_PREFIX}beta.pdf")
    assert only_b_by_filename
    assert all(r["document_id"] == doc_b.document_id for r in only_b_by_filename)


def test_chunk_type_filter(real_conn, tmp_path):
    conn = real_conn
    doc = _ingest(conn, tmp_path, "typed.pdf", _DOC_A_PAGES)

    table_only = fetch_candidates(conn, [0.5] * 1536, document_id=doc.document_id, chunk_type="table")
    assert table_only
    assert all(r["chunk_type"] == "table" for r in table_only)

    prose_only = fetch_candidates(conn, [0.5] * 1536, document_id=doc.document_id, chunk_type="prose")
    assert prose_only
    assert all(r["chunk_type"] == "prose" for r in prose_only)


def test_inactive_chunks_never_returned_after_cutover(real_conn, tmp_path):
    conn = real_conn
    doc_v1 = _ingest(conn, tmp_path, "versioned.pdf", _DOC_A_PAGES)
    v1_rows = fetch_candidates(conn, [0.5] * 1536, document_id=doc_v1.document_id)
    assert v1_rows

    doc_v2 = _ingest(conn, tmp_path, "versioned.pdf", _DOC_B_PAGES)
    assert doc_v2.document_id != doc_v1.document_id

    v1_rows_after_cutover = fetch_candidates(conn, [0.5] * 1536, document_id=doc_v1.document_id)
    assert v1_rows_after_cutover == []

    global_rows = fetch_candidates(conn, [0.5] * 1536)
    returned_document_ids = {r["document_id"] for r in global_rows}
    assert doc_v1.document_id not in returned_document_ids
