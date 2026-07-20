"""Step 6 Sub-step 2 driver.

Parses all 4 spike candidate PDFs page-by-page, applies OCR fallback only to
pages classified as "scanned" (near_empty pages are left as-is; they are not
scans and OCR would add nothing), and writes a JSON report for manual review
against the 17 test questions in spike/test_questions.json.

Run from the project root:
    python -m spike.run_parsing_validation
"""

from __future__ import annotations

import json
from pathlib import Path

from spike.ocr_fallback import ocr_page
from spike.pdf_parser import PAGE_STATUS_SCANNED, parse_pdf_pages

DOCS_DIR = Path(__file__).resolve().parent.parent / "data" / "spike_documents"

DOCUMENTS = [
    "新進人員實習表.pdf",
    "2415-1305研究報告-太陽光發電預測.pdf",
    "2415-1304研究報告-智能貨櫃屋 .pdf",
    "A 完整版本  鋰電池二次利用之電池管理系統開發研究完成報告.pdf",
]


def main() -> None:
    report: dict[str, dict] = {}

    for filename in DOCUMENTS:
        pdf_path = DOCS_DIR / filename
        if not pdf_path.exists():
            report[filename] = {"error": "file not found"}
            print(f"{filename}: NOT FOUND at {pdf_path}")
            continue

        pages = parse_pdf_pages(str(pdf_path))

        ocr_applied = 0
        for result in pages:
            if result.page_status == PAGE_STATUS_SCANNED:
                ocr_page(str(pdf_path), result)
                ocr_applied += 1

        status_counts: dict[str, int] = {}
        for r in pages:
            status_counts[r.page_status] = status_counts.get(r.page_status, 0) + 1

        report[filename] = {
            "total_pages": len(pages),
            "status_counts": status_counts,
            "ocr_applied": ocr_applied,
            "pages": [
                {
                    "page_index": r.page_index,
                    "pdf_page_number": r.pdf_page_number,
                    "printed_page_number": r.printed_page_number,
                    "section_title": r.section_title,
                    "page_status": r.page_status,
                    "image_coverage_ratio": round(r.image_coverage_ratio, 3),
                    "extraction_method": r.extraction_method,
                    "char_count": r.char_count,
                    "text_preview": r.text[:200],
                }
                for r in pages
            ],
        }
        print(f"{filename}: {len(pages)} pages, status_counts={status_counts}, {ocr_applied} OCR'd")

    out_path = Path(__file__).resolve().parent / "parsing_validation_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Full report written to {out_path}")


if __name__ == "__main__":
    main()
