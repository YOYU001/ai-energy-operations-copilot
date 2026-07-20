from spike.hybrid_retrieval import WEIGHTS, score_candidates
from spike.query_parser import DateCandidate


def _row(chunk_id, chunk_type, text, distance):
    return {
        "chunk_id": chunk_id,
        "chunk_type": chunk_type,
        "text": text,
        "filename": "doc3.pdf",
        "pdf_page_number_start": 63,
        "pdf_page_number_end": 63,
        "printed_page_number_map": {"63": "52"},
        "section_title": "sec",
        "table_title": "表4. 系統超約事件紀錄",
        "distance": distance,
    }


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
