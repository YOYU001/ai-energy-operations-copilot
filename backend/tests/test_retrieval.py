"""Step 10 Sub-step 5: unit tests for app/services/retrieval.py.

Scoring-logic tests (score_candidates) mirror spike/tests/test_hybrid_retrieval.py,
ported to production field names (file_name/content, document_id added) and
extended with the new metadata_boost field and the explicit stable
tie-break. fetch_candidates' SQL-building tests use the existing
FakeConnection (canned rows, records executed SQL/params) since verifying
"the right WHERE clause was built" doesn't require simulating real vector
math -- that's covered by test_retrieval_integration.py against the real DB.
"""

import pytest

from app.services.query_parser import DateCandidate
from app.services.retrieval import WEIGHTS, fetch_candidates, retrieve_chunks, score_candidates
from tests.fakes import FakeConnection


def _row(chunk_id, chunk_type, content, distance, document_id=1, file_name="doc.pdf"):
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "chunk_type": chunk_type,
        "content": content,
        "file_name": file_name,
        "page_index_start": 0,
        "page_index_end": 0,
        "pdf_page_number_start": 63,
        "pdf_page_number_end": 63,
        "printed_page_number_map": {"63": "52"},
        "section_title": "sec",
        "table_title": "表4. 系統超約事件紀錄",
        "distance": distance,
    }


# ---------------------------------------------------------------------------
# score_candidates
# ---------------------------------------------------------------------------


def test_no_signals_preserves_vector_only_order():
    rows = [
        _row("a", "prose", "unrelated text", 0.40),
        _row("b", "table", "unrelated table text", 0.45),
        _row("c", "prose", "more unrelated text", 0.50),
    ]
    scored = score_candidates(rows, date_candidates=[], table_query=False)
    assert [s.chunk_id for s in scored] == ["a", "b", "c"]
    for s in scored:
        assert s.exact_date_match is False
        assert s.table_query_match is False
        assert s.metadata_boost == 0.0
        assert s.final_score == WEIGHTS["semantic"] * (1 - s.vector_distance)


def test_exact_date_match_promotes_correct_row_even_if_not_top_by_distance():
    rows = [
        _row("wrong_date", "table", "2024 年8 月21 日\n10:45~11:00", 0.40),
        _row("right_date", "table", "2024 年8 月30 日\n10:30~10:45", 0.45),
    ]
    dc = [DateCandidate(2024, 8, 30)]
    scored = score_candidates(rows, date_candidates=dc, table_query=True)
    assert scored[0].chunk_id == "right_date"
    assert scored[0].exact_date_match is True
    assert scored[0].metadata_boost == WEIGHTS["exact_date_match"] + WEIGHTS["table_query_match"]
    assert scored[1].exact_date_match is False


def test_table_query_match_only_applies_to_table_chunks():
    rows = [
        _row("prose_chunk", "prose", "text mentioning 表4 without being a table row", 0.40),
        _row("table_chunk", "table", "actual table content", 0.42),
    ]
    scored = score_candidates(rows, date_candidates=[], table_query=True)
    by_id = {s.chunk_id: s for s in scored}
    assert by_id["prose_chunk"].table_query_match is False
    assert by_id["table_chunk"].table_query_match is True
    assert by_id["table_chunk"].metadata_boost == WEIGHTS["table_query_match"]


def test_final_score_formula_matches_weights():
    rows = [_row("x", "table", "2024 年8 月30 日", 0.40)]
    dc = [DateCandidate(2024, 8, 30)]
    scored = score_candidates(rows, date_candidates=dc, table_query=True)
    s = scored[0]
    expected = WEIGHTS["semantic"] * (1 - 0.40) + WEIGHTS["exact_date_match"] + WEIGHTS["table_query_match"]
    assert abs(s.final_score - expected) < 1e-9


def test_no_date_candidates_never_sets_exact_date_match():
    rows = [_row("x", "table", "2024 年8 月30 日", 0.40)]
    scored = score_candidates(rows, date_candidates=[], table_query=True)
    assert scored[0].exact_date_match is False


