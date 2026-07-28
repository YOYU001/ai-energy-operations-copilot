"""Tests for Step 10 Sub-step 2 OCR fallback.

This is a NEW test file, not a port: the Step 6 spike never had a dedicated
pytest for ocr_fallback.py (its behavior was only ever checked via offline
scripts against real scanned pages). These tests use a fake OcrReader (no
real easyocr model load, no OpenAI/network calls) so they run fast and
without external dependencies, while still exercising the real PDF-to-image
rendering path via a real (already-used-elsewhere) fixture PDF.
"""

from pathlib import Path

from app.services.ocr_fallback import EasyOcrReaderProvider, ocr_page
from app.services.pdf_parser import PAGE_STATUS_OCR_FAILED, PAGE_STATUS_SCANNED, PageParseResult

DOCS_DIR = Path(__file__).resolve().parents[2] / "data" / "spike_documents"
SCANNED_DOC = DOCS_DIR / "新進人員實習表.pdf"


class _FakeReader:
    def __init__(self, lines):
        self._lines = lines
        self.calls = 0

    def readtext(self, image, detail=0, paragraph=True):
        self.calls += 1
        return self._lines


def _scanned_page_result() -> PageParseResult:
    return PageParseResult(
        page_index=0,
        pdf_page_number=1,
        printed_page_number=None,
        section_title=None,
        page_status=PAGE_STATUS_SCANNED,
        extraction_method="none",
        text="",
        char_count=0,
    )


def test_ocr_page_success_keeps_scanned_status_and_records_extraction_method():
    reader = _FakeReader(["姓名：王小明", "到職日期：2026年1月1日", "部門：資訊部"])
    result = ocr_page(str(SCANNED_DOC), _scanned_page_result(), reader)

    assert reader.calls == 1
    assert result.extraction_method == "ocr"
    assert result.text == "姓名：王小明\n到職日期：2026年1月1日\n部門：資訊部"
    assert result.char_count == len(result.text.strip())
    assert result.page_status == PAGE_STATUS_SCANNED  # enough text recovered, not reclassified


def test_ocr_page_still_below_threshold_reclassifies_to_ocr_failed():
    reader = _FakeReader(["x"])  # far below TEXT_LENGTH_THRESHOLD
    result = ocr_page(str(SCANNED_DOC), _scanned_page_result(), reader)

    assert result.page_status == PAGE_STATUS_OCR_FAILED


def test_ocr_page_empty_result_reclassifies_to_ocr_failed():
    reader = _FakeReader([])
    result = ocr_page(str(SCANNED_DOC), _scanned_page_result(), reader)

    assert result.text == ""
    assert result.page_status == PAGE_STATUS_OCR_FAILED


def test_easy_ocr_reader_provider_lazily_creates_and_caches_reader(monkeypatch):
    created = []

    class _StubEasyOCRReader:
        def __init__(self, languages, gpu):
            created.append((tuple(languages), gpu))

        def readtext(self, image, detail=0, paragraph=True):
            return []

    import easyocr

    monkeypatch.setattr(easyocr, "Reader", _StubEasyOCRReader)

    provider = EasyOcrReaderProvider(languages=("ch_tra", "en"), gpu=False)
    assert created == []  # constructing the provider must not load the model

    reader_a = provider.get_reader()
    reader_b = provider.get_reader()

    assert reader_a is reader_b  # cached, not re-created
    assert created == [(("ch_tra", "en"), False)]  # model loaded exactly once
