from spike.retrieval_metrics import (
    document_correctness,
    evaluate_candidate,
    exact_content_correctness,
    hit_at_k,
    hybrid_matches_vector_only_order,
    multi_chunk_keyword_coverage,
    multi_chunk_success,
    page_correctness,
    single_chunk_hit_rank,
)


def test_document_correctness():
    assert document_correctness("doc3.pdf", "doc3.pdf") is True
    assert document_correctness("doc1.pdf", "doc3.pdf") is False


def test_page_correctness_within_range():
    assert page_correctness(63, 64, 63) is True
    assert page_correctness(63, 64, 64) is True
    assert page_correctness(63, 64, 65) is False
    assert page_correctness(63, 64, None) is False


def test_exact_content_correctness_requires_all_keywords_present():
    text = "表4. 系統超約事件紀錄\n2024 年8 月30 日\n10:30~10:45"
    assert exact_content_correctness(text, ["2024 年8 月30 日"]) is True
    assert exact_content_correctness(text, ["2024 年8 月30 日", "10:30~10:45"]) is True
    assert exact_content_correctness(text, ["2024 年8 月30 日", "missing string"]) is False


def test_exact_content_correctness_empty_keywords_is_not_gradable():
    # An empty keyword list must never vacuously pass -- that would silently
    # mark ungraded questions as "correct".
    assert exact_content_correctness("any text at all", []) is False


def test_exact_content_correctness_uses_full_text_not_a_truncated_preview():
    # The Sub-step 5 bug: a 150-char preview of this text would only show
    # "...8月21日..." and a human reviewer would (wrongly) conclude the
    # 8/30 keyword is absent. The full text (below) actually contains it.
    full_text = (
        "表4. 系統超約事件紀錄\n2024 年8 月21 日\n10:45~11:00\n..." + "x" * 200 + "\n2024 年8 月30 日\n10:30~10:45"
    )
    assert exact_content_correctness(full_text, ["2024 年8 月30 日"]) is True


def test_evaluate_candidate_combines_all_three_dimensions():
    candidate = {"filename": "doc3.pdf", "pdf_page_number_start": 63, "pdf_page_number_end": 63, "text": "2024 年8 月30 日"}
    result = evaluate_candidate(candidate, "doc3.pdf", 63, ["2024 年8 月30 日"])
    assert result == {"document_correct": True, "page_correct": True, "content_correct": True}


def test_single_chunk_hit_rank_finds_first_fully_correct_candidate():
    evaluated = [
        {"document_correct": True, "page_correct": True, "content_correct": False},  # page right, content wrong
        {"document_correct": True, "page_correct": True, "content_correct": True},  # this one is the real hit
        {"document_correct": True, "page_correct": True, "content_correct": True},
    ]
    assert single_chunk_hit_rank(evaluated) == 2


def test_single_chunk_hit_rank_none_when_nothing_qualifies():
    evaluated = [
        {"document_correct": True, "page_correct": True, "content_correct": False},
        {"document_correct": True, "page_correct": False, "content_correct": True},
    ]
    assert single_chunk_hit_rank(evaluated) is None


def test_hit_at_k():
    assert hit_at_k(1, 1) is True
    assert hit_at_k(3, 3) is True
    assert hit_at_k(4, 3) is False
    assert hit_at_k(None, 5) is False


def test_multi_chunk_keyword_coverage_unions_across_candidates():
    texts = ["chunk with 容量： 10 kWh only", "different chunk with $100,000 only"]
    result = multi_chunk_keyword_coverage(texts, ["容量： 10 kWh", "$100,000"])
    assert result["per_keyword"] == {"容量： 10 kWh": True, "$100,000": True}
    assert result["coverage_ratio"] == 1.0


def test_multi_chunk_keyword_coverage_partial():
    texts = ["chunk with 容量： 10 kWh only"]
    result = multi_chunk_keyword_coverage(texts, ["容量： 10 kWh", "$100,000"])
    assert result["coverage_ratio"] == 0.5
    assert result["per_keyword"]["$100,000"] is False


def test_multi_chunk_success_threshold():
    assert multi_chunk_success(1.0, threshold=1.0) is True
    assert multi_chunk_success(0.5, threshold=1.0) is False
    assert multi_chunk_success(0.5, threshold=0.5) is True


def test_hybrid_matches_vector_only_order():
    assert hybrid_matches_vector_only_order(["a", "b", "c"], ["a", "b", "c"]) is True
    assert hybrid_matches_vector_only_order(["a", "b", "c"], ["a", "c", "b"]) is False
