"""Step 10 Sub-step 3: documents / document_chunks query layer.

Function-based, dependency-injected style (conn passed in, no commit/rollback
inside these functions -- the caller, app/services/ingestion_rag.py, owns
transaction boundaries), matching the existing convention in
datasets_queries.py rather than spike/vector_store.py's self-committing
functions.

Idempotency/lifecycle contract these functions support (see
app/services/ingestion_rag.py for how they're composed):
  - documents are identified by document_content_hash; a hash collision means
    "this exact file was already ingested", not a new document.
  - document_chunks.chunk_id is a deterministic hash (see
    app.services.hashing.compute_chunk_id) -- re-ingesting unchanged content
    reproduces the same chunk_id, so get_existing_chunk_hashes lets the
    caller skip re-embedding unchanged chunks and only UPDATE metadata for
    chunks whose non-text metadata changed.
  - new chunks are always inserted with is_active=false; only
    activate_new_and_deactivate_old_chunks flips that, atomically, for both
    the new and superseded document at once.
"""

from __future__ import annotations

import json

from sqlalchemy import text


def get_document_by_content_hash(conn, document_content_hash: str):
    """Return the documents row with this content hash, or None."""
    row = conn.execute(
        text("SELECT * FROM documents WHERE document_content_hash = :hash"),
        {"hash": document_content_hash},
    ).mappings().first()
    return dict(row) if row else None


def get_document_by_id(conn, document_id: int):
    """Return a single documents row as a dict, or None if it doesn't exist."""
    row = conn.execute(
        text("SELECT * FROM documents WHERE id = :id"),
        {"id": document_id},
    ).mappings().first()
    return dict(row) if row else None


def find_supersede_candidate(conn, file_name: str):
    """Return the id of the currently-active document with this file_name, or None.

    "Logical document identity" is file_name only (a known, accepted MVP
    limitation, not solved here): a renamed file is treated as an unrelated
    new document, and two different files sharing a file_name would be
    treated as versions of each other.
    """
    row = conn.execute(
        text(
            """
            SELECT DISTINCT d.id
            FROM documents d
            JOIN document_chunks c ON c.document_id = d.id
            WHERE d.file_name = :file_name AND c.is_active = true
            """
        ),
        {"file_name": file_name},
    ).mappings().first()
    return row["id"] if row else None


def create_processing_document(
    conn,
    file_name: str,
    document_content_hash: str,
    total_pages: int | None,
    supersedes_document_id: int | None,
    title: str | None = None,
    file_type: str | None = None,
    source_type: str | None = None,
):
    """Insert a new documents row with status='processing'. Returns its id.

    total_pages is often not known yet at creation time (the async upload
    flow creates this row before parsing) -- pass None and backfill later
    via update_document_total_pages.
    """
    result = conn.execute(
        text(
            """
            INSERT INTO documents (
                file_name, document_content_hash, total_pages, supersedes_document_id,
                status, uploaded_at, title, file_type, source_type
            )
            VALUES (
                :file_name, :hash, :total_pages, :supersedes,
                'processing', now(), :title, :file_type, :source_type
            )
            RETURNING id
            """
        ),
        {
            "file_name": file_name,
            "hash": document_content_hash,
            "total_pages": total_pages,
            "supersedes": supersedes_document_id,
            "title": title,
            "file_type": file_type,
            "source_type": source_type,
        },
    )
    return result.scalar_one()