def test_stable_tie_break_on_equal_final_score():
    # Same distance (and thus same final_score) for two rows with no
    # metadata signal firing -- order must be deterministic (by chunk_id),
    # not incidental input order.
    rows = [
        _row("z_chunk", "prose", "text", 0.5),
        _row("a_chunk", "prose", "text", 0.5),
    ]
    scored = score_candidates(rows, date_candidates=[], table_query=False)
    assert [s.chunk_id for s in scored] == ["a_chunk", "z_chunk"]

    # Re-running with the input rows reversed must produce the identical order.
    scored_reversed = score_candidates(list(reversed(rows)), date_candidates=[], table_query=False)
    assert [s.chunk_id for s in scored_reversed] == ["a_chunk", "z_chunk"]


# ---------------------------------------------------------------------------
# retrieve_chunks
# ---------------------------------------------------------------------------


class _FakeEmbeddingProvider:
    def __init__(self, vector):
        self.vector = vector
        self.calls = []

    def embed_batch(self, texts):
        self.calls.append(texts)

        class _Result:
            pass

        class _Item:
            def __init__(self, vector):
                self.vector = vector

        result = _Result()
        result.results = [_Item(self.vector)]
        return result


def test_retrieve_chunks_requires_exactly_one_embedding_source():
    conn = FakeConnection(rows=[])
    with pytest.raises(ValueError):
        retrieve_chunks(conn, "some query")
    with pytest.raises(ValueError):
        retrieve_chunks(conn, "some query", embedding_provider=_FakeEmbeddingProvider([0.1]), query_embedding=[0.1])


def test_retrieve_chunks_top_k_slices_after_scoring(monkeypatch):
    rows = [_row(f"c{i}", "prose", "text", 0.1 * i) for i in range(10)]
    conn = FakeConnection(rows=rows)

    result = retrieve_chunks(conn, "some query", query_embedding=[0.1, 0.2], top_k=3)

    assert len(result) == 3
    assert [s.chunk_id for s in result] == ["c0", "c1", "c2"]


def test_retrieve_chunks_uses_provided_embedding_provider_when_no_query_embedding():
    rows = [_row("a", "prose", "text", 0.2)]
    conn = FakeConnection(rows=rows)
    provider = _FakeEmbeddingProvider([0.5, 0.5])

    result = retrieve_chunks(conn, "some query", embedding_provider=provider, top_k=5)

    assert provider.calls == [["some query"]]
    assert len(result) == 1


# ---------------------------------------------------------------------------
# fetch_candidates SQL shape (filters correctly parameterized, base filters
# always present) -- real vector-distance/ranking correctness is verified
# against the real DB in test_retrieval_integration.py.
# ---------------------------------------------------------------------------


def test_fetch_candidates_always_filters_active_and_embedded():
    conn = FakeConnection(rows=[])
    fetch_candidates(conn, [0.1, 0.2])

    statement, params = conn.executed[-1]
    sql = str(statement)
    assert "c.is_active = true" in sql
    assert "c.embedding IS NOT NULL" in sql
    assert "document_id" not in params
    assert "file_name" not in params
    assert "chunk_type" not in params


def test_fetch_candidates_applies_document_id_filter():
    conn = FakeConnection(rows=[])
    fetch_candidates(conn, [0.1, 0.2], document_id=42)

    statement, params = conn.executed[-1]
    assert "c.document_id = :document_id" in str(statement)
    assert params["document_id"] == 42


def test_fetch_candidates_applies_file_name_filter():
    conn = FakeConnection(rows=[])
    fetch_candidates(conn, [0.1, 0.2], file_name="a.pdf")

    statement, params = conn.executed[-1]
    assert "d.file_name = :file_name" in str(statement)
    assert params["file_name"] == "a.pdf"


def test_fetch_candidates_applies_chunk_type_filter():
    conn = FakeConnection(rows=[])
    fetch_candidates(conn, [0.1, 0.2], chunk_type="table")

    statement, params = conn.executed[-1]
    assert "c.chunk_type = :chunk_type" in str(statement)
    assert params["chunk_type"] == "table"


def test_fetch_candidates_parameterizes_query_vector_not_string_interpolated():
    conn = FakeConnection(rows=[])
    query_vector = [0.1, 0.2, 0.3]
    fetch_candidates(conn, query_vector)

    statement, params = conn.executed[-1]
    assert ":qv" in str(statement)
    assert str(query_vector) not in str(statement)  # never interpolated directly into SQL text
    assert params["qv"] == str(query_vector)
