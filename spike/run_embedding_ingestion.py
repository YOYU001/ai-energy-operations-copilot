"""Step 6 Sub-step 4 driver: chunk -> embed -> pgvector ingestion.

Ingests doc1 (新進人員實習表.pdf, scanned, validates Q11) and doc3
(2415-1304研究報告-智能貨櫃屋 .pdf, validates Q6) using the provisional
structured_600_100 strategy, into the spike-only schema (spike_documents /
spike_document_chunks) -- never database/schema.sql's documents /
document_chunks tables.

Run twice in the same invocation to demonstrate idempotency (second run
must make 0 new embedding API calls for unchanged input).

Run from the project root:
    python -m spike.run_embedding_ingestion
"""

from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

import os  # noqa: E402 -- must follow load_dotenv()

from spike.chunker import STRATEGIES, chunk_document
from spike.embedding_provider import OpenAIEmbeddingProvider
from spike.hashing import compute_document_content_hash
from spike.ocr_fallback import ocr_page
from spike.pdf_parser import PAGE_STATUS_SCANNED, parse_pdf_pages
from spike.vector_store import (
    IngestionStats,
    ensure_schema,
    execute_cutover_if_needed,
    get_or_create_document,
    upsert_chunks,
)

DOCS_DIR = Path(__file__).resolve().parent.parent / "data" / "spike_documents"
SPIKE_DIR = Path(__file__).resolve().parent

DOCUMENTS = {
    "doc1": "新進人員實習表.pdf",  # validates Q11 (OCR names)
    "doc3": "2415-1304研究報告-智能貨櫃屋 .pdf",  # validates Q6 (Table 4)
    "doc4": "A 完整版本  鋰電池二次利用之電池管理系統開發研究完成報告.pdf",  # validates Q15/Q27/Q28 (caption-first tables)
}

STRATEGY = next(s for s in STRATEGIES if s["name"] == "structured_600_100")  # provisional; not hard-coded elsewhere


def _load_pages_with_ocr(pdf_path: Path):
    pages = parse_pdf_pages(str(pdf_path))
    for page in pages:
        if page.page_status == PAGE_STATUS_SCANNED:
            ocr_page(str(pdf_path), page)
    return pages


def _stats_to_dict(stats: IngestionStats) -> dict:
    return {
        "total_chunks_considered": stats.total_chunks_considered,
        "inserted_new": stats.inserted_new,
        "updated_metadata_only": stats.updated_metadata_only,
        "unchanged_skipped": stats.unchanged_skipped,
        "embedding_api_calls": stats.embedding_api_calls,
        "embedded_chunk_count": stats.embedded_chunk_count,
        "prompt_tokens": stats.prompt_tokens,
        "total_tokens": stats.total_tokens,
        "failed_chunk_ids": stats.failed_chunk_ids,
    }


def run_ingestion_pass(engine, provider) -> dict:
    pass_report = {}
    with engine.connect() as conn:
        ensure_schema(conn)
        for doc_id, filename in DOCUMENTS.items():
            pdf_path = DOCS_DIR / filename
            document_content_hash = compute_document_content_hash(str(pdf_path))
            pages = _load_pages_with_ocr(pdf_path)
            db_document_id = get_or_create_document(conn, filename, document_content_hash, total_pages=len(pages))
            chunks = chunk_document(pages, filename, STRATEGY)
            stats = upsert_chunks(
                conn, db_document_id, document_content_hash, pages, chunks, provider, initial_is_active=False
            )

            cutover_action = None
            if not stats.failed_chunk_ids:
                cutover_action = execute_cutover_if_needed(conn, db_document_id)
            # else: new chunks stay is_active=false, old version (if any) stays
            # active and searchable -- cutover is never attempted on a
            # partially-failed ingestion.

            pass_report[doc_id] = {
                "filename": filename,
                "document_content_hash": document_content_hash,
                "db_document_id": db_document_id,
                "total_pages": len(pages),
                "total_chunks": len(chunks),
                "stats": _stats_to_dict(stats),
                "cutover_action": cutover_action,
            }
    return pass_report


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY not set in environment (.env) -- refusing to proceed")

    engine = create_engine(os.environ["DATABASE_URL"])
    provider = OpenAIEmbeddingProvider()

    print("=== Ingestion pass 1 ===")
    pass1 = run_ingestion_pass(engine, provider)
    for doc_id, info in pass1.items():
        print(f"{doc_id} ({info['filename']}): {info['total_chunks']} chunks, stats={info['stats']}")

    print("\n=== Ingestion pass 2 (idempotency check) ===")
    pass2 = run_ingestion_pass(engine, provider)
    for doc_id, info in pass2.items():
        print(f"{doc_id} ({info['filename']}): {info['total_chunks']} chunks, stats={info['stats']}")

    report = {"strategy": STRATEGY["name"], "pass_1": pass1, "pass_2": pass2}
    out_path = SPIKE_DIR / "embedding_ingestion_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFull report written to {out_path}")


if __name__ == "__main__":
    main()
