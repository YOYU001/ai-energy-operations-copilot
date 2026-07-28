"""Step 10 Sub-step 3: RAG ingestion orchestration.

Ported logic from spike/vector_store.py (Step 6 Sub-step 4/6), but split so
that document_chunks_queries.py holds only DB primitives (execute, no
commit/rollback) and this module owns the transaction boundaries -- matching
the existing production convention (datasets_queries.py / main.py) instead
of spike's self-committing query functions.

Data flow: file -> hash -> parse -> OCR -> chunk -> embed -> persist -> cutover.

Transaction boundaries (see docs/RAG_SPIKE_PLAN.md §17 and the Sub-step 3
planning discussion):
  - create_processing_document is committed immediately, so the document
    row is inspectable/retryable even if everything after it fails.
  - New chunks are inserted is_active=false, one embedding batch at a time,
    each batch committed as soon as it succeeds (a failed batch writes
    nothing). This is safe without a single giant transaction because
    inactive rows are never visible to retrieval -- so partial progress
    here can never corrupt the currently-active version.
  - The blue-green cutover (activate new + deactivate old) is the one step
    that must be atomic: it runs in its own try/except, rolling back and
    re-raising on any failure, so the old active generation is never left
    partially replaced.
  - Any failure after the document row exists marks documents.status =
    'failed' (its own commit) before propagating the exception -- the
    document is never left silently in 'processing'.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.document_chunks_queries import (
    activate_new_and_deactivate_old_chunks,
    create_processing_document,
    find_supersede_candidate,
    get_chunk_activation_counts,
    get_document_by_content_hash,
    get_document_by_id,
    get_existing_chunk_hashes,
    insert_inactive_chunk,
    update_chunk_metadata,
    update_document_status,
    update_document_total_pages,
)
from app.services.chunker import STRATEGIES, chunk_document
from app.services.embedding_provider import EmbeddingBatchError, EmbeddingProvider
from app.services.hashing import compute_chunk_id, compute_chunk_metadata_hash, compute_document_content_hash, compute_embedding_content_hash
from app.services.ocr_fallback import EasyOcrReaderProvider, OcrReader, ocr_page
from app.services.pdf_parser import PAGE_STATUS_SCANNED, PageParseResult, parse_pdf_pages

DEFAULT_STRATEGY_NAME = "structured_600_100"
EMBED_BATCH_SIZE = 96

# Canonical document.status values (Step 10 Sub-step 4 confirms these as the
# only document-level statuses -- there is no document-level "ocr_failed":
# that is a page-level classification (see pdf_parser.PAGE_STATUS_OCR_FAILED)
# that does not by itself stop ingestion. A page whose OCR failed simply
# contributes whatever (possibly empty) text it has to chunking; the
# document still reaches "ready" if nothing else fails. This is a known,
# accepted MVP limitation: there is currently no document- or chunk-level
# signal that a given page's OCR failed, only the per-page PageParseResult
# produced during ingestion (not persisted).
READY_STATUS = "ready"
FAILED_STATUS = "failed"
PROCESSING_STATUS = "processing"


class ChunkLifecycleAnomalyError(RuntimeError):
    """A document_id has both active and inactive chunks simultaneously.

    This violates the one-active-version invariant the rest of the lifecycle
    logic depends on. Ingestion stops for manual investigation rather than
    silently resolving it either way.
    """


@dataclass
class IngestionStats:
    total_chunks_considered: int = 0
    inserted_new: int = 0
    updated_metadata_only: int = 0
    unchanged_skipped: int = 0
    embedding_api_calls: int = 0
    embedded_chunk_count: int = 0
    prompt_tokens: int = 0
    total_tokens: int = 0
    failed_chunk_ids: list = field(default_factory=list)


@dataclass
class IngestionResult:
    document_id: int
    status: str  # "already_ingested" | "ready" | "failed"
    cutover_action: str | None  # "activated" | "already_active" | "no_chunks" | None
    stats: IngestionStats | None = None


def _build_printed_page_map(pages: list[PageParseResult], page_index_start: int, page_index_end: int) -> dict:
    mapping = {}
    for page in pages:
        if page_index_start <= page.page_index <= page_index_end:
            mapping[str(page.pdf_page_number)] = page.printed_page_number
    return mapping


def _chunk_metadata_dict(chunk) -> dict:
    return {
        "printed_page_number_list": chunk.printed_page_number_list,
        "section_title": chunk.section_title,
        "table_title": chunk.table_title,
    }


def _upsert_chunks(
    conn,
    document_id: int,
    document_content_hash: str,
    pages: list[PageParseResult],
    chunks: list,
    embedding_provider: EmbeddingProvider,
    embed_batch_size: int = EMBED_BATCH_SIZE,
) -> IngestionStats:
    stats = IngestionStats(total_chunks_considered=len(chunks))

    prepared = []
    for chunk in chunks:
        embedding_content_hash = compute_embedding_content_hash(chunk.text)
        chunk_metadata_hash = compute_chunk_metadata_hash(_chunk_metadata_dict(chunk))
        chunk_id = compute_chunk_id(
            document_content_hash=document_content_hash,
            strategy_name=chunk.strategy_name,
            chunk_type=chunk.chunk_type,
            page_index_start=chunk.page_index_range[0],
            page_index_end=chunk.page_index_range[1],
            embedding_content_hash=embedding_content_hash,
        )
        prepared.append((chunk, chunk_id, embedding_content_hash, chunk_metadata_hash))

    existing = get_existing_chunk_hashes(conn, [p[1] for p in prepared])

    to_embed = []
    to_update_metadata_only = []
    for item in prepared:
        chunk, chunk_id, embedding_content_hash, chunk_metadata_hash = item
        if chunk_id not in existing:
            to_embed.append(item)
        elif existing[chunk_id] != chunk_metadata_hash:
            to_update_metadata_only.append(item)
        else:
            stats.unchanged_skipped += 1

    for i in range(0, len(to_embed), embed_batch_size):
        batch = to_embed[i : i + embed_batch_size]
        texts = [chunk.text for chunk, _, _, _ in batch]
        try:
            batch_result = embedding_provider.embed_batch(texts)
        except EmbeddingBatchError:
            for _, chunk_id, _, _ in batch:
                stats.failed_chunk_ids.append(chunk_id)
            # A failed batch writes nothing for any chunk in it -- no
            # partial success is recorded as if it succeeded.
            continue

        stats.embedding_api_calls += 1
        stats.prompt_tokens += batch_result.prompt_tokens or 0
        stats.total_tokens += batch_result.total_tokens or 0

        for (chunk, chunk_id, embedding_content_hash, chunk_metadata_hash), embedded in zip(batch, batch_result.results):
            printed_map = _build_printed_page_map(pages, chunk.page_index_range[0], chunk.page_index_range[1])
            inserted = insert_inactive_chunk(
                conn,
                chunk_id=chunk_id,
                document_id=document_id,
                strategy_name=chunk.strategy_name,
                chunk_type=chunk.chunk_type,
                content=chunk.text,
                embedding_content_hash=embedding_content_hash,
                chunk_metadata_hash=chunk_metadata_hash,
                page_index_start=chunk.page_index_range[0],
                page_index_end=chunk.page_index_range[1],
                pdf_page_number_start=chunk.pdf_page_number_range[0],
                pdf_page_number_end=chunk.pdf_page_number_range[1],
                printed_page_number_map=printed_map,
                section_title=chunk.section_title,
                table_title=chunk.table_title,
                embedding=embedded.vector,
                embedding_provider=embedded.provider,
                embedding_model=embedded.model,
                embedding_dimensions=embedded.dimensions,
                embedding_model_version=embedded.model_version,
            )
            if inserted:
                stats.inserted_new += 1
                stats.embedded_chunk_count += 1
        conn.commit()  # this batch's inactive rows are durable now, regardless of what happens next

    for chunk, chunk_id, _, chunk_metadata_hash in to_update_metadata_only:
        printed_map = _build_printed_page_map(pages, chunk.page_index_range[0], chunk.page_index_range[1])
        update_chunk_metadata(
            conn,
            chunk_id=chunk_id,
            chunk_metadata_hash=chunk_metadata_hash,
            section_title=chunk.section_title,
            table_title=chunk.table_title,
            printed_page_number_map=printed_map,
        )
        stats.updated_metadata_only += 1
    if to_update_metadata_only:
        conn.commit()

    return stats


def _execute_cutover_if_needed(conn, document_id: int) -> str:
    """Decide whether document_id needs a blue-green cutover, based on the
    CURRENT is_active state of its chunks -- not on anything remembered from
    earlier in this call, so a retried run behaves correctly.

    Returns "already_active" | "activated" | "no_chunks".
    Raises ChunkLifecycleAnomalyError if active and inactive chunks coexist.
    """
    counts = get_chunk_activation_counts(conn, document_id)

    if counts["active"] > 0 and counts["inactive"] > 0:
        raise ChunkLifecycleAnomalyError(
            f"document_id={document_id} has {counts['active']} active AND {counts['inactive']} "
            "inactive chunks simultaneously -- refusing to silently cut over"
        )
    if counts["active"] > 0 and counts["inactive"] == 0:
        return "already_active"
    if counts["active"] == 0 and counts["inactive"] == 0:
        return "no_chunks"

    document = get_document_by_id(conn, document_id)
    old_document_id = document["supersedes_document_id"] if document else None
    try:
        activate_new_and_deactivate_old_chunks(conn, new_document_id=document_id, old_document_id=old_document_id)
        conn.commit()
        return "activated"
    except Exception:
        conn.rollback()
        raise


def ingest_pdf_document(
    conn,
    pdf_path: str,
    file_name: str,
    embedding_provider: EmbeddingProvider,
    ocr_reader_provider: EasyOcrReaderProvider | None = None,
    strategy_name: str = DEFAULT_STRATEGY_NAME,
    embed_batch_size: int = EMBED_BATCH_SIZE,
) -> IngestionResult:
    """Ingest one PDF end to end. Pure service function -- no FastAPI, no
    frontend; conn is an already-open DB connection the caller owns.

    The documents row is created (or reused, if retrying a previously
    "processing"/"failed" attempt for this exact content hash) BEFORE
    parsing -- total_pages is not known yet at that point, so it is left
    NULL and backfilled via update_document_total_pages once parsing
    succeeds. This lets a caller (e.g. a FastAPI background task) always
    have a document_id and a status to poll, and guarantees that ANY
    failure past this point -- including a parse/OCR/chunk error, not just
    an embedding failure -- has a document row to mark 'failed' rather than
    leaving nothing behind or getting stuck in 'processing' forever.
    """
    document_content_hash = compute_document_content_hash(pdf_path)

    existing = get_document_by_content_hash(conn, document_content_hash)
    if existing is not None and existing["status"] == READY_STATUS:
        # Exact same file already fully ingested: do not re-parse/chunk/
        # embed, do not create a second documents row. A "failed" (or
        # still-"processing") existing row must NOT hit this branch -- that
        # document never finished, so it needs to be retried below, not
        # reported as already done.
        return IngestionResult(document_id=existing["id"], status="already_ingested", cutover_action=None)

    if existing is not None:
        # Retrying a previously-failed (or interrupted-mid-"processing")
        # attempt for this exact content hash: reuse the same document_id
        # rather than creating a second row. Any chunks already committed
        # inactive by the earlier attempt keep their chunk_id (deterministic
        # from document_content_hash + embedding_content_hash), so
        # insert_inactive_chunk's ON CONFLICT DO NOTHING will recognize them
        # as already-present -- no PK collision, no re-embedding of chunks
        # that already succeeded.
        document_id = existing["id"]
        update_document_status(conn, document_id, PROCESSING_STATUS)
        conn.commit()
    else:
        supersedes_document_id = find_supersede_candidate(conn, file_name)
        document_id = create_processing_document(
            conn,
            file_name,
            document_content_hash,
            total_pages=None,
            supersedes_document_id=supersedes_document_id,
            title=file_name,
            file_type=Path(pdf_path).suffix.lstrip(".").lower() or None,
            source_type="upload",
        )
        conn.commit()  # document row visible/retryable even if everything below fails

    try:
        pages = parse_pdf_pages(pdf_path)

        reader: OcrReader | None = None
        provider = ocr_reader_provider or EasyOcrReaderProvider()
        for i, page in enumerate(pages):
            if page.page_status == PAGE_STATUS_SCANNED:
                if reader is None:
                    reader = provider.get_reader()
                pages[i] = ocr_page(pdf_path, page, reader)

        strategy = next(s for s in STRATEGIES if s["name"] == strategy_name)
        chunks = chunk_document(pages, file_name, strategy)

        update_document_total_pages(conn, document_id, len(pages))
        conn.commit()

        stats = _upsert_chunks(conn, document_id, document_content_hash, pages, chunks, embedding_provider, embed_batch_size)
    except Exception:
        update_document_status(conn, document_id, FAILED_STATUS)
        conn.commit()
        raise

    if stats.failed_chunk_ids:
        update_document_status(conn, document_id, FAILED_STATUS)
        conn.commit()
        return IngestionResult(document_id=document_id, status="failed", cutover_action=None, stats=stats)

    try:
        cutover_action = _execute_cutover_if_needed(conn, document_id)
    except Exception:
        update_document_status(conn, document_id, FAILED_STATUS)
        conn.commit()
        raise

    update_document_status(conn, document_id, READY_STATUS)
    conn.commit()
    return IngestionResult(document_id=document_id, status=READY_STATUS, cutover_action=cutover_action, stats=stats)
