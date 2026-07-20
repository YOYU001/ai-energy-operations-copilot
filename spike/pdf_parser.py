"""Step 6 Sub-step 2: text-based PDF page parsing and scanned-page detection.

Scope for this sub-step only: per-page text extraction via the PDF text layer,
a four-way page classification (text / near_empty / scanned / ocr_failed), and
page-level metadata (page_index / pdf_page_number / printed_page_number /
section_title). OCR itself lives in ocr_fallback.py. Chunking, embedding, and
retrieval are explicitly out of scope here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import fitz  # PyMuPDF

# Below this character count (after stripping whitespace), a page has no
# usable text layer and needs further classification (near_empty vs scanned).
TEXT_LENGTH_THRESHOLD = 20

# When a low-text page's embedded images cover at least this fraction of the
# page area, it is classified as "scanned" (i.e. the page is essentially a
# photograph/scan of content). Below this, it is "near_empty" (a legitimate
# near-blank page, e.g. a front-matter divider with only a page number).
IMAGE_COVERAGE_THRESHOLD = 0.5

PAGE_STATUS_TEXT = "text"
PAGE_STATUS_NEAR_EMPTY = "near_empty"
PAGE_STATUS_SCANNED = "scanned"
PAGE_STATUS_OCR_FAILED = "ocr_failed"

# Matches a standalone printed page number: pure digits (1-4 of them) or a
# roman numeral, on its own line. Applied only to the first/last non-empty
# line of a page's extracted text, per the report layout observed in the
# spike documents (front matter uses roman numerals, body uses arabic).
_PRINTED_PAGE_NUMBER_RE = re.compile(r"^(\d{1,4}|[IVXLCDM]{1,7})$")

# Conservative section-heading patterns actually observed in the spike
# documents: top-level Chinese numeral headings ("一、...") and numbered
# subsection headings ("4.2.2 ..."). Only an exact regex match counts; no
# inference beyond this is attempted in this sub-step.
_TOP_LEVEL_HEADING_RE = re.compile(r"^[一二三四五六七八九十]+、\S")
_SUBSECTION_HEADING_RE = re.compile(r"^\d+(\.\d+){1,3}\s+\S")


@dataclass
class PageParseResult:
    page_index: int  # 0-based, internal use
    pdf_page_number: int  # 1-based, matches what a PDF viewer displays
    printed_page_number: Optional[str]  # page number printed on the page; None if not reliably detected
    section_title: Optional[str]  # heading text detected on this page; None if not reliably detected
    page_status: str  # "text" | "near_empty" | "scanned" | "ocr_failed"
    extraction_method: str  # "text_layer", "ocr", or "none" (not yet OCR'd)
    text: str = field(repr=False)
    char_count: int
    image_coverage_ratio: float = 0.0  # 0.0 for "text" pages (not computed)

    @property
    def is_scanned(self) -> bool:
        """Backward-compat convenience: True for scanned or ocr_failed pages."""
        return self.page_status in (PAGE_STATUS_SCANNED, PAGE_STATUS_OCR_FAILED)


def _detect_printed_page_number(text: str) -> Optional[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    for candidate in (lines[-1], lines[0]):
        if _PRINTED_PAGE_NUMBER_RE.match(candidate):
            return candidate
    return None


def _detect_section_title(text: str) -> Optional[str]:
    for line in text.splitlines():
        stripped = line.strip()
        if _TOP_LEVEL_HEADING_RE.match(stripped) or _SUBSECTION_HEADING_RE.match(stripped):
            return stripped
    return None


def _image_coverage_ratio(page: fitz.Page) -> float:
    """Fraction of the page area covered by embedded images (0.0-1.0).

    Approximated as the sum of each image's bounding-box area divided by the
    page area, capped at 1.0. This is a sum, not a true union, so overlapping
    images could over-count coverage; acceptable for this sub-step's coarse
    text/near_empty/scanned split, not for precise layout analysis.
    """
    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return 0.0
    total = 0.0
    for info in page.get_image_info():
        bbox = info.get("bbox")
        if not bbox:
            continue
        x0, y0, x1, y1 = bbox
        total += max(0.0, x1 - x0) * max(0.0, y1 - y0)
    return min(total / page_area, 1.0)


def _classify_page(page: fitz.Page, char_count: int) -> tuple[str, float]:
    if char_count >= TEXT_LENGTH_THRESHOLD:
        return PAGE_STATUS_TEXT, 0.0
    coverage = _image_coverage_ratio(page)
    if coverage >= IMAGE_COVERAGE_THRESHOLD:
        return PAGE_STATUS_SCANNED, coverage
    return PAGE_STATUS_NEAR_EMPTY, coverage


def parse_pdf_pages(pdf_path: str) -> list[PageParseResult]:
    """Extract per-page text from a PDF and classify each page's text/scan status."""
    results: list[PageParseResult] = []
    doc = fitz.open(pdf_path)
    try:
        for page_index, page in enumerate(doc):
            text = page.get_text("text") or ""
            char_count = len(text.strip())
            page_status, coverage = _classify_page(page, char_count)
            results.append(
                PageParseResult(
                    page_index=page_index,
                    pdf_page_number=page_index + 1,
                    printed_page_number=_detect_printed_page_number(text),
                    section_title=_detect_section_title(text),
                    page_status=page_status,
                    extraction_method="text_layer" if page_status == PAGE_STATUS_TEXT else "none",
                    text=text,
                    char_count=char_count,
                    image_coverage_ratio=coverage,
                )
            )
    finally:
        doc.close()
    return results


def render_page_to_image(pdf_path: str, page_index: int, zoom: float = 2.0):
    """Render a single PDF page to raw RGB(A) bytes for OCR consumption."""
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_index]
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix)
        return pixmap.samples, pixmap.width, pixmap.height, pixmap.n
    finally:
        doc.close()
