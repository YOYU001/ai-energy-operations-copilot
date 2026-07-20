"""Step 6 Sub-step 5 driver: vector-only baseline vs. hybrid scoring comparison.

Reuses the 124 chunks already ingested in Sub-step 4 -- does NOT re-ingest,
re-embed documents, or touch schema_spike.sql. Each question's TEXT is
embedded exactly once (1 embedding API call per question); the resulting
candidate pool (top CANDIDATE_POOL_SIZE by vector distance) is used for
both the vector-only baseline ranking (first top_k of that pool, which is
already distance-sorted) and the hybrid re-ranking
(hybrid_retrieval.score_candidates).

Question set:
  - q06, q11: the two "verified"-tier questions (see Sub-step 4).
  - q02, q05, q13: false-positive controls -- doc3 questions with no exact
    date pattern and no "表<N>" table reference in their question text, so
    neither hybrid signal should fire and hybrid ranking must be IDENTICAL
    to vector-only for these three.

Run from the project root (after spike/run_embedding_ingestion.py has been
run at least once):
    python -m spike.run_retrieval_comparison
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

from spike.embedding_provider import OpenAIEmbeddingProvider
from spike.hybrid_retrieval import WEIGHTS, fetch_candidates, score_candidates
from spike.query_parser import extract_date_candidates, looks_like_table_question

SPIKE_DIR = Path(__file__).resolve().parent
TOP_K = 5

DOC_ID_TO_FILENAME = {
    "doc1": "新進人員實習表.pdf",
    "doc3": "2415-1304研究報告-智能貨櫃屋 .pdf",
}

QUESTION_IDS = ["q06", "q11", "q02", "q05", "q13"]  # q06/q11 = verified; q02/q05/q13 = false-positive controls


def _load_questions() -> dict[str, dict]:
    with open(SPIKE_DIR / "test_questions.json", encoding="utf-8") as f:
        data = json.load(f)
    return {q["id"]: q for q in data["questions"] if q["id"] in QUESTION_IDS}


def _page_ranges_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start <= b_end and b_start <= a_end


def _row_to_dict(r, rank: int) -> dict:
    return {
        "rank": rank,
        "chunk_id": r["chunk_id"],
        "chunk_type": r["chunk_type"],
        "pdf_page_number_range": [r["pdf_page_number_start"], r["pdf_page_number_end"]],
        "printed_page_number_map": r["printed_page_number_map"],
        "section_title": r["section_title"],
        "table_title": r["table_title"],
        "vector_distance": float(r["distance"]),
        "text_preview": r["text"][:150],
    }


def _scored_to_dict(s, rank: int) -> dict:
    return {
        "rank": rank,
        "chunk_id": s.chunk_id,
        "chunk_type": s.chunk_type,
        "pdf_page_number_range": [s.pdf_page_number_start, s.pdf_page_number_end],
        "printed_page_number_map": s.printed_page_number_map,
        "section_title": s.section_title,
        "table_title": s.table_title,
        "score_breakdown": {
            "vector_distance": s.vector_distance,
            "semantic_score": s.semantic_score,
            "exact_date_match": s.exact_date_match,
            "table_query_match": s.table_query_match,
            "final_score": s.final_score,
        },
        "text_preview": s.text[:150],
    }


def _hit(results_page_ranges: list[tuple[int, int]], expected_pdf_page: int | None) -> bool:
    if expected_pdf_page is None:
        return False
    return any(_page_ranges_overlap(a, b, expected_pdf_page, expected_pdf_page) for a, b in results_page_ranges)


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY not set in environment (.env) -- refusing to proceed")

    engine = create_engine(os.environ["DATABASE_URL"])
    provider = OpenAIEmbeddingProvider()

    questions = _load_questions()
    report = {
        "weights_used": WEIGHTS,
        "candidate_pool_size": None,
        "results": {},
    }

    total_api_calls = 0
    total_tokens = 0

    with engine.connect() as conn:
        for qid in QUESTION_IDS:
            q = questions[qid]
            doc_id = q["source_document"]
            if isinstance(doc_id, list):
                raise RuntimeError(f"{qid}: multi-document questions are not supported by this comparison script")
            filename = DOC_ID_TO_FILENAME[doc_id]
            expected = q["expected_location"] or {}
            expected_pdf_page = expected.get("pdf_page_number")

            embed_result = provider.embed_batch([q["question"]])
            total_api_calls += 1
            total_tokens += embed_result.total_tokens or 0
            query_vector = embed_result.results[0].vector

            date_candidates = extract_date_candidates(q["question"])
            table_query = looks_like_table_question(q["question"])

            rows = fetch_candidates(conn, query_vector, filename)
            report["candidate_pool_size"] = len(rows) if rows else report["candidate_pool_size"]

            vector_only_top = rows[:TOP_K]
            scored = score_candidates(rows, date_candidates, table_query)
            hybrid_top = scored[:TOP_K]

            vector_only_hit = _hit(
                [(r["pdf_page_number_start"], r["pdf_page_number_end"]) for r in vector_only_top], expected_pdf_page
            )
            hybrid_hit = _hit(
                [(s.pdf_page_number_start, s.pdf_page_number_end) for s in hybrid_top], expected_pdf_page
            )

            report["results"][qid] = {
                "question": q["question"],
                "source_document": doc_id,
                "expected_location": expected,
                "parsed_date_candidates": [
                    {"year": dc.year, "month": dc.month, "day": dc.day} for dc in date_candidates
                ],
                "table_query_detected": table_query,
                "vector_only": {
                    "top_k": [_row_to_dict(r, i + 1) for i, r in enumerate(vector_only_top)],
                    "citation_page_correctness_hit": vector_only_hit,
                },
                "hybrid": {
                    "top_k": [_scored_to_dict(s, i + 1) for i, s in enumerate(hybrid_top)],
                    "citation_page_correctness_hit": hybrid_hit,
                },
            }
            print(f"{qid}: vector_only_hit={vector_only_hit}, hybrid_hit={hybrid_hit}, "
                  f"dates={[f'{dc.year}-{dc.month}-{dc.day}' for dc in date_candidates]}, table_query={table_query}")

    report["api_calls"] = total_api_calls
    report["total_tokens"] = total_tokens

    out_path = SPIKE_DIR / "retrieval_comparison_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\napi_calls={total_api_calls}, total_tokens={total_tokens}")
    print(f"Full report written to {out_path}")


if __name__ == "__main__":
    main()
