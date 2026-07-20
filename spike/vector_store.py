"""Step 6 Sub-step 4: pgvector read/write logic for the spike schema.

Idempotency contract (see spike/hashing.py for why this works):
  - chunk_id is derived from document_content_hash + strategy_name +
    chunk_type + page range + embedding_content_hash. Re-running ingestion
    on unchanged input reproduces the exact same chunk_ids.
  - A chunk_id already present in the table with a matching
    chunk_metadata_hash is left untouched (0 embedding calls, 0 writes).
  - A chunk_id already present but with a different chunk_metadata_hash
    (e.g. an improved section_title heuristic, same text) gets its metadata
    columns UPDATEd -- no re-embedding, since the text (and therefore
    embedding_content_hash, and therefore chunk_id) did not change.
  - A chunk_id not present is new (either truly new content, or the same
    logical chunk with different text -- either way its embedding_content_hash
    changed, so by construction it is a new chunk_id) and must be embedded.
  - Old rows are never deleted when superseded.

Chunk lifecycle contract (Sub-step 6, blue-green cutover -- see
execute_cutover_if_needed/cutover_document_version below):
  - New chunks are always written with is_active=false (upsert_chunks'
    initial_is_active parameter defaults to False). A half-finished
    ingestion can never expose partial new content to retrieval, because
    "written" and "searchable" are two separate states.
  - Only after an ingestion run reports zero failed_chunk_ids does the
    caller invoke execute_cutover_if_needed, which re-checks the CURRENT
    is_active state of the document's chunks in the database (not a
    "was this document just created" flag) and, if the new chunks are
    still all inactive, atomically activates them and deactivates the
    document they supersede in a single transaction (cutover_document_version).
  - If a document_id somehow has both active and inactive chunks at once,
    that violates the one-active-version invariant and
    ChunkLifecycleAnomalyError is raised instead of silently resolving it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text as sql_text

from spike.chunker import Chunk
from spike.embedding_provider import EmbeddingBatchError, EmbeddingProvider
from spike.hashing import compute_chunk_id, compute_chunk_metadata_hash, compute_embedding_content_hash
from spike.pdf_parser import PageParseResult

SCHEMA_PATH = Path(__file__).resolve().parent / "schema_spike.sql"
EMBED_BATCH_SIZE = 96


class ChunkLifecycleAnomalyError(RuntimeError):
    """A document_id has both active and inactive chunks simultaneously.

    This violates the one-active-version invariant that the rest of the
    lifecycle logic depends on. It must stop ingestion for manual
    investigation rather than being silently resolved either way (blindly
    activating everything could expose incomplete content; blindly
    deactivating everything could remove valid searchable content).
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


def ensure_schema(conn) -> None:
    ddl = SCHEMA_PATH.read_text(encoding="utf-8")
    for raw_statement in ddl.split(";"):
        # Drop comment-only lines from within this statement block (a
        # naive "does the whole block start with --" check would wrongly
        # skip a real statement preceded by leading comment lines).
        code_lines = [line for line in raw_statement.splitlines() if not line.strip().startswith("--")]
        statement = "\n".join(code_lines).strip()
        if statement:
            conn.execute(sql_text(statement))
    conn.commit()


def get_or_create_document(conn, filename: str, document_content_hash: str, total_pages: int) -> int:
    """Look up (or create) the spike_documents row for this content hash.

    filename is used as the "logical document identity" for the purposes of
    finding what a newly-created row supersedes (see supersedes_document_id
    below). This is a deliberate, documented limitation of this spike: a
    renamed file is treated as an unrelated new document, and two
    different files that happen to share a filename (e.g. from different
    folders) would be treated as versions of the same logical document.
    A real document_key independent of filename is out of scope here.
    """
    row = conn.execute(
        sql_text("SELECT id FROM spike_documents WHERE document_content_hash = :h"),
        {"h": document_content_hash},
    ).mappings().first()
    if row:
        return row["id"]

    prev = conn.execute(
        sql_text(
            """
            SELECT DISTINCT d.id
            FROM spike_documents d
            JOIN spike_document_chunks c ON c.document_id = d.id
            WHERE d.filename = :filename AND c.is_active = true
            """
        ),
        {"filename": filename},
    ).mappings().first()
    supersedes_document_id = prev["id"] if prev else None

    result = conn.execute(
        sql_text(
            "INSERT INTO spike_documents (filename, document_content_hash, total_pages, supersedes_document_id) "
            "VALUES (:filename, :hash, :pages, :supersedes) RETURNING id"
        ),
        {"filename": filename, "hash": document_content_hash, "pages": total_pages, "supersedes": supersedes_document_id},
    )
    document_id = result.scalar_one()
    conn.commit()
    return document_id


