"""Shared test helpers for Step 10 Sub-step 3/4 tests that need a real,
tiny, deterministic PDF and a no-network embedding provider.

Used by test_ingestion_rag_integration.py, test_documents_api.py, and
test_documents_api_integration.py.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import fitz

from app.services.embedding_provider import EmbeddingBatchError, EmbeddingBatchResult, EmbeddingResult


def build_fixture_pdf(path: Path, page_texts: list[str], fontname: str | None = None) -> None:
    """Build a tiny deterministic PDF from plain-text pages.

    Pass fontname="china-ts" (PyMuPDF's built-in traditional-Chinese CJK
    font) for any fixture containing Chinese text -- the default Latin font
    cannot render CJK glyphs at all and silently produces garbage characters
    on extraction (verified: without this, Chinese fixture content came back
    as replacement-character garbage, breaking query_parser's date/table
    regex matching). Left as an opt-in parameter, not the default, because
    switching fonts measurably changes this font's line-wrap/spacing metrics
    even for plain ASCII text -- confirmed it silently changed how many
    chunks an existing English-only fixture packed into, which is exactly
    the kind of accidental cross-test coupling a shared default must avoid.
    """
    doc = fitz.open()
    for page_text in page_texts:
        page = doc.new_page()
        kwargs = {"fontsize": 11}
        if fontname is not None:
            kwargs["fontname"] = fontname
        page.insert_text((72, 72), page_text, **kwargs)
    doc.save(str(path))
    doc.close()


def deterministic_vector(text_value: str, dimensions: int = 1536) -> list[float]:
    seed = hashlib.sha256(text_value.encode("utf-8")).digest()
    values: list[float] = []
    counter = 0
    while len(values) < dimensions:
        block = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        values.extend(b / 255.0 for b in block)
        counter += 1
    return values[:dimensions]


class DeterministicFakeEmbeddingProvider:
    """Same text -> same 1536-dim vector, different text -> different
    vector, no network. Can be told to fail on a specific embed_batch call
    number to simulate a mid-ingestion embedding failure."""

    provider_name = "fake-deterministic"
    model_name = "fake-embedding-v1"
    dimensions = 1536

    def __init__(self, fail_on_call: int | None = None):
        self.call_count = 0
        self.fail_on_call = fail_on_call

    def embed_batch(self, texts: list[str]) -> EmbeddingBatchResult:
        self.call_count += 1
        if self.fail_on_call is not None and self.call_count == self.fail_on_call:
            raise EmbeddingBatchError(f"forced failure on embed_batch call {self.call_count}")
        results = [
            EmbeddingResult(
                text=t,
                vector=deterministic_vector(t, self.dimensions),
                provider=self.provider_name,
                model=self.model_name,
                dimensions=self.dimensions,
                model_version="v1",
            )
            for t in texts
        ]
        return EmbeddingBatchResult(results=results, prompt_tokens=len(texts), total_tokens=len(texts))
