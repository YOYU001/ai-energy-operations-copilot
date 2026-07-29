"""Step 11 Sub-step 3: case similarity retrieval orchestration.

Wires case_records_queries.py (DB reads) and services/case_similarity.py
(pure scoring, untouched by this module) into the two supported search
paths:
  - case-to-case (find_similar_to_case): reuses an existing case's stored
    embedding, NEVER calls an embedding provider.
  - free-text (search_by_text): embeds the query text exactly once via an
    injected EmbeddingProvider (no second OpenAI client built here -- the
    caller in main.py passes the same provider factory used elsewhere).

pool_size is a scoring-internal implementation detail, not part of the
public API contract -- fixed here (POOL_SIZE) and never exposed to callers,
matching the Sub-step 3 API contract decision.
"""

from __future__ import annotations

from app.case_records_queries import fetch_candidate_cases, get_case_by_case_id, list_cases
from app.services.case_similarity import ScoredCase, score_candidates
from app.services.embedding_provider import EmbeddingProvider

POOL_SIZE = 30

DEFAULT_TOP_K = 5
MIN_TOP_K = 1
MAX_TOP_K = 20


class CaseNotFound(Exception):
    """Raised when a case_id does not exist in case_records. main.py
    translates this into a 404."""


class CaseHasNoEmbedding(Exception):
    """Raised when a case exists but has never been embedded -- case-to-case
    similarity has nothing to compute against, and this path deliberately
    never calls an embedding provider to produce one on the fly (that would
    silently turn a "not ready yet" case into an unexpected API-cost side
    effect). main.py translates this into a 422."""


def list_case_summaries(conn, limit: int, offset: int) -> tuple[int, list[dict]]:
    return list_cases(conn, limit, offset)


def get_case_detail(conn, case_id: str) -> dict | None:
    return get_case_by_case_id(conn, case_id)


def find_similar_to_case(conn, case_id: str, top_k: int) -> list[ScoredCase]:
    case = get_case_by_case_id(conn, case_id)
    if case is None:
        raise CaseNotFound(case_id)
    if case.get("embedding") is None:
        raise CaseHasNoEmbedding(case_id)

    candidates = fetch_candidate_cases(conn, case["embedding"], pool_size=POOL_SIZE)
    candidates = [c for c in candidates if c["case_id"] != case_id]
    scored = score_candidates(candidates, query_event_type=case.get("event_type"), query_tags=case.get("tags"))
    return scored[:top_k]


def search_by_text(
    conn,
    embedding_provider: EmbeddingProvider,
    query: str,
    event_type: str | None,
    tags: str | None,
    top_k: int,
) -> list[ScoredCase]:
    embed_result = embedding_provider.embed_batch([query])
    query_vector = embed_result.results[0].vector

    candidates = fetch_candidate_cases(conn, query_vector, pool_size=POOL_SIZE)
    scored = score_candidates(candidates, query_event_type=event_type, query_tags=tags)
    return scored[:top_k]
