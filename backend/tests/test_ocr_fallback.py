"""Tests for Step 10 Sub-step 2 OCR fallback.

This is a NEW test file, not a port: the Step 6 spike never had a dedicated
pytest for ocr_fallback.py (its behavior was only ever checked via offline
scripts against real scanned pages). These tests use a fake OcrReader (no
real easyocr model load, no OpenAI/network calls) so they run fast and
without external dependencies, while still exercising the real PDF-to-image
rendering path via a real (already-used-elsewhere) fixture PDF.
"""

from pathlib import Path

import numpy as np

from app.services.ocr_fallback import (
    EasyOcrReaderProvider,
    ReconciledOcrReader,
    ReconciledOcrReaderProvider,
    VisionLLMOcrReader,
    VisionLLMOcrReaderProvider,
    ocr_page,
)
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


# ---------------------------------------------------------------------------
# VisionLLMOcrReader / VisionLLMOcrReaderProvider (2026-08-26): alternative
# to EasyOcrReaderProvider using a vision-capable chat model instead of a
# dedicated OCR model. No real OpenAI/network calls -- a fake client is
# injected, matching how OpenAIEmbeddingProvider's tests avoid a real
# API call.
# ---------------------------------------------------------------------------


class _FakeChoice:
    def __init__(self, content: str):
        self.message = type("_Msg", (), {"content": content})()


class _FakeCompletionResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


class _FakeChatCompletions:
    def __init__(self, content: str):
        self._content = content
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeCompletionResponse(self._content)


class _FakeChat:
    def __init__(self, content: str):
        self.completions = _FakeChatCompletions(content)


class _FakeOpenAIClient:
    def __init__(self, content: str):
        self.chat = _FakeChat(content)


def test_vision_llm_ocr_reader_sends_image_and_returns_transcribed_lines():
    fake_client = _FakeOpenAIClient("姓名：劉宥羽\n導師：廖健翔")
    reader = VisionLLMOcrReader(model="gpt-4o-mini", client=fake_client)
    image = np.zeros((10, 10, 3), dtype=np.uint8)

    lines = reader.readtext(image)

    assert lines == ["姓名：劉宥羽", "導師：廖健翔"]

    call = fake_client.chat.completions.calls[0]
    assert call["model"] == "gpt-4o-mini"
    content_parts = call["messages"][0]["content"]
    assert content_parts[0]["type"] == "text"
    assert content_parts[1]["type"] == "image_url"
    assert content_parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_vision_llm_ocr_reader_handles_rgba_input():
    fake_client = _FakeOpenAIClient("ok")
    reader = VisionLLMOcrReader(client=fake_client)
    rgba_image = np.zeros((10, 10, 4), dtype=np.uint8)

    lines = reader.readtext(rgba_image)  # must not raise on the alpha channel

    assert lines == ["ok"]


def test_vision_llm_ocr_reader_via_ocr_page_updates_result():
    fake_client = _FakeOpenAIClient("姓名：劉宥羽\n導師：廖健翔\n期間：114年09月22日")
    reader = VisionLLMOcrReader(client=fake_client)

    result = ocr_page(str(SCANNED_DOC), _scanned_page_result(), reader)

    assert result.extraction_method == "ocr"
    assert "劉宥羽" in result.text
    assert result.page_status == PAGE_STATUS_SCANNED


def test_vision_llm_ocr_reader_provider_lazily_creates_and_caches_reader(monkeypatch):
    created = []

    class _StubOpenAI:
        def __init__(self):
            created.append(1)

    import app.services.ocr_fallback as ocr_fallback_module

    monkeypatch.setattr(
        ocr_fallback_module,
        "VisionLLMOcrReader",
        lambda model="gpt-4o-mini", client=None: type("_R", (), {"readtext": lambda self, *a, **k: []})(),
    )

    provider = VisionLLMOcrReaderProvider(model="gpt-4o-mini")
    reader_a = provider.get_reader()
    reader_b = provider.get_reader()

    assert reader_a is reader_b  # cached, not re-created


# ---------------------------------------------------------------------------
# ReconciledOcrReader / ReconciledOcrReaderProvider (2026-08-26): runs
# EasyOCR + VisionLLMOcrReader on the same page, then asks a vision model to
# cross-reference both candidates against the image and produce a corrected
# final transcription.
# ---------------------------------------------------------------------------


class _FakeEasyReader:
    def __init__(self, lines):
        self._lines = lines
        self.calls = 0

    def readtext(self, image, detail=0, paragraph=True):
        self.calls += 1
        return self._lines


def test_reconciled_ocr_reader_calls_both_readers_then_reconciles_with_image():
    easy_reader = _FakeEasyReader(["姓名：劉寳羽", "導師：廖健翔"])
    fake_client = _FakeOpenAIClient("姓名：劉宥羽\n導師：廖健翔")
    vision_reader = VisionLLMOcrReader(model="gpt-4o-mini", client=fake_client)
    reader = ReconciledOcrReader(easy_reader, vision_reader)
    image = np.zeros((10, 10, 3), dtype=np.uint8)

    lines = reader.readtext(image)

    assert lines == ["姓名：劉宥羽", "導師：廖健翔"]
    assert easy_reader.calls == 1
    # vision reader called once for its own reading, once inside reconciliation
    assert len(fake_client.chat.completions.calls) == 2

    reconciliation_call = fake_client.chat.completions.calls[1]
    content_parts = reconciliation_call["messages"][0]["content"]
    prompt_text = content_parts[0]["text"]
    assert "劉寳羽" in prompt_text  # candidate A (EasyOCR) present
    assert "廖健翔" in prompt_text  # candidate B (vision) present
    assert content_parts[1]["type"] == "image_url"


def test_reconciled_ocr_reader_via_ocr_page_updates_result():
    easy_reader = _FakeEasyReader(["姓名：劉寳羽"])
    fake_client = _FakeOpenAIClient("姓名：劉宥羽\n導師：廖健翔\n期間：114年09月22日")
    vision_reader = VisionLLMOcrReader(client=fake_client)
    reader = ReconciledOcrReader(easy_reader, vision_reader)

    result = ocr_page(str(SCANNED_DOC), _scanned_page_result(), reader)

    assert result.extraction_method == "ocr"
    assert "劉宥羽" in result.text
    assert result.page_status == PAGE_STATUS_SCANNED


def test_reconciled_ocr_reader_provider_lazily_creates_and_caches_reader(monkeypatch):
    import app.services.ocr_fallback as ocr_fallback_module

    monkeypatch.setattr(
        ocr_fallback_module,
        "EasyOcrReaderProvider",
        lambda: type("_P", (), {"get_reader": lambda self: _FakeEasyReader([])})(),
    )
    monkeypatch.setattr(
        ocr_fallback_module,
        "VisionLLMOcrReader",
        lambda model="gpt-4o-mini", client=None: type(
            "_R", (), {"readtext": lambda self, *a, **k: [], "_client": None, "model_name": model}
        )(),
    )

    provider = ReconciledOcrReaderProvider(model="gpt-4o-mini")
    reader_a = provider.get_reader()
    reader_b = provider.get_reader()

    assert reader_a is reader_b  # cached, not re-created
