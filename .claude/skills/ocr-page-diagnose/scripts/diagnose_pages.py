"""ocr-page-diagnose: report the text/near_empty/scanned/ocr_failed
classification for every page of a PDF, with the raw signals (char_count,
image_coverage_ratio) that drove each decision -- so a new document's edge
cases can be visually double-checked before ingestion, the way Sub-step 2's
near-blank-divider-page false positive should have been caught earlier.

Run from the project root:
    python .claude/skills/ocr-page-diagnose/scripts/diagnose_pages.py <pdf_path> [--ocr]
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from spike.pdf_parser import (  # noqa: E402
    PAGE_STATUS_NEAR_EMPTY,
    PAGE_STATUS_OCR_FAILED,
    PAGE_STATUS_SCANNED,
    PAGE_STATUS_TEXT,
    parse_pdf_pages,
)


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("Usage: python diagnose_pages.py <pdf_path> [--ocr]")
        return 1

    pdf_path = Path(args[0])
    run_ocr = "--ocr" in args

    if not pdf_path.exists():
        print(f"[ocr-page-diagnose] PDF not found: {pdf_path}")
        return 1

    print(f"[ocr-page-diagnose] Parsing {pdf_path.name} ...")
    pages = parse_pdf_pages(str(pdf_path))

    scanned_pages = [p for p in pages if p.page_status == PAGE_STATUS_SCANNED]

    if run_ocr and scanned_pages:
        from spike.ocr_fallback import ocr_page

        print(f"[ocr-page-diagnose] Running OCR on {len(scanned_pages)} scanned page(s) (this loads the easyocr model, may take a while) ...")
        for page in scanned_pages:
            ocr_page(str(pdf_path), page)

    print(f"\n[ocr-page-diagnose] Per-page classification ({len(pages)} pages):\n")
    print(f"{'page':>5}  {'status':<12}  {'chars':>6}  {'img_coverage':>12}  {'extraction':<10}  note")
    counts: dict[str, int] = {}
    for page in pages:
        counts[page.page_status] = counts.get(page.page_status, 0) + 1
        note = ""
        if page.page_status == PAGE_STATUS_NEAR_EMPTY:
            note = "<- review: legit near-blank page, or missed scan?"
        elif page.page_status == PAGE_STATUS_SCANNED:
            note = "<- review: real scanned content"
        elif page.page_status == PAGE_STATUS_OCR_FAILED:
            note = "<- OCR ran but still unreadable"
        print(
            f"{page.pdf_page_number:>5}  {page.page_status:<12}  {page.char_count:>6}  "
            f"{page.image_coverage_ratio:>12.2f}  {page.extraction_method:<10}  {note}"
        )

    print("\n[ocr-page-diagnose] Summary:")
    for status in (PAGE_STATUS_TEXT, PAGE_STATUS_NEAR_EMPTY, PAGE_STATUS_SCANNED, PAGE_STATUS_OCR_FAILED):
        print(f"  {status}: {counts.get(status, 0)}")

    if not run_ocr and scanned_pages:
        print(
            f"\n[ocr-page-diagnose] {len(scanned_pages)} page(s) classified 'scanned' but OCR was not run "
            "(pass --ocr to actually verify their readability)."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
