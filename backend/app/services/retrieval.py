"""Step 10 Sub-step 5: production internal retrieval service.

Ported from spike/hybrid_retrieval.py (Step 6 Sub-step 5/7), with the
production schema's table/column names (documents/document_chunks,
file_name/content, not spike_documents/spike_document_chunks/filename/text)
and three additions the spike never needed:
  - c.embedding IS NOT NULL: the spike corpus was always fully embedded
    before any retrieval query ran. Production's blue-green chunk lifecycle
    means a chunk row can in principle exist without its embedding written
    yet (mid-ingestion); such a row must never be scored as a candidate.
  - document_id / chunk_type filters, alongside the existing file_name
    filter, for the Step 12 tool-calling use cases this service is meant to
    be reused from.
  - ScoredChunk carries document_id and file_name (production chunks belong
    to a specific document row, not just a bare filename) and a numeric
    metadata_boost field (the sum of whichever weighted bonuses actually
    applied) alongside the existing exact_date_match/table_query_match
    booleans, so a caller doesn't have to re-derive "how much did metadata
    change the score" from the individual flags.

This is an internal service function only -- no HTTP endpoint in this
sub-step. It is meant to be called directly (e.g. by a future Step 12
tool-calling layer), not through app/main.py.

Scoring formula and WEIGHTS are UNCHANGED from the spike (not re-tuned):
final_score = WEIGHTS["semantic"] * (1 - vector_distance)
              + WEIGHTS["exact_date_match"] if exact_date_match else 0
              + WEIGHTS["table_query_match"] if table_query_match else 0

Fallback behavior: when neither signal fires for any candidate, final_score
reduces to a monotonic transform of vector_distance alone, so the resulting
order is IDENTICAL to the vector-only baseline -- there is no query-
classifier branch that can cause retrieval to return nothing or diverge
without a signal firing.

Candidate pool: re-scoring happens over the top CANDIDATE_POOL_SIZE
vector-distance results (not just the final top_k), so a chunk that is a
strong exact-date match but not literally the #1-5 result by raw distance
still has a chance to be pulled into the final top_k by the exact-match
bonus.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text as sql_text

from app.services.embedding_provider import EmbeddingProvider
from app.services.query_parser import DateCandidate, extract_date_candidates, looks_like_table_question

CANDIDATE_POOL_SIZE = 30

WEIGHTS = {
    "semantic": 1.0,  # multiplier on (1 - vector_distance)
    "exact_date_match": 0.5,  # flat bonus if a parsed query date appears in the chunk content
    "table_query_match": 0.2,  # flat bonus if query looks table-like AND chunk_type == "table"
}


@dataclass
class ScoredChunk:
    chunk_id: str
    document_id: int
    file_name: str
    chunk_type: str
    content: str
    page_index_start: int
    page_index_end: int
    pdf_page_number_start: int
    pdf_page_number_end: int
    printed_page_number_map: dict
    section_title: str | None
    table_title: str | None
    vector_distance: float
    semantic_score: float
    exact_date_match: bool
    table_query_match: bool
    metadata_boost: float
    final_score: float


def fetch_candidates(
    conn,
    query_vector,
    document_id: int | None = None,
    file_name: str | None = None,
    chunk_type: str | None = None,
    pool_size: int = CANDIDATE_POOL_SIZE,
):
    """Fetch the top `pool_size` active chunks by pure vector distance.

    Only active chunks with a written embedding participate -- inactive
    (superseded) generations and not-yet-embedded rows are never candidates.
    All filters are optional and parameterized; the WHERE clause is built
    from fixed literal fragments only, never by interpolating a caller-
    supplied value into the SQL text itself.
    """
    where_clauses = ["c.is_active = true", "c.embedding IS NOT NULL"]
    params: dict = {"qv": str(query_vector), "k": pool_size}

    if document_id is not None:
        where_clauses.append("c.document_id = :document_id")
        params["document_id"] = document_id
    if file_name is not None:
        where_clauses.append("d.file_name = :file_name")
        params["file_name"] = file_name
    if chunk_type is not None:
        where_clauses.append("c.chunk_type = :chunk_type")
        params["chunk_type"] = chunk_type

    where_sql = " AND ".join(where_clauses)

    rows = conn.execute(
        sql_text(
            f"""
            SELECT c.chunk_id, c.document_id, c.chunk_type, c.content, d.file_name,
                   c.page_index_start, c.page_index_end,
                   c.pdf_page_number_start, c.pdf_page_number_end,
                   c.printed_page_number_map, c.section_title, c.table_title,
                   (c.embedding <=> CAST(:qv AS vector)) AS distance
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE {where_sql}
            ORDER BY distance
            LIMIT :k
            """
        ),
        params,
    ).mappings().all()
    return rows


def score_candidates(rows, date_candidates: list[DateCandidate], table_query: bool) -> list[ScoredChunk]:
    scored = []
    for r in rows:
        distance = float(r["distance"])
        semantic_score = 1.0 - distance
        exact_date_match = any(dc.match_regex().search(r["content"]) for dc in date_candidates)
        table_query_match = table_query and r["chunk_type"] == "table"

        metadata_boost = 0.0
        if exact_date_match:
            metadata_boost += WEIGHTS["exact_date_match"]
        if table_query_match:
            metadata_boost += WEIGHTS["table_query_match"]

        final_score = WEIGHTS["semantic"] * semantic_score + metadata_boost

        scored.append(
            ScoredChunk(
                chunk_id=r["chunk_id"],
                document_id=r["document_id"],
                file_name=r["file_name"],
                chunk_type=r["chunk_type"],
                content=r["content"],
                page_index_start=r["page_index_start"],
                page_index_end=r["page_index_end"],
                pdf_page_number_start=r["pdf_page_number_start"],
                pdf_page_number_end=r["pdf_page_number_end"],
                printed_page_number_map=r["printed_page_number_map"],
                section_title=r["section_title"],
                table_title=r["table_title"],
                vector_distance=distance,
                semantic_score=semantic_score,
                exact_date_match=exact_date_match,
                table_query_match=table_query_match,
                metadata_boost=metadata_boost,
                final_score=final_score,
            )
        )
    # Stable, fully-deterministic ordering: ties on final_score break on
    # ascending vector_distance, then on chunk_id, so the result order never
    # depends on incidental input/dict-iteration order.
    scored.sort(key=lambda s: (-s.final_score, s.vector_distance, s.chunk_id))
    return scored


def retrieve_chunks(
    conn,
    query_text: str,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    query_embedding: list[float] | None = None,
    top_k: int = 5,
    document_id: int | None = None,
    file_name: str | None = None,
    chunk_type: str | None = None,
    pool_size: int = CANDIDATE_POOL_SIZE,
) -> list[ScoredChunk]:
    """Production internal retrieval entrypoint. Exactly one of
    embedding_provider or query_embedding must be given: pass a provider to
    have this function embed query_text itself (1 embedding API call), or
    pass an already-computed query_embedding if the caller already has one
    (e.g. a future Step 12 tool-calling layer that embeds once and reuses it
    across several retrieval calls).
    """
    if (embedding_provider is None) == (query_embedding is None):
        raise ValueError("retrieve_chunks requires exactly one of embedding_provider or query_embedding")

    if query_embedding is None:
        embed_result = embedding_provider.embed_batch([query_text])
        query_embedding = embed_result.results[0].vector

    date_candidates = extract_date_candidates(query_text)
    table_query = looks_like_table_question(query_text)

    rows = fetch_candidates(
        conn, query_embedding, document_id=document_id, file_name=file_name, chunk_type=chunk_type, pool_size=pool_size
    )
    scored = score_candidates(rows, date_candidates, table_query)
    return scored[:top_k]