def list_documents(conn) -> list[dict]:
    """Return every row in documents, newest first (mirrors list_datasets)."""
    rows = conn.execute(
        text(
            """
            SELECT id, title, file_name, file_type, source_type, uploaded_at,
                   status, total_pages, supersedes_document_id
            FROM documents
            ORDER BY uploaded_at DESC, id DESC
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def list_active_chunks_for_document(conn, document_id: int) -> list[dict]:
    """Return active chunks for a document, excluding the embedding vector
    column itself (this is a read-only debug/inspection listing, not a
    retrieval path -- there is no reason to pull 1536 floats per chunk over
    the wire just to have Pydantic discard them)."""
    rows = conn.execute(
        text(
            """
            SELECT chunk_id, strategy_name, chunk_type, content,
                   page_index_start, page_index_end,
                   pdf_page_number_start, pdf_page_number_end,
                   section_title, table_title,
                   embedding_provider, embedding_model, embedding_dimensions,
                   embedding_model_version, embedded_at, is_active
            FROM document_chunks
            WHERE document_id = :document_id AND is_active = true
            ORDER BY page_index_start ASC, chunk_id ASC
            """
        ),
        {"document_id": document_id},
    ).mappings().all()
    return [dict(row) for row in rows]


def update_document_status(conn, document_id: int, status: str) -> None:
    conn.execute(
        text("UPDATE documents SET status = :status WHERE id = :id"),
        {"status": status, "id": document_id},
    )


def update_document_total_pages(conn, document_id: int, total_pages: int) -> None:
    conn.execute(
        text("UPDATE documents SET total_pages = :total_pages WHERE id = :id"),
        {"total_pages": total_pages, "id": document_id},
    )


def get_existing_chunk_hashes(conn, chunk_ids: list[str]) -> dict[str, str]:
    """Return {chunk_id: chunk_metadata_hash} for whichever of chunk_ids already exist.

    Used to decide, per candidate chunk, whether it's unchanged (skip),
    metadata-changed-only (UPDATE, no re-embed), or new (must be embedded).
    """
    if not chunk_ids:
        return {}
    rows = conn.execute(
        text("SELECT chunk_id, chunk_metadata_hash FROM document_chunks WHERE chunk_id = ANY(:ids)"),
        {"ids": chunk_ids},
    ).mappings().all()
    return {r["chunk_id"]: r["chunk_metadata_hash"] for r in rows}


def insert_inactive_chunk(
    conn,
    *,
    chunk_id: str,
    document_id: int,
    strategy_name: str,
    chunk_type: str,
    content: str,
    embedding_content_hash: str,
    chunk_metadata_hash: str,
    page_index_start: int,
    page_index_end: int,
    pdf_page_number_start: int,
    pdf_page_number_end: int,
    printed_page_number_map: dict,
    section_title: str | None,
    table_title: str | None,
    embedding: list[float],
    embedding_provider: str,
    embedding_model: str,
    embedding_dimensions: int,
    embedding_model_version: str | None,
) -> bool:
    """Insert one new chunk with is_active=false. Returns True if a row was
    actually inserted, False if chunk_id already existed (ON CONFLICT DO
    NOTHING) -- e.g. a concurrent/retried ingestion run got there first.
    """
    result = conn.execute(
        text(
            """
            INSERT INTO document_chunks (
                chunk_id, document_id, strategy_name, chunk_type, content,
                embedding_content_hash, chunk_metadata_hash,
                page_index_start, page_index_end,
                pdf_page_number_start, pdf_page_number_end,
                printed_page_number_map, section_title, table_title,
                embedding, embedding_provider, embedding_model,
                embedding_dimensions, embedding_model_version, embedded_at,
                is_active
            ) VALUES (
                :chunk_id, :document_id, :strategy_name, :chunk_type, :content,
                :embedding_content_hash, :chunk_metadata_hash,
                :page_index_start, :page_index_end,
                :pdf_page_number_start, :pdf_page_number_end,
                CAST(:printed_page_number_map AS JSONB), :section_title, :table_title,
                CAST(:embedding AS vector), :embedding_provider, :embedding_model,
                :embedding_dimensions, :embedding_model_version, now(),
                false
            )
            ON CONFLICT (chunk_id) DO NOTHING
            RETURNING chunk_id
            """
        ),
        {
            "chunk_id": chunk_id,
            "document_id": document_id,
            "strategy_name": strategy_name,
            "chunk_type": chunk_type,
            "content": content,
            "embedding_content_hash": embedding_content_hash,
            "chunk_metadata_hash": chunk_metadata_hash,
            "page_index_start": page_index_start,
            "page_index_end": page_index_end,
            "pdf_page_number_start": pdf_page_number_start,
            "pdf_page_number_end": pdf_page_number_end,
            "printed_page_number_map": json.dumps(printed_page_number_map, ensure_ascii=False),
            "section_title": section_title,
            "table_title": table_title,
            "embedding": str(embedding),
            "embedding_provider": embedding_provider,
            "embedding_model": embedding_model,
            "embedding_dimensions": embedding_dimensions,
            "embedding_model_version": embedding_model_version,
        },
    )
    return result.mappings().first() is not None


def update_chunk_metadata(
    conn,
    *,
    chunk_id: str,
    chunk_metadata_hash: str,
    section_title: str | None,
    table_title: str | None,
    printed_page_number_map: dict,
) -> None:
    """Update a chunk's metadata columns only -- never touches text/embedding/
    is_active, since a metadata-only change never changes chunk_id."""
    conn.execute(
        text(
            """
            UPDATE document_chunks
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
            "section_title": section_title,
            "table_title": table_title,
            "printed_page_number_map": json.dumps(printed_page_number_map, ensure_ascii=False),
        },
    )


def get_active_chunks(conn, document_id: int, strategy_name: str | None = None) -> list[dict]:
    """Return active chunks for a document, optionally filtered by strategy_name."""
    if strategy_name is not None:
        rows = conn.execute(
            text(
                "SELECT * FROM document_chunks WHERE document_id = :document_id "
                "AND strategy_name = :strategy_name AND is_active = true"
            ),
            {"document_id": document_id, "strategy_name": strategy_name},
        ).mappings().all()
    else:
        rows = conn.execute(
            text("SELECT * FROM document_chunks WHERE document_id = :document_id AND is_active = true"),
            {"document_id": document_id},
        ).mappings().all()
    return [dict(row) for row in rows]


def get_chunk_activation_counts(conn, document_id: int) -> dict:
    row = conn.execute(
        text(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE is_active) AS active,
                COUNT(*) FILTER (WHERE NOT is_active) AS inactive
            FROM document_chunks
            WHERE document_id = :document_id
            """
        ),
        {"document_id": document_id},
    ).mappings().first()
    return {"total": row["total"], "active": row["active"], "inactive": row["inactive"]}


def activate_new_and_deactivate_old_chunks(conn, new_document_id: int, old_document_id: int | None) -> int:
    """Activate every currently-inactive chunk of new_document_id, and (if
    old_document_id is given) deactivate every currently-active chunk of
    old_document_id. Caller must run this inside a transaction it controls
    and commit/rollback itself -- this function only executes statements.

    Returns the number of chunks activated. Raises RuntimeError (without
    executing the deactivate half) if there was nothing to activate --
    calling this for a new_document_id with no inactive chunks would
    otherwise deactivate the old version for a new version that wrote nothing.
    """
    result = conn.execute(
        text(
            "UPDATE document_chunks SET is_active = true, updated_at = now() "
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
            text(
                "UPDATE document_chunks SET is_active = false, updated_at = now() "
                "WHERE document_id = :old_id AND is_active = true"
            ),
            {"old_id": old_document_id},
        )
    return activated
