"""Step 11 Sub-step 2A/2B: case_records query layer.

Function-based, dependency-injected style (conn passed in, no commit/
rollback inside these functions -- the caller owns transaction boundaries),
matching the existing convention in datasets_queries.py / document_chunks_queries.py.

upsert_case_record uses a real DB-level atomic upsert: `INSERT ... ON
CONFLICT (case_id) DO UPDATE ...`. This is safe under concurrent/
multi-writer callers because case_id is now `TEXT NOT NULL UNIQUE`
(case_records_case_id_key, added in Sub-step 2B) -- Postgres itself
guarantees at most one row per case_id, resolved atomically by the
ON CONFLICT clause rather than by an application-level read-then-write
check. (Sub-step 2A's original implementation was a SELECT-then-branch,
which was NOT concurrency-safe; that approach and its caveats no longer
apply now that the constraint exists.)

No scoring/boost/confidence logic lives here -- see
app/services/case_similarity.py for that. This module only knows how to
read and write rows.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import text


def get_case_by_case_id(conn, case_id: str):
    """Return the case_records row with this case_id, or None."""
    row = conn.execute(
        text("SELECT * FROM case_records WHERE case_id = :case_id"),
        {"case_id": case_id},
    ).mappings().first()
    return dict(row) if row else None


def get_case_by_id(conn, id: int):
    """Return a single case_records row by primary key, or None."""
    row = conn.execute(
        text("SELECT * FROM case_records WHERE id = :id"),
        {"id": id},
    ).mappings().first()
    return dict(row) if row else None


def get_cases_by_case_ids(conn, case_ids: list[str]) -> dict[str, dict]:
    """Batch-fetch existing case_records rows for these case_ids, keyed by
    case_id. Used by scripts/seed_case_records.py to decide, per case,
    whether it already has a matching embedding_content_hash (skip) --
    one query instead of one SELECT per case_id (N+1), matching
    document_chunks_queries.get_existing_chunk_hashes's precedent.
    """
    if not case_ids:
        return {}
    rows = conn.execute(
        text("SELECT * FROM case_records WHERE case_id = ANY(:ids)"),
        {"ids": case_ids},
    ).mappings().all()
    return {row["case_id"]: dict(row) for row in rows}


def list_cases(conn, limit: int, offset: int) -> tuple[int, list[dict]]:
    """Return (total, items) for a page of case_records, newest event first.

    total counts every row regardless of limit/offset, matching
    datasets_queries.get_dataset_timeseries's pagination shape.
    """
    total = conn.execute(text("SELECT COUNT(*) AS total FROM case_records")).mappings().first()["total"]
    rows = conn.execute(
        text(
            """
            SELECT * FROM case_records
            ORDER BY event_time DESC NULLS LAST, id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {"limit": limit, "offset": offset},
    ).mappings().all()
    return total, [dict(row) for row in rows]


