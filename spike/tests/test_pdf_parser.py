"""Minimal tests for Step 6 Sub-step 2 (text/near_empty/scanned detection + metadata shape).

Run from the project root: python -m pytest spike/tests -v
"""

from pathlib import Path

import pytest

from spike.pdf_parser import (
    PAGE_STATUS_NEAR_EMPTY,
    PAGE_STATUS_SCANNED,
    PAGE_STATUS_TEXT,
    TEXT_LENGTH_THRESHOLD,
    parse_pdf_pages,
)

DOCS_DIR = Path(__file__).resolve().parents[2] / "data" / "spike_documents"

SCANNED_DOC = DOCS_DIR / "新進人員實習表.pdf"
BMS_DOC = DOCS_DIR / "A 完整版本  鋰電池二次利用之電池管理系統開發研究完成報告.pdf"
TEXT_DOCS = [
    DOCS_DIR / "2415-1305研究報告-太陽光發電預測.pdf",
    DOCS_DIR / "2415-1304研究報告-智能貨櫃屋 .pdf",
    BMS_DOC,
]


def test_scanned_document_detected_as_scanned():
    pages = parse_pdf_pages(str(SCANNED_DOC))
    assert len(pages) == 1
    assert pages[0].page_status == PAGE_STATUS_SCANNED
    assert pages[0].is_scanned is True
    assert pages[0].extraction_method == "none"


@pytest.mark.parametrize("pdf_path", TEXT_DOCS)
def test_text_document_body_page_detected_as_text_based(pdf_path):
    pages = parse_pdf_pages(str(pdf_path))
    assert len(pages) > 20
    # page_index 20 falls inside the running body text for all three
    # text-based reports (well past cover/disclaimer/abstract front matter).
    body_page = pages[20]
    assert body_page.page_status == PAGE_STATUS_TEXT
    assert body_page.is_scanned is False
    assert body_page.extraction_method == "text_layer"
    assert body_page.char_count > TEXT_LENGTH_THRESHOLD


def test_near_empty_page_not_classified_as_scanned():
    # page_index=16 in the BMS report is a near-blank front-matter divider
    # page containing only the printed roman numeral "XIII" (4 chars, no
    # meaningful image content) -- confirmed by manual visual inspection this
    # session. It must be classified as near_empty, not scanned, and must not
    # be routed to OCR.
    pages = parse_pdf_pages(str(BMS_DOC))
    divider_page = pages[16]
    assert divider_page.char_count < TEXT_LENGTH_THRESHOLD
    assert divider_page.page_status == PAGE_STATUS_NEAR_EMPTY
    assert divider_page.is_scanned is False
    assert divider_page.extraction_method == "none"


def test_page_metadata_has_all_four_required_fields():
    pages = parse_pdf_pages(str(TEXT_DOCS[0]))
    sample = pages[0]
    assert sample.pdf_page_number == sample.page_index + 1
    assert isinstance(sample.printed_page_number, (str, type(None)))
    assert isinstance(sample.section_title, (str, type(None)))


def test_printed_page_number_detected_on_known_body_page():
    # For the "低碳綠能與儲能整合技術研究" report, page_index=11 (0-based) is
    # printed page "1" (first body page, right after 11 pages of front matter).
    pages = parse_pdf_pages(str(TEXT_DOCS[1]))
    assert pages[11].printed_page_number == "1"
