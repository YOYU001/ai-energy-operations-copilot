"""Step 10 Sub-step 2: OCR fallback for pages flagged as scanned.

Ported from spike/ocr_fallback.py (Step 6 Sub-step 2), with one deliberate
change: the OCR reader is no longer a bare module-level global singleton.
spike/ocr_fallback.py's `_READER`/`get_reader()` pattern is fine for a
single-process offline script, but is not safe to reuse as-is in a
multi-request FastAPI process (no lifecycle control, no concurrency story).

This module instead exposes:
  - `OcrReader`: a Protocol describing the one method ocr_page() actually
    calls (`readtext`), so tests can inject a fake without ever importing
    easyocr or loading a real model.
  - `EasyOcrReaderProvider`: lazily creates and caches a real
    easyocr.Reader, matching the spike's lazy-load behavior, but as an
    instance you construct and own (e.g. one per app process) instead of a
    module global. Where exactly that instance lives and how concurrent
    requests share it is a FastAPI application-lifecycle decision left to
    the ingestion orchestration sub-step -- this module only defines the
    interface.
  - `ocr_page()`: the OCR algorithm itself, unchanged, now taking a reader
    explicitly instead of reaching for a global.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from app.services.pdf_parser import (
    PAGE_STATUS_OCR_FAILED,
    PAGE_STATUS_SCANNED,
    TEXT_LENGTH_THRESHOLD,
    PageParseResult,
    render_page_to_image,
)


class OcrReader(Protocol):
    """The subset of easyocr.Reader's interface ocr_page() actually uses."""

    def readtext(self, image, detail: int = 0, paragraph: bool = True) -> list[str]: ...


class EasyOcrReaderProvider:
    """Lazily creates and caches a real easyocr.Reader instance.

    easyocr is imported lazily inside get_reader(), not at module import
    time, so constructing this provider (or importing this module) never
    requires easyocr/torch to be installed unless OCR is actually invoked --
    matching how OpenAIEmbeddingProvider lazily imports `openai`.
    """

    def __init__(self, languages: tuple[str, ...] = ("ch_tra", "en"), gpu: bool = False):
        self._languages = list(languages)
        self._gpu = gpu
        self._reader: OcrReader | None = None

    def get_reader(self) -> OcrReader:
        if self._reader is None:
            import easyocr

            self._reader = easyocr.Reader(self._languages, gpu=self._gpu)
        return self._reader


def ocr_page(pdf_path: str, result: PageParseResult, reader: OcrReader) -> PageParseResult:
    """Run OCR on a page classified as "scanned" and update its PageParseResult.

    Only intended for result.page_status == PAGE_STATUS_SCANNED (near_empty
    pages should not reach here). If the OCR output is still below the
    usable-text threshold, the page is reclassified to "ocr_failed" rather
    than silently left as "scanned" with unusable text.
    """
    samples, width, height, channels = render_page_to_image(pdf_path, result.page_index)
    image = np.frombuffer(samples, dtype=np.uint8).reshape(height, width, channels)
    if channels == 4:
        image = image[:, :, :3]  # drop alpha channel; easyocr expects RGB

    lines = reader.readtext(image, detail=0, paragraph=True)
    text = "\n".join(lines)
    char_count = len(text.strip())

    result.text = text
    result.char_count = char_count
    result.extraction_method = "ocr"
    if result.page_status == PAGE_STATUS_SCANNED and char_count < TEXT_LENGTH_THRESHOLD:
        result.page_status = PAGE_STATUS_OCR_FAILED
    return result