def upsert_case_record(
    conn,
    *,
    case_id: str,
    site_id: Optional[str],
    event_time,
    event_type: Optional[str],
    symptoms: Optional[str],
    root_cause: Optional[str],
    operator_action: Optional[str],
    resolution_result: Optional[str],
    severity: Optional[str],
    tags: Optional[str],
    related_dataset_id: Optional[int],
    related_time_range: Optional[str],
    embedding: Optional[list[float]] = None,
    embedding_provider: Optional[str] = None,
    embedding_model: Optional[str] = None,
    embedding_dimensions: Optional[int] = None,
    embedding_model_version: Optional[str] = None,
    embedding_content_hash: Optional[str] = None,
) -> int:
    """Atomically insert a new case_records row, or update the existing row
    with this case_id if one already exists (via `ON CONFLICT (case_id) DO
    UPDATE`, relying on the case_records_case_id_key UNIQUE constraint).
    Returns the row's id either way.

    Structured fields (site_id, event_time, ... related_time_range) always
    take the newly-passed values on conflict. embedding, its provenance
    columns, and embedding_content_hash only update when a non-None
    embedding is passed -- calling this again with embedding=None (e.g. to
    update structured fields only, or because the caller decided this
    case's search text is unchanged and skipped re-embedding) must NOT
    erase an existing embedding, its provenance, its hash, or its
    embedded_at timestamp; EXCLUDED.embedding IS NULL is used to detect
    that case and fall back to the existing row's values instead of
    overwriting them.
    """
    embedding_param = str(embedding) if embedding is not None else None

    params = {
        "case_id": case_id,
        "site_id": site_id,
        "event_time": event_time,
        "event_type": event_type,
        "symptoms": symptoms,
        "root_cause": root_cause,
        "operator_action": operator_action,
        "resolution_result": resolution_result,
        "severity": severity,
        "tags": tags,
        "related_dataset_id": related_dataset_id,
        "related_time_range": related_time_range,
        "embedding": embedding_param,
        "embedding_provider": embedding_provider,
        "embedding_model": embedding_model,
        "embedding_dimensions": embedding_dimensions,
        "embedding_model_version": embedding_model_version,
        "embedding_content_hash": embedding_content_hash,
    }

    result = conn.execute(
        text(
            """
            INSERT INTO case_records (
                case_id, site_id, event_time, event_type, symptoms, root_cause,
                operator_action, resolution_result, severity, tags,
                related_dataset_id, related_time_range,
                embedding, embedding_provider, embedding_model,
                embedding_dimensions, embedding_model_version,
                embedding_content_hash, embedded_at
            ) VALUES (
                :case_id, :site_id, :event_time, :event_type, :symptoms, :root_cause,
                :operator_action, :resolution_result, :severity, :tags,
                :related_dataset_id, :related_time_range,
                CAST(:embedding AS vector), :embedding_provider, :embedding_model,
                :embedding_dimensions, :embedding_model_version,
                :embedding_content_hash,
                CASE WHEN :embedding IS NULL THEN NULL ELSE now() END
            )
            ON CONFLICT (case_id) DO UPDATE SET
                site_id = EXCLUDED.site_id,
                event_time = EXCLUDED.event_time,
                event_type = EXCLUDED.event_type,
                symptoms = EXCLUDED.symptoms,
                root_cause = EXCLUDED.root_cause,
                operator_action = EXCLUDED.operator_action,
                resolution_result = EXCLUDED.resolution_result,
                severity = EXCLUDED.severity,
                tags = EXCLUDED.tags,
                related_dataset_id = EXCLUDED.related_dataset_id,
                related_time_range = EXCLUDED.related_time_range,
                embedding = CASE WHEN EXCLUDED.embedding IS NULL THEN case_records.embedding ELSE EXCLUDED.embedding END,
                embedding_provider = CASE WHEN EXCLUDED.embedding IS NULL THEN case_records.embedding_provider ELSE EXCLUDED.embedding_provider END,
                embedding_model = CASE WHEN EXCLUDED.embedding IS NULL THEN case_records.embedding_model ELSE EXCLUDED.embedding_model END,
                embedding_dimensions = CASE WHEN EXCLUDED.embedding IS NULL THEN case_records.embedding_dimensions ELSE EXCLUDED.embedding_dimensions END,
                embedding_model_version = CASE WHEN EXCLUDED.embedding IS NULL THEN case_records.embedding_model_version ELSE EXCLUDED.embedding_model_version END,
                embedding_content_hash = CASE WHEN EXCLUDED.embedding IS NULL THEN case_records.embedding_content_hash ELSE EXCLUDED.embedding_content_hash END,
                embedded_at = CASE WHEN EXCLUDED.embedding IS NULL THEN case_records.embedded_at ELSE now() END,
                updated_at = now()
            RETURNING id
            """
        ),
        params,
    )
    return result.scalar_one()


def fetch_candidate_cases(conn, query_vector, pool_size: int = 30) -> list[dict]:
    """Fetch the top `pool_size` case_records by pure vector distance.

    Only rows with a written embedding participate -- a seed run that has
    not embedded a case yet (embedding IS NULL) must never surface as a
    similarity candidate. SQL is fully parameterized; no caller-supplied
    value is interpolated into the SQL text itself.
    """
    rows = conn.execute(
        text(
            """
            SELECT id, case_id, site_id, event_time, event_type, symptoms, root_cause,
                   operator_action, resolution_result, severity, tags,
                   related_dataset_id, related_time_range,
                   (embedding <=> CAST(:qv AS vector)) AS distance
            FROM case_records
            WHERE embedding IS NOT NULL
            ORDER BY distance
            LIMIT :k
            """
        ),
        {"qv": str(query_vector), "k": pool_size},
    ).mappings().all()
    return [dict(row) for row in rows]