def _build_printed_page_map(pages: list[PageParseResult], page_index_start: int, page_index_end: int) -> dict:
    mapping = {}
    for page in pages:
        if page_index_start <= page.page_index <= page_index_end:
            mapping[str(page.pdf_page_number)] = page.printed_page_number
    return mapping


def _chunk_metadata_dict(chunk: Chunk) -> dict:
    return {
        "printed_page_number_list": chunk.printed_page_number_list,
        "section_title": chunk.section_title,
        "table_title": chunk.table_title,
    }


def upsert_chunks(
    conn,
    document_id: int,
    document_content_hash: str,
    pages: list[PageParseResult],
    chunks: list[Chunk],
    provider: EmbeddingProvider,
    embed_batch_size: int = EMBED_BATCH_SIZE,
    initial_is_active: bool = False,
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

    existing: dict[str, dict] = {}
    if prepared:
        ids = [p[1] for p in prepared]
        rows = conn.execute(
            sql_text("SELECT chunk_id, chunk_metadata_hash FROM spike_document_chunks WHERE chunk_id = ANY(:ids)"),
            {"ids": ids},
        ).mappings().all()
        existing = {r["chunk_id"]: r for r in rows}

    to_embed = []
    to_update_metadata_only = []
    for item in prepared:
        chunk, chunk_id, embedding_content_hash, chunk_metadata_hash = item
        if chunk_id not in existing:
            to_embed.append(item)
        elif existing[chunk_id]["chunk_metadata_hash"] != chunk_metadata_hash:
            to_update_metadata_only.append(item)
        else:
            stats.unchanged_skipped += 1

    for i in range(0, len(to_embed), embed_batch_size):
        batch = to_embed[i : i + embed_batch_size]
        texts = [chunk.text for chunk, _, _, _ in batch]
        try:
            batch_result = provider.embed_batch(texts)
        except EmbeddingBatchError as exc:
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
            conn.execute(
                sql_text(
                    """
                    INSERT INTO spike_document_chunks (
                        chunk_id, document_id, strategy_name, chunk_type, text,
                        embedding_content_hash, chunk_metadata_hash,
                        page_index_start, page_index_end,
                        pdf_page_number_start, pdf_page_number_end,
                        printed_page_number_map, section_title, table_title,
                        embedding, embedding_provider, embedding_model,
                        embedding_dimensions, embedding_model_version, embedded_at,
                        is_active
                    ) VALUES (
                        :chunk_id, :document_id, :strategy_name, :chunk_type, :text,
                        :embedding_content_hash, :chunk_metadata_hash,
                        :page_index_start, :page_index_end,
                        :pdf_page_number_start, :pdf_page_number_end,
                        CAST(:printed_page_number_map AS JSONB), :section_title, :table_title,
                        CAST(:embedding AS vector), :embedding_provider, :embedding_model,
                        :embedding_dimensions, :embedding_model_version, now(),
                        :is_active
                    )
                    ON CONFLICT (chunk_id) DO NOTHING
                    """
                ),
                {
                    "chunk_id": chunk_id,
                    "document_id": document_id,
                    "strategy_name": chunk.strategy_name,
                    "chunk_type": chunk.chunk_type,
                    "text": chunk.text,
                    "embedding_content_hash": embedding_content_hash,
                    "chunk_metadata_hash": chunk_metadata_hash,
                    "page_index_start": chunk.page_index_range[0],
                    "page_index_end": chunk.page_index_range[1],
                    "pdf_page_number_start": chunk.pdf_page_number_range[0],
                    "pdf_page_number_end": chunk.pdf_page_number_range[1],
                    "printed_page_number_map": json.dumps(printed_map, ensure_ascii=False),
                    "section_title": chunk.section_title,
                    "table_title": chunk.table_title,
                    "embedding": str(embedded.vector),
                    "embedding_provider": embedded.provider,
                    "embedding_model": embedded.model,
                    "embedding_dimensions": embedded.dimensions,
                    "embedding_model_version": embedded.model_version,
                    "is_active": initial_is_active,
                },
            )
            stats.inserted_new += 1
            stats.embedded_chunk_count += 1
        conn.commit()

    for chunk, chunk_id, _, chunk_metadata_hash in to_update_metadata_only:
        conn.execute(
            sql_text(
                """
                UPDATE spike_document_chunks
                SET chunk_metadata_hash = :chunk_metadata_hash,
                    section_title = :section_title,
                    table_title = :table_title,
                    printed_page_number_map = CAST(:printed_page_number_map AS JSONB),
                    updated_at = now()
                WHERE chunk_id = :chunk_id
                """
            ),
            {
                "chunk_id": chunk_id,
                "chunk_metadata_hash": chunk_metadata_hash,
                "section_title": chunk.section_title,
                "table_title": chunk.table_title,
                "printed_page_number_map": json.dumps(
                    _build_printed_page_map(pages, chunk.page_index_range[0], chunk.page_index_range[1]), ensure_ascii=False
                ),
            },
        )
        stats.updated_metadata_only += 1
    conn.commit()

    return stats


def _chunk_activation_counts(conn, document_id: int) -> dict:
    row = conn.execute(
        sql_text(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE is_active) AS active,
                COUNT(*) FILTER (WHERE NOT is_active) AS inactive
            FROM spike_document_chunks
            WHERE document_id = :document_id
            """
        ),
        {"document_id": document_id},
    ).mappings().first()
    return {"total": row["total"], "active": row["active"], "inactive": row["inactive"]}


def cutover_document_version(conn, new_document_id: int, old_document_id: int | None) -> int:
    """Atomic blue-green cutover in a single transaction: activate every
    currently-inactive chunk belonging to new_document_id, and (if
    old_document_id is given) deactivate every currently-active chunk
    belonging to old_document_id. Either both updates commit, or neither
    does (any exception triggers an explicit rollback before re-raising).

    If old_document_id is None (first-ever ingestion of this logical
    document -- nothing to supersede), only the activate half runs.

    Returns the number of chunks activated. Raises RuntimeError (without
    committing) if there was nothing to activate -- calling this with a
    new_document_id that has no inactive chunks would otherwise silently
    deactivate the old version for a new version that wrote nothing.
    """
    try:
        result = conn.execute(
            sql_text(
                "UPDATE spike_document_chunks SET is_active = true, updated_at = now() "
                "WHERE document_id = :new_id AND is_active = false"
            ),
            {"new_id": new_document_id},
        )
        activated = result.rowcount
        if not activated:
            raise RuntimeError(
                f"cutover aborted: document_id={new_document_id} has 0 inactive chunks to activate -- "
                "refusing to deactivate the superseded version for a new version that wrote nothing"
            )

        if old_document_id is not None:
            conn.execute(
                sql_text(
                    "UPDATE spike_document_chunks SET is_active = false, updated_at = now() "
                    "WHERE document_id = :old_id AND is_active = true"
                ),
                {"old_id": old_document_id},
            )
        conn.commit()
        return activated
    except Exception:
        conn.rollback()
        raise


def execute_cutover_if_needed(conn, document_id: int) -> str:
    """Decide whether document_id needs a blue-green cutover, based on the
    CURRENT is_active state of its chunks in the database right now -- not
    on whether this document_id happened to be created earlier in this
    ingestion run. This makes it safe to call after a retried run that
    picks up a document_id created (but left fully inactive) by a previous,
    partially-failed run.

    Returns one of:
      "already_active" -- this document's chunks are already the live
                           version (a normal idempotent re-run); no-op.
      "activated"       -- chunks were all inactive and have now been
                           cut over via cutover_document_version.
      "no_chunks"       -- this document_id has zero chunks at all (e.g.
                           chunk_document produced nothing); no-op.

    Raises ChunkLifecycleAnomalyError if this document_id has both active
    and inactive chunks at the same time -- that violates the
    one-active-version invariant and must stop for manual investigation
    rather than being silently resolved either direction.
    """
    counts = _chunk_activation_counts(conn, document_id)

    if counts["active"] > 0 and counts["inactive"] > 0:
        raise ChunkLifecycleAnomalyError(
            f"document_id={document_id} has {counts['active']} active AND {counts['inactive']} "
            "inactive chunks simultaneously -- refusing to silently cut over"
        )
    if counts["active"] > 0 and counts["inactive"] == 0:
        return "already_active"
    if counts["active"] == 0 and counts["inactive"] == 0:
        return "no_chunks"

    row = conn.execute(
        sql_text("SELECT supersedes_document_id FROM spike_documents WHERE id = :id"),
        {"id": document_id},
    ).mappings().first()
    old_document_id = row["supersedes_document_id"] if row else None
    cutover_document_version(conn, new_document_id=document_id, old_document_id=old_document_id)
    return "activated"
