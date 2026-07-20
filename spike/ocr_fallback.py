"""Step 6 Sub-step 2: OCR fallback for pages flagged as scanned.

Only invoked for pages where pdf_parser.parse_pdf_pages() found no usable
text layer. Uses easyocr with a traditional-Chinese + English reader
(CPU-only; see requirements.txt / environment.yml for the pinned versions).
"""

from __future__ import annotations

import numpy as np
import easyocr

from spike.pdf_parser import (
    PAGE_STATUS_OCR_FAILED,
    PAGE_STATUS_SCANNED,
    TEXT_LENGTH_THRESHOLD,
    PageParseResult,
    render_page_to_image,
)

_READER: easyocr.Reader | None = None


def get_reader() -> easyocr.Reader:
    """Lazily create and cache the OCR reader (model load is slow)."""
    global _READER
    if _READER is None:
        _READER = easyocr.Reader(["ch_tra", "en"], gpu=False)
    return _READER


def ocr_page(pdf_path: str, result: PageParseResult) -> PageParseResult:
    """Run OCR on a page classified as "scanned" and update its PageParseResult.

    Only intended for result.page_status == PAGE_STATUS_SCANNED (near_empty
    pages should not reach here; see run_parsing_validation.py's dispatch).
    If the OCR output is still below the usable-text threshold, the page is
    reclassified to "ocr_failed" rather than silently left as "scanned" with
    unusable text.
    """
    samples, width, height, channels = render_page_to_image(pdf_path, result.page_index)
    image = np.frombuffer(samples, dtype=np.uint8).reshape(height, width, channels)
    if channels == 4:
        image = image[:, :, :3]  # drop alpha channel; easyocr expects RGB

    reader = get_reader()
    lines = reader.readtext(image, detail=0, paragraph=True)
    text = "\n".join(lines)
    char_count = len(text.strip())

    result.text = text
    result.char_count = char_count
    result.extraction_method = "ocr"
    if result.page_status == PAGE_STATUS_SCANNED and char_count < TEXT_LENGTH_THRESHOLD:
        result.page_status = PAGE_STATUS_OCR_FAILED
    return result
