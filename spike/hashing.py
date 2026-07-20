"""Step 6 Sub-step 4: deterministic hashing helpers.

chunk_id must not depend on a database SERIAL id (it needs to be the same
across repeated ingestion runs of the same input). It is derived from:
document_content_hash + strategy_name + chunk_type + page range +
embedding_content_hash. Because embedding_content_hash is itself derived
from the chunk's text, a chunk whose text changes automatically gets a new
chunk_id (the old one becomes a stale/inactive row, never silently
overwritten) -- see spike/vector_store.py for how that plays out during
ingestion.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_document_content_hash(pdf_path: str) -> str:
    """Hash of the raw PDF file bytes -- identifies the source document's
    content identity independent of how it gets parsed/chunked."""
    return hash_bytes(Path(pdf_path).read_bytes())


def compute_embedding_content_hash(text: str) -> str:
    """Hash of exactly the text that gets sent to the embedding API."""
    return hash_text(text)


def compute_chunk_metadata_hash(metadata: dict) -> str:
    """Hash of everything about a chunk *other than* its text/embedding
    (page ranges are intentionally excluded too, since they're already part
    of chunk_id; this covers the fields that can change without the chunk's
    identity changing, e.g. an improved section_title heuristic)."""
    canonical = json.dumps(metadata, sort_keys=True, ensure_ascii=False, default=str)
    return hash_text(canonical)


def compute_chunk_id(
    *,
    document_content_hash: str,
    strategy_name: str,
    chunk_type: str,
    page_index_start: int,
    page_index_end: int,
    embedding_content_hash: str,
) -> str:
    parts = (
        f"{document_content_hash}:{strategy_name}:{chunk_type}:"
        f"{page_index_start}:{page_index_end}:{embedding_content_hash}"
    )
    return hash_text(parts)
