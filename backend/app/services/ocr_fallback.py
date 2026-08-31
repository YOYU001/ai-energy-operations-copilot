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

import base64
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


class OcrReaderProvider(Protocol):
    """What ingest_pdf_document() actually needs from an OCR provider --
    EasyOcrReaderProvider and VisionLLMOcrReaderProvider both satisfy this
    without either needing to know the other exists."""

    def get_reader(self) -> OcrReader: ...


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


_VISION_OCR_PROMPT = (
    "Transcribe every piece of text visible in this scanned document page, exactly as "
    "printed/handwritten, preserving reading order (top to bottom, left to right; for tables, "
    "row by row). Do not translate, summarize, correct spelling, or add commentary. Output the "
    "transcribed text only -- no preamble, no explanation, no markdown formatting."
)


class VisionLLMOcrReader:
    """Alternative to EasyOcrReaderProvider's `OcrReader` (2026-08-26): uses
    a vision-capable OpenAI chat model to read a scanned page directly,
    instead of a dedicated OCR model (EasyOCR). Motivation: EasyOCR is a
    general-purpose OCR model with no scene/handwriting/stamp understanding;
    a multimodal LLM reading the page image the way a person would tends to
    be materially more accurate on messy real-world scans (verified
    end-to-end against this project's own scanned test document, see
    TODO.md 2026-08-26).

    Implements the same `OcrReader.readtext()` shape as EasyOcrReaderProvider
    on purpose, so ocr_page()/ingest_pdf_document() need zero changes to
    accept either reader -- only which provider is constructed at the call
    site changes. `readtext()` receives the same raw RGB(A) numpy array
    ocr_page() already builds from render_page_to_image(); this class
    re-encodes it to PNG here (via PyMuPDF, already a dependency -- no new
    image library needed) since the vision API needs an image payload, not
    a numpy array.
    """

    provider_name = "openai"

    def __init__(self, model: str = "gpt-4o-mini", client=None):
        self.model_name = model
        if client is not None:
            self._client = client  # test hook: inject a fake OpenAI-shaped client
        else:
            from openai import OpenAI  # imported lazily, matching OpenAIEmbeddingProvider/OpenAIChatProvider

            self._client = OpenAI()

    def readtext(self, image, detail: int = 0, paragraph: bool = True) -> list[str]:
        import fitz  # PyMuPDF, already a dependency (pdf_parser.py)

        height, width = image.shape[0], image.shape[1]
        colorspace = fitz.csRGB
        rgb_image = image[:, :, :3] if image.shape[2] == 4 else image
        pixmap = fitz.Pixmap(colorspace, width, height, rgb_image.tobytes(), 0)  # alpha=0: no alpha channel
        png_bytes = pixmap.tobytes("png")
        b64_image = base64.b64encode(png_bytes).decode("ascii")

        response = self._client.chat.completions.create(
            model=self.model_name,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _VISION_OCR_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}"}},
                    ],
                }
            ],
        )
        text = response.choices[0].message.content or ""
        return text.split("\n")


class VisionLLMOcrReaderProvider:
    """Lazily creates and caches a VisionLLMOcrReader, matching
    EasyOcrReaderProvider's lazy-construction shape so ingest_pdf_document()
    can accept either provider without caring which one it got (both only
    ever need a `.get_reader()` method)."""

    def __init__(self, model: str = "gpt-4o-mini"):
        self._model = model
        self._reader: VisionLLMOcrReader | None = None

    def get_reader(self) -> OcrReader:
        if self._reader is None:
            self._reader = VisionLLMOcrReader(model=self._model)
        return self._reader


_RECONCILIATION_PROMPT_TEMPLATE = (
    "This image is a scanned document page. Two different OCR methods transcribed its text, "
    "and they may disagree or contain errors. Compare both candidates against the image, "
    "character by character, and produce the single most accurate transcription. Preserve "
    "reading order (top to bottom, left to right; for tables, row by row). Do not translate, "
    "summarize, or add commentary. Output the corrected transcription only -- no preamble, no "
    "explanation, no markdown formatting.\n\n"
    "Candidate A:\n{candidate_a}\n\n"
    "Candidate B:\n{candidate_b}"
)


class ReconciledOcrReader:
    """Runs EasyOCR and VisionLLMOcrReader on the same page, then asks a
    vision-capable model to cross-reference both candidates against the
    original page image and produce a corrected final transcription.

    Motivation: a single real-world validation (2026-08-26, see TODO.md)
    showed neither EasyOCR nor VisionLLMOcrReader alone is reliably more
    accurate -- each makes different mistakes on the same page. Showing a
    model both candidates plus the image lets it catch cases where one
    method got a detail the other missed, without committing to either
    method as the sole source of truth. This only adds cost at document
    ingestion time (two extra model calls per scanned page), never at
    chat-query time.

    Implements the same OcrReader.readtext() shape as its two underlying
    readers, so ocr_page()/ingest_pdf_document() need zero changes -- only
    the provider constructed at the call site changes.
    """

    def __init__(self, easy_reader: OcrReader, vision_reader: VisionLLMOcrReader, client=None):
        self._easy_reader = easy_reader
        self._vision_reader = vision_reader
        # Reuse the vision reader's client/model for the reconciliation call
        # unless a distinct client is explicitly injected for testing.
        self._client = client if client is not None else vision_reader._client
        self._model = vision_reader.model_name

    def readtext(self, image, detail: int = 0, paragraph: bool = True) -> list[str]:
        import fitz  # PyMuPDF, already a dependency (pdf_parser.py)

        easy_text = "\n".join(self._easy_reader.readtext(image, detail=detail, paragraph=paragraph))
        vision_text = "\n".join(self._vision_reader.readtext(image, detail=detail, paragraph=paragraph))

        height, width = image.shape[0], image.shape[1]
        colorspace = fitz.csRGB
        rgb_image = image[:, :, :3] if image.shape[2] == 4 else image
        pixmap = fitz.Pixmap(colorspace, width, height, rgb_image.tobytes(), 0)  # alpha=0: no alpha channel
        png_bytes = pixmap.tobytes("png")
        b64_image = base64.b64encode(png_bytes).decode("ascii")

        prompt = _RECONCILIATION_PROMPT_TEMPLATE.format(candidate_a=easy_text, candidate_b=vision_text)
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}"}},
                    ],
                }
            ],
        )
        text = response.choices[0].message.content or ""
        return text.split("\n")


class ReconciledOcrReaderProvider:
    """Lazily creates and caches a ReconciledOcrReader, matching the other
    providers' lazy-construction shape."""

    def __init__(self, model: str = "gpt-4o-mini"):
        self._model = model
        self._reader: ReconciledOcrReader | None = None

    def get_reader(self) -> OcrReader:
        if self._reader is None:
            easy_reader = EasyOcrReaderProvider().get_reader()
            vision_reader = VisionLLMOcrReader(model=self._model)
            self._reader = ReconciledOcrReader(easy_reader, vision_reader)
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
