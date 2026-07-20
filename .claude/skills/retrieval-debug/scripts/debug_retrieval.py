"""retrieval-debug: run a query through both vector-only and hybrid retrieval,
printing each candidate's FULL text (not a truncated preview) alongside its
score breakdown.

This exists because Sub-step 4 misjudged q06 as a "wrong date" retrieval
failure from a 150-char text_preview, and Sub-step 5 only found out it was a
misreading (the full 547-char stored text actually contained the correct
date group all along) by going back and reading the complete text. This
script prints the complete text from the start so that mistake is structurally
harder to repeat.

Makes 1 real OpenAI embedding API call (the query itself); negligible cost
per Sub-step 5/7's measurements. Requires the database to already have
ingested chunks.

Run from the project root:
    python .claude/skills/retrieval-debug/scripts/debug_retrieval.py "<query text>" [filename_filter] [top_k]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def _print_candidate(rank: int, scored) -> None:
    print(f"\n  [{rank}] chunk_id={scored.chunk_id}  type={scored.chunk_type}  file={scored.filename}")
    print(
        f"      final_score={scored.final_score:.4f}  "
        f"(semantic={scored.semantic_score:.4f}, vector_distance={scored.vector_distance:.4f}, "
        f"exact_date_match={scored.exact_date_match}, table_query_match={scored.table_query_match})"
    )
    print(f"      pages: pdf {scored.pdf_page_number_start}-{scored.pdf_page_number_end}  section={scored.section_title}")
    print("      full text:")
    for line in scored.text.splitlines():
        print(f"        {line}")


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print('Usage: python debug_retrieval.py "<query text>" [filename_filter] [top_k]')
        return 1

    query_text = args[0]
    filename_filter = args[1] if len(args) >= 2 and args[1] else None
    top_k = int(args[2]) if len(args) >= 3 else 5

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

    if not os.environ.get("OPENAI_API_KEY"):
        print("[retrieval-debug] OPENAI_API_KEY not set in .env -- refusing to proceed (this call costs a small amount of real money).")
        return 1
    if not os.environ.get("DATABASE_URL"):
        print("[retrieval-debug] DATABASE_URL not set in .env")
        return 1

    from sqlalchemy import create_engine

    from spike.embedding_provider import OpenAIEmbeddingProvider
    from spike.hybrid_retrieval import fetch_candidates, score_candidates
    from spike.query_parser import extract_date_candidates, looks_like_table_question

    engine = create_engine(os.environ["DATABASE_URL"])
    provider = OpenAIEmbeddingProvider()

    print(f'[retrieval-debug] query: "{query_text}"')
    print(f"[retrieval-debug] filename_filter: {filename_filter or '(none -- global cross-document search)'}")
    print("[retrieval-debug] embedding query (1 API call) ...")

    embed_result = provider.embed_batch([query_text])
    query_vector = embed_result.results[0].vector

    date_candidates = extract_date_candidates(query_text)
    table_query = looks_like_table_question(query_text)
    date_strs = [f"{dc.year}年{dc.month}月{dc.day}日" for dc in date_candidates]
    print(f"[retrieval-debug] parsed signals: date_candidates={date_strs}, looks_like_table_question={table_query}")

    with engine.connect() as conn:
        rows = fetch_candidates(conn, query_vector, filename_filter)

    hybrid_scored = score_candidates(rows, date_candidates, table_query)
    vector_only_scored = score_candidates(rows, [], False)  # no signals fired => pure semantic order

    print(f"\n{'=' * 70}\n[retrieval-debug] VECTOR-ONLY top {top_k}\n{'=' * 70}")
    for i, s in enumerate(vector_only_scored[:top_k], start=1):
        _print_candidate(i, s)

    print(f"\n{'=' * 70}\n[retrieval-debug] HYBRID top {top_k}\n{'=' * 70}")
    for i, s in enumerate(hybrid_scored[:top_k], start=1):
        _print_candidate(i, s)

    vector_only_ids = [s.chunk_id for s in vector_only_scored[:top_k]]
    hybrid_ids = [s.chunk_id for s in hybrid_scored[:top_k]]
    if vector_only_ids == hybrid_ids:
        print("\n[retrieval-debug] Ranking identical between vector-only and hybrid (no date/table signal changed the order).")
    else:
        promoted = [cid for cid in hybrid_ids if cid not in vector_only_ids]
        print(f"\n[retrieval-debug] Hybrid ranking differs from vector-only. Newly promoted into top {top_k}: {promoted}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
