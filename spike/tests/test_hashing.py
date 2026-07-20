"""Tests for Step 6 Sub-step 4 deterministic hashing.

Run from the project root: python -m pytest spike/tests -v
"""

from spike.hashing import (
    compute_chunk_id,
    compute_chunk_metadata_hash,
    compute_embedding_content_hash,
    hash_text,
)


def test_embedding_content_hash_is_deterministic():
    assert compute_embedding_content_hash("hello") == compute_embedding_content_hash("hello")


def test_embedding_content_hash_differs_for_different_text():
    assert compute_embedding_content_hash("hello") != compute_embedding_content_hash("hello!")


def test_chunk_id_is_deterministic_for_identical_inputs():
    kwargs = dict(
        document_content_hash="doc123",
        strategy_name="structured_600_100",
        chunk_type="table",
        page_index_start=62,
        page_index_end=63,
        embedding_content_hash=hash_text("some chunk text"),
    )
    assert compute_chunk_id(**kwargs) == compute_chunk_id(**kwargs)


def test_chunk_id_changes_when_text_changes():
    base = dict(
        document_content_hash="doc123",
        strategy_name="structured_600_100",
        chunk_type="table",
        page_index_start=62,
        page_index_end=63,
    )
    id_a = compute_chunk_id(**base, embedding_content_hash=hash_text("version A"))
    id_b = compute_chunk_id(**base, embedding_content_hash=hash_text("version B"))
    assert id_a != id_b


def test_chunk_id_does_not_depend_on_a_database_serial_id():
    # No database interaction at all -- chunk_id is pure function of its inputs.
    kwargs = dict(
        document_content_hash="doc123",
        strategy_name="structured_600_100",
        chunk_type="prose",
        page_index_start=0,
        page_index_end=0,
        embedding_content_hash=hash_text("text"),
    )
    ids = {compute_chunk_id(**kwargs) for _ in range(5)}
    assert len(ids) == 1


def test_chunk_metadata_hash_independent_of_text_and_page_range():
    # chunk_metadata_hash intentionally covers only non-text, non-page-range
    # fields (page range is already part of chunk_id).
    meta_a = {"printed_page_number_list": ["52", "53"], "section_title": "四、實驗結果", "table_title": "表4"}
    meta_b = dict(meta_a)
    assert compute_chunk_metadata_hash(meta_a) == compute_chunk_metadata_hash(meta_b)


def test_chunk_metadata_hash_changes_when_section_title_changes():
    meta_a = {"printed_page_number_list": ["52"], "section_title": "old title", "table_title": None}
    meta_b = {"printed_page_number_list": ["52"], "section_title": "new title", "table_title": None}
    assert compute_chunk_metadata_hash(meta_a) != compute_chunk_metadata_hash(meta_b)
