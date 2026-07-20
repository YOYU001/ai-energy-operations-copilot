"""Step 6 Sub-step 7: pure evaluation-metric functions for the retrieval benchmark.

Kept separate from spike/hybrid_retrieval.py (which is retrieval/scoring
logic, not evaluation logic) so these functions can be unit tested without a
real database or embedding API call, and so spike/hybrid_retrieval.py's
scoring formula/WEIGHTS stay untouched by this sub-step.

All functions operate on the FULL stored `text` of a candidate, never a
truncated preview -- callers (spike/run_retrieval_benchmark.py) must pass
the real `text` column value. This is a direct, mechanical fix for the
Sub-step 5 finding that manual review of a 150-char text_preview produced a
wrong conclusion about q06's top-1 result.
"""

from __future__ import annotations


def document_correctness(candidate_filename: str, expected_filename: str) -> bool:
    return candidate_filename == expected_filename


def page_correctness(candidate_page_start: int, candidate_page_end: int, expected_pdf_page: int | None) -> bool:
    if expected_pdf_page is None:
        return False
    return candidate_page_start <= expected_pdf_page <= candidate_page_end


def exact_content_correctness(full_text: str, expected_keywords: list[str]) -> bool:
    """True only if EVERY expected keyword is a literal substring of full_text.
    An empty expected_keywords list is treated as "not gradable" -> False,
    never as a vacuous pass.
    """
    if not expected_keywords:
        return False
    return all(kw in full_text for kw in expected_keywords)


def evaluate_candidate(candidate: dict, expected_filename: str, expected_pdf_page: int | None, expected_keywords: list[str]) -> dict:
    """candidate must have keys: filename, pdf_page_number_start, pdf_page_number_end, text."""
    return {
        "document_correct": document_correctness(candidate["filename"], expected_filename),
        "page_correct": page_correctness(candidate["pdf_page_number_start"], candidate["pdf_page_number_end"], expected_pdf_page),
        "content_correct": exact_content_correctness(candidate["text"], expected_keywords),
    }


def single_chunk_hit_rank(evaluated_candidates: list[dict]) -> int | None:
    """evaluated_candidates: evaluate_candidate() dicts, already in ranked order.
    Returns the 1-indexed rank of the first candidate that is fully correct
    (document AND page AND content), or None if no candidate qualifies.
    """
    for i, e in enumerate(evaluated_candidates):
        if e["document_correct"] and e["page_correct"] and e["content_correct"]:
            return i + 1
    return None


def hit_at_k(rank: int | None, k: int) -> bool:
    return rank is not None and rank <= k


def multi_chunk_keyword_coverage(candidate_texts: list[str], expected_keywords: list[str]) -> dict:
    """candidate_texts: FULL text of the top-k candidates the caller has
    already sliced (e.g. the top 3 by rank). Coverage is the UNION across
    all of them -- a multi-chunk question does not require any single chunk
    to contain every keyword.
    """
    if not expected_keywords:
        return {"per_keyword": {}, "coverage_ratio": 0.0}
    per_keyword = {kw: any(kw in text for text in candidate_texts) for kw in expected_keywords}
    coverage_ratio = sum(per_keyword.values()) / len(expected_keywords)
    return {"per_keyword": per_keyword, "coverage_ratio": coverage_ratio}


def multi_chunk_success(coverage_ratio: float, threshold: float = 1.0) -> bool:
    return coverage_ratio >= threshold


def hybrid_matches_vector_only_order(vector_only_chunk_ids: list[str], hybrid_chunk_ids: list[str]) -> bool:
    """False-positive-control check: with no date/table signal expected to
    fire, hybrid ranking must be byte-for-byte identical to vector-only.
    """
    return vector_only_chunk_ids == hybrid_chunk_ids
