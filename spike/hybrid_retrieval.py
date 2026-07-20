"""Step 6 Sub-step 5: hybrid retrieval scoring.

Combines the existing pure-vector similarity ranking (Sub-step 4's
brute-force `embedding <=> query_vector` order) with two additional,
independently-explainable signals:

  - exact_date_match: does any DateCandidate parsed from the query
    (query_parser.extract_date_candidates) appear -- via a whitespace-
    tolerant regex, see DateCandidate.match_regex -- in this candidate
    chunk's text?
  - table_query_match: does the query look like a table question
    (query_parser.looks_like_table_question), AND is this specific
    candidate's chunk_type == "table"?

Weights are centralized in WEIGHTS below (never scattered as inline
magic numbers) and every ScoredChunk carries the raw components
(vector_distance, semantic_score, exact_date_match, table_query_match)
alongside final_score, so a report can show exactly why a chunk ranked
where it did.

Fallback behavior: when neither signal fires for any candidate (e.g. a
query with no date and no table reference), final_score reduces to
WEIGHTS["semantic"] * (1 - vector_distance) for every row -- a monotonic
transform of vector_distance alone -- so the resulting order is IDENTICAL
to the vector-only baseline. There is no query-classifier branch that
can cause retrieval to return nothing or diverge without a signal firing.

Candidate pool: re-scoring happens over the top CANDIDATE_POOL_SIZE
vector-distance results (not just the final top_k), so that a chunk
which is a strong exact-date match but not literally the #1-5 result by
raw distance still has a chance to be pulled into the final top_k by the
exact-match bonus.

Retrieval scope (Sub-step 7): fetch_candidates' filename_filter is
optional. Passing a filename runs the existing document-scoped query
(WHERE d.filename = :filename); passing None runs an unscoped, cross-
document query over every active chunk. This is a query-layer addition
only -- score_candidates' formula and WEIGHTS are unchanged -- added so
spike/run_retrieval_benchmark.py can report document_correctness
meaningfully (with a document-scoped query, document_correctness is
true by construction and does not test anything).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text as sql_text

from spike.query_parser import DateCandidate, extract_date_candidates, looks_like_table_question

CANDIDATE_POOL_SIZE = 30

WEIGHTS = {
    "semantic": 1.0,  # multiplier on (1 - vector_distance)
    "exact_date_match": 0.5,  # flat bonus if a parsed query date appears in the chunk text
    "table_query_match": 0.2,  # flat bonus if query looks table-like AND chunk_type == "table"
}


@dataclass
class ScoredChunk:
    chunk_id: str
    chunk_type: str
    text: str
    filename: str
    pdf_page_number_start: int
    pdf_page_number_end: int
    printed_page_number_map: dict
    section_title: str | None
    table_title: str | None
    vector_distance: float
    semantic_score: float
    exact_date_match: bool
    table_query_match: bool
    final_score: float


def fetch_candidates(conn, query_vector, filename_filter: str | None = None, pool_size: int = CANDIDATE_POOL_SIZE):
    """Fetch the top `pool_size` chunks by pure vector distance (the Sub-step 4 baseline order).

    filename_filter=None runs an unscoped (cross-document) query over every
    active chunk; a filename runs the original document-scoped query.
    """
    where_clause = "c.is_active = true"
    params = {"qv": str(query_vector), "k": pool_size}
    if filename_filter is not None:
        where_clause += " AND d.filename = :filename"
        params["filename"] = filename_filter

    rows = conn.execute(
        sql_text(
            f"""
            SELECT c.chunk_id, c.chunk_type, c.text, d.filename, c.pdf_page_number_start,
                   c.pdf_page_number_end, c.printed_page_number_map, c.section_title,
                   c.table_title, (c.embedding <=> CAST(:qv AS vector)) AS distance
            FROM spike_document_chunks c
            JOIN spike_documents d ON d.id = c.document_id
            WHERE {where_clause}
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
        exact_date_match = any(dc.match_regex().search(r["text"]) for dc in date_candidates)
        table_query_match = table_query and r["chunk_type"] == "table"

        final_score = WEIGHTS["semantic"] * semantic_score
        if exact_date_match:
            final_score += WEIGHTS["exact_date_match"]
        if table_query_match:
            final_score += WEIGHTS["table_query_match"]

        scored.append(
            ScoredChunk(
                chunk_id=r["chunk_id"],
                chunk_type=r["chunk_type"],
                text=r["text"],
                filename=r["filename"],
                pdf_page_number_start=r["pdf_page_number_start"],
                pdf_page_number_end=r["pdf_page_number_end"],
                printed_page_number_map=r["printed_page_number_map"],
                section_title=r["section_title"],
                table_title=r["table_title"],
                vector_distance=distance,
                semantic_score=semantic_score,
                exact_date_match=exact_date_match,
                table_query_match=table_query_match,
                final_score=final_score,
            )
        )
    scored.sort(key=lambda s: s.final_score, reverse=True)
    return scored


def run_hybrid_query(
    conn, provider, query_text: str, filename_filter: str | None, top_k: int = 5, pool_size: int = CANDIDATE_POOL_SIZE
) -> list[ScoredChunk]:
    """Convenience wrapper: embed the query, fetch the candidate pool, and rescore. Uses 1 embedding API call."""
    embed_result = provider.embed_batch([query_text])
    query_vector = embed_result.results[0].vector

    date_candidates = extract_date_candidates(query_text)
    table_query = looks_like_table_question(query_text)

    rows = fetch_candidates(conn, query_vector, filename_filter, pool_size)
    scored = score_candidates(rows, date_candidates, table_query)
    return scored[:top_k]
