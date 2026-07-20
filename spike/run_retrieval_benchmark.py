"""Step 6 Sub-step 7 driver: formal retrieval benchmark over the expanded
question set in spike/test_questions.json.

Reuses the 124 chunks already ingested in Sub-step 4 -- does NOT re-ingest,
re-embed documents, or touch schema_spike.sql/chunker.py/vector_store.py.
Each eligible question's text is embedded exactly once per retrieval_scope
(one embedding API call), and the resulting candidate pool is used for both
the vector-only baseline ranking and the hybrid re-ranking (hybrid_retrieval.py's
scoring formula/WEIGHTS are untouched by this sub-step).

Retrieval scope:
  - "document_scoped" (always run): hybrid_retrieval.fetch_candidates is
    called WITH a filename filter, exactly as in Sub-step 5/6. Under this
    scope, document_correctness is true by construction (the query itself
    restricts to the expected document) -- it is still recorded for
    completeness, but it is not a meaningful signal here.
  - "global" (also run this round, since the corpus is small -- 124 chunks
    across only 2 documents -- so the extra cost is negligible): fetch_candidates
    is called WITHOUT a filename filter, searching every active chunk across
    every ingested document. This is the only mode where document_correctness
    actually tests something.

Grading:
  - single_chunk questions: ranked by evaluate_candidate() (document + page +
    exact content correctness, using the FULL stored chunk text) over the
    scored candidate pool; hit@1/3/5 derived from the rank of the first fully
    correct candidate.
  - multi_chunk questions: NOT required to have any single chunk contain the
    full answer; instead, keyword coverage is computed over the UNION of the
    top-1/top-3/top-5 candidates' full text (keyword_coverage_at_1/3/5).
  - false_positive_control questions: checked for hybrid-ranking-equals-
    vector-only-ranking (no date/table signal should fire), independent of
    whether they have gradable keywords.
  - Questions with retrieval_eval_eligible=false are skipped entirely and
    listed in the report under "excluded_questions" with their reason.

Run from the project root (after spike/run_embedding_ingestion.py has been
run at least once):
    python -m spike.run_retrieval_benchmark
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
from spike.retrieval_metrics import (
    evaluate_candidate,
    exact_content_correctness,
    hit_at_k,
    hybrid_matches_vector_only_order,
    multi_chunk_keyword_coverage,
    multi_chunk_success,
    single_chunk_hit_rank,
)

SPIKE_DIR = Path(__file__).resolve().parent
TOP_KS = (1, 3, 5)

DOC_ID_TO_FILENAME = {
    "doc1": "新進人員實習表.pdf",
    "doc3": "2415-1304研究報告-智能貨櫃屋 .pdf",
    "doc4": "A 完整版本  鋰電池二次利用之電池管理系統開發研究完成報告.pdf",
}


def _load_questions() -> list[dict]:
    with open(SPIKE_DIR / "test_questions.json", encoding="utf-8") as f:
        data = json.load(f)
    return data["questions"]


def _rows_to_evaluated(rows_or_scored, expected_filename: str, expected_pdf_page, expected_keywords, is_scored: bool):
    evaluated = []
    for r in rows_or_scored:
        if is_scored:
            candidate = {"filename": r.filename, "pdf_page_number_start": r.pdf_page_number_start, "pdf_page_number_end": r.pdf_page_number_end, "text": r.text}
        else:
            candidate = {"filename": r["filename"], "pdf_page_number_start": r["pdf_page_number_start"], "pdf_page_number_end": r["pdf_page_number_end"], "text": r["text"]}
        evaluated.append(evaluate_candidate(candidate, expected_filename, expected_pdf_page, expected_keywords))
    return evaluated


def _chunk_ids(rows_or_scored, is_scored: bool) -> list[str]:
    if is_scored:
        return [r.chunk_id for r in rows_or_scored]
    return [r["chunk_id"] for r in rows_or_scored]


def _texts(rows_or_scored, is_scored: bool, limit: int) -> list[str]:
    if is_scored:
        return [r.text for r in rows_or_scored[:limit]]
    return [r["text"] for r in rows_or_scored[:limit]]


def _grade_single_chunk(evaluated: list[dict]) -> dict:
    rank = single_chunk_hit_rank(evaluated)
    return {"hit_rank": rank, **{f"hit_at_{k}": hit_at_k(rank, k) for k in TOP_KS}}


def _grade_multi_chunk(vector_texts: list[str], hybrid_texts: list[str], keywords: list[str], threshold: float) -> dict:
    result = {}
    for mode, texts in (("vector_only", vector_texts), ("hybrid", hybrid_texts)):
        per_k = {}
        for k in TOP_KS:
            coverage = multi_chunk_keyword_coverage(texts[:k], keywords)
            per_k[f"keyword_coverage_at_{k}"] = coverage["coverage_ratio"]
            per_k[f"success_at_{k}"] = multi_chunk_success(coverage["coverage_ratio"], threshold)
            per_k[f"per_keyword_at_{k}"] = coverage["per_keyword"]
        result[mode] = per_k
    return result


def run_scope(conn, provider, questions: list[dict], scope: str) -> dict:
    filename_scoped = scope == "document_scoped"
    results = {}
    api_calls = 0
    total_tokens = 0

    for q in questions:
        if not q["retrieval_eval_eligible"]:
            continue

        doc_id = q["source_document"]
        filename = DOC_ID_TO_FILENAME[doc_id] if filename_scoped else None
        expected_filename = DOC_ID_TO_FILENAME[doc_id]
        expected_pdf_page = (q.get("expected_location") or {}).get("pdf_page_number")
        keywords = q.get("expected_content_keywords") or []

        embed_result = provider.embed_batch([q["question"]])
        api_calls += 1
        total_tokens += embed_result.total_tokens or 0
        query_vector = embed_result.results[0].vector

        date_candidates = extract_date_candidates(q["question"])
        table_query = looks_like_table_question(q["question"])

        rows = fetch_candidates(conn, query_vector, filename, pool_size=30)
        scored = score_candidates(rows, date_candidates, table_query)

        vector_only_ids = _chunk_ids(rows, is_scored=False)
        hybrid_ids = _chunk_ids(scored, is_scored=True)

        q_result = {
            "question": q["question"],
            "source_document": doc_id,
            "retrieval_target": q.get("retrieval_target"),
            "false_positive_control": bool(q.get("false_positive_control")),
        }

        if q.get("false_positive_control"):
            q_result["hybrid_matches_vector_only_order"] = hybrid_matches_vector_only_order(vector_only_ids, hybrid_ids)

        if keywords and q.get("retrieval_target") == "single_chunk":
            vector_evaluated = _rows_to_evaluated(rows, expected_filename, expected_pdf_page, keywords, is_scored=False)
            hybrid_evaluated = _rows_to_evaluated(scored, expected_filename, expected_pdf_page, keywords, is_scored=True)
            q_result["vector_only"] = _grade_single_chunk(vector_evaluated)
            q_result["hybrid"] = _grade_single_chunk(hybrid_evaluated)
            # per-candidate detail for the top 5, so document/page/content
            # correctness are visible SEPARATELY, not just folded into hit@k
            q_result["vector_only"]["top_5_detail"] = vector_evaluated[:5]
            q_result["hybrid"]["top_5_detail"] = hybrid_evaluated[:5]
        elif keywords and q.get("retrieval_target") == "multi_chunk":
            threshold = q.get("multi_chunk_coverage_threshold", 1.0)
            vector_texts = _texts(rows, is_scored=False, limit=5)
            hybrid_texts = _texts(scored, is_scored=True, limit=5)
            q_result["multi_chunk"] = _grade_multi_chunk(vector_texts, hybrid_texts, keywords, threshold)
        else:
            q_result["not_graded_reason"] = "no expected_content_keywords -- used for false-positive check only, if applicable"

        results[q["id"]] = q_result

    return {"scope": scope, "results": results, "api_calls": api_calls, "total_tokens": total_tokens}


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY not set in environment (.env) -- refusing to proceed")

    engine = create_engine(os.environ["DATABASE_URL"])
    provider = OpenAIEmbeddingProvider()
    questions = _load_questions()

    excluded = [
        {"id": q["id"], "source_document": q["source_document"], "reason": q.get("eligibility_reason")}
        for q in questions
        if not q["retrieval_eval_eligible"]
    ]

    report = {"weights_used": WEIGHTS, "excluded_questions": excluded}

    with engine.connect() as conn:
        scoped = run_scope(conn, provider, questions, "document_scoped")
        global_ = run_scope(conn, provider, questions, "global")

    report["document_scoped"] = {k: v for k, v in scoped.items() if k != "scope"}
    report["global"] = {k: v for k, v in global_.items() if k != "scope"}
    report["total_api_calls"] = scoped["api_calls"] + global_["api_calls"]
    report["total_tokens"] = scoped["total_tokens"] + global_["total_tokens"]

    out_path = SPIKE_DIR / "retrieval_benchmark_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"document_scoped api_calls={scoped['api_calls']} tokens={scoped['total_tokens']}")
    print(f"global api_calls={global_['api_calls']} tokens={global_['total_tokens']}")
    print(f"excluded_questions={len(excluded)}")
    print(f"Full report written to {out_path}")


if __name__ == "__main__":
    main()
