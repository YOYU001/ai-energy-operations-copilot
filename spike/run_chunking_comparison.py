"""Step 6 Sub-step 3 driver: compare chunking strategies across the 4 spike documents.

Loads each document via spike.pdf_parser (with OCR fallback applied exactly
as Sub-step 2 does), runs all 4 STRATEGIES from spike.chunker, and reports:
  - chunk counts, average/max chunk length per strategy
  - Table 4 splitting behavior (chunk count, whether the 2024/8/30 six-row
    group stays intact) per strategy
  - answer completeness for the "verified"-tier test questions only (q06,
    q11), per spike/test_questions.json's verification_tier field
  - basic metadata-correctness assertions (page ranges well-formed, no
    missing required fields) across every chunk produced

Run from the project root:
    python -m spike.run_chunking_comparison
"""

from __future__ import annotations

import json
from pathlib import Path

from spike.chunker import STRATEGIES, Chunk, chunk_document
from spike.ocr_fallback import ocr_page
from spike.pdf_parser import PAGE_STATUS_SCANNED, PageParseResult, parse_pdf_pages

DOCS_DIR = Path(__file__).resolve().parent.parent / "data" / "spike_documents"
SPIKE_DIR = Path(__file__).resolve().parent

DOCUMENTS = {
    "doc1": "新進人員實習表.pdf",
    "doc2": "2415-1305研究報告-太陽光發電預測.pdf",
    "doc3": "2415-1304研究報告-智能貨櫃屋 .pdf",
    "doc4": "A 完整版本  鋰電池二次利用之電池管理系統開發研究完成報告.pdf",
}


def _load_pages_with_ocr(pdf_path: Path) -> list[PageParseResult]:
    pages = parse_pdf_pages(str(pdf_path))
    for page in pages:
        if page.page_status == PAGE_STATUS_SCANNED:
            ocr_page(str(pdf_path), page)
    return pages


def _metadata_ok(chunk: Chunk) -> tuple[bool, str]:
    if chunk.page_index_range[0] > chunk.page_index_range[1]:
        return False, "page_index_range reversed"
    if chunk.pdf_page_number_range[0] != chunk.page_index_range[0] + 1:
        return False, "pdf_page_number_range start mismatch"
    if chunk.pdf_page_number_range[1] != chunk.page_index_range[1] + 1:
        return False, "pdf_page_number_range end mismatch"
    if chunk.char_count != len(chunk.text):
        return False, "char_count mismatch"
    if chunk.chunk_type not in ("prose", "table"):
        return False, "invalid chunk_type"
    if chunk.chunk_type == "table" and not chunk.table_title:
        return False, "table chunk missing table_title"
    return True, ""


def _check_q06(doc3_chunks_by_strategy: dict[str, list[Chunk]]) -> dict:
    expected_time_ranges = ["10:30~10:45", "10:45~11:00", "11:00~11:15", "14:00~14:15", "14:15~14:30", "14:30~14:45"]
    results = {}
    for name, chunks in doc3_chunks_by_strategy.items():
        candidates = [c for c in chunks if c.chunk_type == "table" and "2024 年8 月30 日" in c.text]
        if len(candidates) != 1:
            results[name] = {"complete": False, "reason": f"found in {len(candidates)} chunks, expected 1"}
            continue
        text = candidates[0].text
        missing = [t for t in expected_time_ranges if t not in text]
        results[name] = {"complete": not missing, "missing_rows": missing}
    return results


def _check_q11(doc1_chunks_by_strategy: dict[str, list[Chunk]]) -> dict:
    results = {}
    for name, chunks in doc1_chunks_by_strategy.items():
        candidates = [c for c in chunks if "劉宥羽" in c.text and "廖健翔" in c.text]
        results[name] = {"complete": len(candidates) >= 1, "chunk_count_containing_both_names": len(candidates)}
    return results


def main() -> None:
    with open(SPIKE_DIR / "test_questions.json", encoding="utf-8") as f:
        test_questions = json.load(f)
    verified_ids = [q["id"] for q in test_questions["questions"] if q["verification_tier"] == "verified"]
    print(f"Verified-tier questions used for formal completeness metric: {verified_ids}")

    pages_by_doc = {doc_id: _load_pages_with_ocr(DOCS_DIR / filename) for doc_id, filename in DOCUMENTS.items()}

    all_chunks_by_strategy: dict[str, list[Chunk]] = {s["name"]: [] for s in STRATEGIES}
    per_doc_chunks_by_strategy: dict[str, dict[str, list[Chunk]]] = {doc_id: {} for doc_id in DOCUMENTS}

    for strategy in STRATEGIES:
        for doc_id, filename in DOCUMENTS.items():
            chunks = chunk_document(pages_by_doc[doc_id], filename, strategy)
            all_chunks_by_strategy[strategy["name"]].extend(chunks)
            per_doc_chunks_by_strategy[doc_id][strategy["name"]] = chunks

    report: dict = {"strategies": {}}

    for strategy in STRATEGIES:
        name = strategy["name"]
        chunks = all_chunks_by_strategy[name]
        lengths = [c.char_count for c in chunks]
        table_chunks = [c for c in chunks if c.chunk_type == "table"]

        metadata_failures = []
        for c in chunks:
            ok, reason = _metadata_ok(c)
            if not ok:
                metadata_failures.append({"chunk_id": c.chunk_id, "reason": reason})

        report["strategies"][name] = {
            "config": strategy,
            "total_chunks": len(chunks),
            "prose_chunks": len(chunks) - len(table_chunks),
            "table_chunks": len(table_chunks),
            "avg_chunk_length": round(sum(lengths) / len(lengths), 1) if lengths else 0,
            "max_chunk_length": max(lengths) if lengths else 0,
            "metadata_check": {
                "total_checked": len(chunks),
                "failures": len(metadata_failures),
                "failure_details": metadata_failures[:10],
            },
        }

    doc3_by_strategy = {s["name"]: per_doc_chunks_by_strategy["doc3"][s["name"]] for s in STRATEGIES}
    doc1_by_strategy = {s["name"]: per_doc_chunks_by_strategy["doc1"][s["name"]] for s in STRATEGIES}

    report["table4_split_check"] = _check_q06(doc3_by_strategy)
    report["q11_ocr_names_check"] = _check_q11(doc1_by_strategy)

    for strategy in STRATEGIES:
        name = strategy["name"]
        report["strategies"][name]["q06_table_completeness"] = report["table4_split_check"][name]["complete"]
        report["strategies"][name]["q11_completeness"] = report["q11_ocr_names_check"][name]["complete"]
        verified_pass = sum(
            [
                report["table4_split_check"][name]["complete"],
                report["q11_ocr_names_check"][name]["complete"],
            ]
        )
        report["strategies"][name]["verified_question_completeness_rate"] = f"{verified_pass}/2"

    out_path = SPIKE_DIR / "chunking_comparison_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== Chunking strategy comparison ===")
    for strategy in STRATEGIES:
        s = report["strategies"][strategy["name"]]
        print(
            f"{strategy['name']:>24}: total={s['total_chunks']:>4} "
            f"(prose={s['prose_chunks']}, table={s['table_chunks']}) "
            f"avg_len={s['avg_chunk_length']:>6} max_len={s['max_chunk_length']:>5} "
            f"meta_failures={s['metadata_check']['failures']} "
            f"verified_completeness={s['verified_question_completeness_rate']}"
        )
    print(f"\nFull report written to {out_path}")


if __name__ == "__main__":
    main()
