from spike.run_retrieval_benchmark import _grade_multi_chunk, _grade_single_chunk


def test_grade_single_chunk_hit_at_k_thresholds():
    evaluated = [
        {"document_correct": True, "page_correct": True, "content_correct": False},
        {"document_correct": True, "page_correct": True, "content_correct": False},
        {"document_correct": True, "page_correct": True, "content_correct": True},  # rank 3
    ]
    result = _grade_single_chunk(evaluated)
    assert result["hit_rank"] == 3
    assert result["hit_at_1"] is False
    assert result["hit_at_3"] is True
    assert result["hit_at_5"] is True


def test_grade_single_chunk_no_hit():
    evaluated = [{"document_correct": True, "page_correct": False, "content_correct": False}]
    result = _grade_single_chunk(evaluated)
    assert result["hit_rank"] is None
    assert result["hit_at_1"] is False
    assert result["hit_at_5"] is False


def test_grade_multi_chunk_reports_both_modes_and_all_k_values():
    vector_texts = ["chunk A with 容量： 10 kWh", "chunk B unrelated", "chunk C with $100,000"]
    hybrid_texts = ["chunk A with 容量： 10 kWh", "chunk C with $100,000", "chunk B unrelated"]
    keywords = ["容量： 10 kWh", "$100,000"]

    result = _grade_multi_chunk(vector_texts, hybrid_texts, keywords, threshold=1.0)

    # vector-only: needs top-3 to see both keywords (found at rank1 and rank3)
    assert result["vector_only"]["keyword_coverage_at_1"] == 0.5
    assert result["vector_only"]["success_at_1"] is False
    assert result["vector_only"]["keyword_coverage_at_3"] == 1.0
    assert result["vector_only"]["success_at_3"] is True

    # hybrid: both keywords already covered by top-2
    assert result["hybrid"]["keyword_coverage_at_1"] == 0.5
    assert result["hybrid"]["success_at_1"] is False
    assert result["hybrid"]["keyword_coverage_at_3"] == 1.0
    assert result["hybrid"]["success_at_3"] is True


def test_grade_multi_chunk_partial_threshold_allows_success_below_full_coverage():
    texts = ["chunk with only 容量： 10 kWh"]
    result = _grade_multi_chunk(texts, texts, ["容量： 10 kWh", "$100,000"], threshold=0.5)
    assert result["vector_only"]["keyword_coverage_at_1"] == 0.5
    assert result["vector_only"]["success_at_1"] is True  # meets the 0.5 threshold
