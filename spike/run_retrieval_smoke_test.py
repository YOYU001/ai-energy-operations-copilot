"""Step 6 Sub-step 4 driver: minimal retrieval smoke test.

Loads q06 and q11 (the only "verified"-tier questions in
spike/test_questions.json), embeds each question's text with the same
provider used for ingestion, and does a brute-force cosine-distance query
against spike_document_chunks (no vector index -- out of scope this round).
For each question, checks whether any of the top-5 results' page range
overlaps the question's expected_location.

Run from the project root (after spike/run_embedding_ingestion.py):
    python -m spike.run_retrieval_smoke_test
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text as sql_text

load_dotenv()

from spike.embedding_provider import OpenAIEmbeddingProvider

SPIKE_DIR = Path(__file__).resolve().parent
TOP_K = 5

DOC_ID_TO_FILENAME = {
    "doc1": "新進人員實習表.pdf",
    "doc3": "2415-1304研究報告-智能貨櫃屋 .pdf",
}


def _load_verified_questions() -> list[dict]:
    with open(SPIKE_DIR / "test_questions.json", encoding="utf-8") as f:
        data = json.load(f)
    return [q for q in data["questions"] if q["verification_tier"] == "verified"]


def _page_ranges_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start <= b_end and b_start <= a_end


def run_query(conn, provider, query_text: str, filename_filter: str, top_k: int = TOP_K) -> list[dict]:
    embed_result = provider.embed_batch([query_text])
    query_vector = embed_result.results[0].vector

    rows = conn.execute(
        sql_text(
            """
            SELECT c.chunk_id, c.chunk_type, c.text, c.pdf_page_number_start,
                   c.pdf_page_number_end, c.printed_page_number_map, c.section_title,
                   c.table_title, (c.embedding <=> CAST(:qv AS vector)) AS distance
            FROM spike_document_chunks c
            JOIN spike_documents d ON d.id = c.document_id
            WHERE d.filename = :filename AND c.is_active = true
            ORDER BY c.embedding <=> CAST(:qv AS vector)
            LIMIT :k
            """
        ),
        {"qv": str(query_vector), "filename": filename_filter, "k": top_k},
    ).mappings().all()
    return [dict(r) for r in rows]


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY not set in environment (.env) -- refusing to proceed")

    engine = create_engine(os.environ["DATABASE_URL"])
    provider = OpenAIEmbeddingProvider()

    questions = _load_verified_questions()
    report = {}

    with engine.connect() as conn:
        for q in questions:
            doc_id = q["source_document"]
            filename = DOC_ID_TO_FILENAME[doc_id]
            expected = q["expected_location"] or {}
            expected_pdf_page = expected.get("pdf_page_number")

            results = run_query(conn, provider, q["question"], filename)

            hit = False
            if expected_pdf_page is not None:
                for r in results:
                    if _page_ranges_overlap(
                        r["pdf_page_number_start"], r["pdf_page_number_end"], expected_pdf_page, expected_pdf_page
                    ):
                        hit = True
                        break

            report[q["id"]] = {
                "question": q["question"],
                "expected_location": expected,
                "top_k": [
                    {
                        "chunk_id": r["chunk_id"],
                        "chunk_type": r["chunk_type"],
                        "pdf_page_number_range": [r["pdf_page_number_start"], r["pdf_page_number_end"]],
                        "printed_page_number_map": r["printed_page_number_map"],
                        "section_title": r["section_title"],
                        "table_title": r["table_title"],
                        "distance": float(r["distance"]),
                        "text_preview": r["text"][:150],
                    }
                    for r in results
                ],
                "citation_page_correctness_hit": hit,
            }
            print(f"{q['id']}: top-{TOP_K} retrieved, expected_pdf_page={expected_pdf_page}, hit={hit}")

    out_path = SPIKE_DIR / "retrieval_smoke_test_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFull report written to {out_path}")


if __name__ == "__main__":
    main()
