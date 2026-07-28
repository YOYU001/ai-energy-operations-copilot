"""Step 10 Sub-step 5: production regression benchmark runner.

Ported from spike/run_retrieval_benchmark.py (Step 6 Sub-step 7), pointed at
the production documents/document_chunks schema and app/services/retrieval.py
instead of spike_documents/spike_document_chunks and hybrid_retrieval.py.

Reuses the SAME evaluation inputs as the spike so the baseline is a real
regression check, not a re-tuned one:
  - spike/test_questions.json (question set, ground truth, eligibility flags)
  - the same 3 source PDFs under data/spike_documents/
  - the same scoring WEIGHTS (app/services/retrieval.py, unchanged from spike)
  - the same grading functions (app/services/retrieval_metrics.py, ported
    unchanged from spike/retrieval_metrics.py)

Do NOT edit test_questions.json to make a score look better, and do NOT
loosen retrieval_metrics.py's grading to pass more questions -- both would
defeat the point of a regression benchmark.

THIS SCRIPT MAKES REAL OpenAI API CALLS (embedding every not-yet-ingested
source PDF's chunks, plus one embedding call per benchmark question) and
therefore has a real dollar cost. Do not run it without the user's explicit
go-ahead for that specific run.

Run from the backend/ directory (same convention as `uvicorn app.main:app
--app-dir backend`; there is no backend/ package itself, only app/ and
scripts/ underneath it), after confirming OPENAI_API_KEY is set and the user
has approved the cost:
    cd backend && python -m scripts.run_retrieval_benchmark
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text as sql_text

load_dotenv()

from app.db import get_connection  # noqa: E402
from app.services.embedding_provider import OpenAIEmbeddingProvider  # noqa: E402
from app.services.ingestion_rag import ingest_pdf_document  # noqa: E402
from app.services.query_parser import extract_date_candidates, looks_like_table_question  # noqa: E402
from app.services.retrieval import WEIGHTS, fetch_candidates, score_candidates  # noqa: E402
from app.services.retrieval_metrics import (  # noqa: E402
    evaluate_candidate,
    hit_at_k,
    hybrid_matches_vector_only_order,
    multi_chunk_keyword_coverage,
    multi_chunk_success,
    single_chunk_hit_rank,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SPIKE_DIR = REPO_ROOT / "spike"
SOURCE_PDF_DIR = REPO_ROOT / "data" / "spike_documents"
TOP_KS = (1, 3, 5)

# Same corpus the spike's final (Step 6 closeout) benchmark used, so the
# baseline this locks in is directly comparable: doc1/doc3 (Sub-step 7,
# document_scoped hit@1/3/5 = 7/11, 10/11, 11/11; global = 7/11, 9/11,
# 11/11) plus doc4 (closeout, q27/q28 both hit@3/5=True, hit@1=False).
DOC_ID_TO_FILENAME = {
    "doc1": "新進人員實習表.pdf",
    "doc3": "2415-1304研究報告-智能貨櫃屋 .pdf",
    "doc4": "A 完整版本  鋰電池二次利用之電池管理系統開發研究完成報告.pdf",
}


def _load_questions() -> list[dict]:
    with open(SPIKE_DIR / "test_questions.json", encoding="utf-8") as f:
        data = json.load(f)
    return data["questions"]


def ensure_documents_ingested(conn) -> None:
    """Ingest any of the 3 known source PDFs not yet present as a 'ready'
    document in the production schema. Makes real OpenAI embedding calls
    for whatever isn't already there -- expected to be a one-time cost the
    first time this runs against a fresh database.
    """
    provider = OpenAIEmbeddingProvider()
    for doc_id, file_name in DOC_ID_TO_FILENAME.items():
        existing = conn.execute(
            sql_text("SELECT status FROM documents WHERE file_name = :file_name ORDER BY id DESC LIMIT 1"),
            {"file_name": file_name},
        ).mappings().first()
        if existing is not None and existing["status"] == "ready":
            continue

        pdf_path = SOURCE_PDF_DIR / file_name
        if not pdf_path.exists():
            raise FileNotFoundError(f"source PDF for {doc_id} not found at {pdf_path}")

        result = ingest_pdf_document(conn, str(pdf_path), file_name, provider)
        if result.status != "ready":
            raise RuntimeError(f"ingestion of {doc_id} ({file_name}) did not reach 'ready': {result}")


def _rows_to_evaluated(rows_or_scored, expected_file_name: str, expected_pdf_page, expected_keywords, is_scored: bool):
    evaluated = []
    for r in rows_or_scored:
        if is_scored:
            candidate = {
                "file_name": r.file_name,
                "pdf_page_number_start": r.pdf_page_number_start,
                "pdf_page_number_end": r.pdf_page_number_end,
                "content": r.content,
            }
        else:
            candidate = {
                "file_name": r["file_name"],
                "pdf_page_number_start": r["pdf_page_number_start"],
                "pdf_page_number_end": r["pdf_page_number_end"],
                "content": r["content"],
            }
        evaluated.append(evaluate_candidate(candidate, expected_file_name, expected_pdf_page, expected_keywords))
    return evaluated


def _chunk_ids(rows_or_scored, is_scored: bool) -> list[str]:
    if is_scored:
        return [r.chunk_id for r in rows_or_scored]
    return [r["chunk_id"] for r in rows_or_scored]


def _texts(rows_or_scored, is_scored: bool, limit: int) -> list[str]:
    if is_scored:
        return [r.content for r in rows_or_scored[:limit]]
    return [r["content"] for r in rows_or_scored[:limit]]


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
    document_scoped = scope == "document_scoped"
    results = {}
    api_calls = 0
    total_tokens = 0

    for q in questions:
        if not q["retrieval_eval_eligible"]:
            continue

        doc_id = q["source_document"]
        expected_file_name = DOC_ID_TO_FILENAME[doc_id]

        document_row = None
        if document_scoped:
            document_row = conn.execute(
                sql_text("SELECT id FROM documents WHERE file_name = :file_name AND status = 'ready'"),
                {"file_name": expected_file_name},
            ).mappings().first()

        expected_pdf_page = (q.get("expected_location") or {}).get("pdf_page_number")
        keywords = q.get("expected_content_keywords") or []

        embed_result = provider.embed_batch([q["question"]])
        api_calls += 1
        total_tokens += embed_result.total_tokens or 0
        query_vector = embed_result.results[0].vector

        date_candidates = extract_date_candidates(q["question"])
        table_query = looks_like_table_question(q["question"])

        rows = fetch_candidates(
            conn,
            query_vector,
            document_id=document_row["id"] if document_row else None,
            pool_size=30,
        )
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
            vector_evaluated = _rows_to_evaluated(rows, expected_file_name, expected_pdf_page, keywords, is_scored=False)
            hybrid_evaluated = _rows_to_evaluated(scored, expected_file_name, expected_pdf_page, keywords, is_scored=True)
            q_result["vector_only"] = _grade_single_chunk(vector_evaluated)
            q_result["hybrid"] = _grade_single_chunk(hybrid_evaluated)
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

    provider = OpenAIEmbeddingProvider()
    questions = _load_questions()

    excluded = [
        {"id": q["id"], "source_document": q["source_document"], "reason": q.get("eligibility_reason")}
        for q in questions
        if not q["retrieval_eval_eligible"]
    ]

    report = {"weights_used": WEIGHTS, "excluded_questions": excluded}

    with get_connection() as conn:
        ensure_documents_ingested(conn)

        scoped = run_scope(conn, provider, questions, "document_scoped")
        global_ = run_scope(conn, provider, questions, "global")

    report["document_scoped"] = {k: v for k, v in scoped.items() if k != "scope"}
    report["global"] = {k: v for k, v in global_.items() if k != "scope"}
    report["total_api_calls"] = scoped["api_calls"] + global_["api_calls"]
    report["total_tokens"] = scoped["total_tokens"] + global_["total_tokens"]

    out_path = Path(__file__).resolve().parent / "retrieval_benchmark_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"document_scoped api_calls={scoped['api_calls']} tokens={scoped['total_tokens']}")
    print(f"global api_calls={global_['api_calls']} tokens={global_['total_tokens']}")
    print(f"excluded_questions={len(excluded)}")
    print(f"Full report written to {out_path}")


if __name__ == "__main__":
    main()
