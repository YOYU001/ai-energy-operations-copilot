"""Step 11 Sub-step 2A: case similarity scoring, pure logic.

Deterministic, no DB access and no external API calls -- takes candidate
rows (already fetched, already carrying a vector `distance`) and a query's
event_type/tags, and produces a ranked, explainable score. This is what
makes it unit-testable without a real database or embedding provider.

Scoring design (per the Step 11 planning decision):
  - semantic_score (cosine similarity, derived from pgvector distance) is
    the PRIMARY signal.
  - event_type exact match and tags overlap are small, capped boosts only --
    never large enough to let a semantically dissimilar case outrank a
    strongly similar one.
  - root_cause / operator_action / resolution_result are NEVER used to
    compute the query embedding and NEVER contribute to the score -- they
    are display-only fields on the returned ScoredCase, to avoid the
    search silently leaking the answer fields into the ranking itself.
  - final_score is always clamped to [0, 1], regardless of how boosts sum.

WEIGHTS and CONFIDENCE_THRESHOLDS are centralized here -- nothing about
case scoring should be duplicated or hardcoded anywhere else in the
codebase (query layer, API, frontend all import from this module).

PROVISIONAL, NOT CALIBRATED: CONFIDENCE_THRESHOLDS below are MVP defaults
chosen for a reasonable-looking distribution, not derived from any
ground-truth "these two cases are genuinely similar" labeled dataset --
none exists for case_records (unlike Step 10's retrieval benchmark, which
had spike/test_questions.json). Revisit once real usage/query data exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Flat, capped boosts -- deliberately small relative to the semantic score's
# full [0, 1] range, so metadata alone can never make a poor semantic match
# outrank a strong one (see test_event_type_boost_cannot_outrank_higher_semantic_similarity).
WEIGHTS = {
    "event_type_match": 0.05,
    "tags_overlap_max": 0.05,  # ceiling on the Jaccard-overlap-scaled tags boost
}

# PROVISIONAL, uncalibrated -- see module docstring.
CONFIDENCE_THRESHOLDS = {
    "high": 0.85,
    "medium": 0.70,
}

# Separate, PROVISIONAL thresholds for describing overall case similarity in
# matches/differs. Deliberately NOT the same buckets as CONFIDENCE_THRESHOLDS:
# confidence describes final_score (semantic + boosts), this describes
# semantic_score alone.
#
# NOTE: semantic_score comes from the embedding of build_case_search_text(),
# which concatenates event_type + symptoms + tags + severity (see
# scripts/seed_case_records.py). It is a COMPOSITE case-similarity signal,
# NOT a symptoms-only comparison -- two cases sharing event_type/tags can
# score highly here even if their symptom descriptions actually differ. Do
# not rename this back to anything implying "symptom similarity" (PR #37
# Codex review, P2) -- that was the original, misleading name.
CASE_SIMILARITY_THRESHOLDS = {
    "high": 0.80,
    "medium": 0.55,
}


def case_similarity_label(semantic_score: float) -> str:
    """Bucket semantic_score into one of three fixed, centrally-defined
    labels describing overall case similarity (event_type + symptoms + tags
    + severity combined) -- never claims this isolates symptom text
    similarity specifically."""
    if semantic_score >= CASE_SIMILARITY_THRESHOLDS["high"]:
        return "高度語意相似"
    if semantic_score >= CASE_SIMILARITY_THRESHOLDS["medium"]:
        return "中度語意相似"
    return "低度語意相似"

CASE_DISPLAY_FIELDS = (
    "case_id",
    "site_id",
    "event_time",
    "event_type",
    "symptoms",
    "root_cause",
    "operator_action",
    "resolution_result",
    "severity",
    "tags",
    "related_dataset_id",
    "related_time_range",
)


@dataclass
class ScoredCase:
    case_id: str
    site_id: Optional[str]
    event_time: object
    event_type: Optional[str]
    symptoms: Optional[str]
    root_cause: Optional[str]
    operator_action: Optional[str]
    resolution_result: Optional[str]
    severity: Optional[str]
    tags: Optional[str]
    related_dataset_id: Optional[int]
    related_time_range: Optional[str]
    vector_distance: float
    semantic_score: float
    event_type_match: bool
    tags_overlap_ratio: float
    tags_boost: float
    final_score: float
    confidence: str
    matches: list[str] = field(default_factory=list)
    differs: list[str] = field(default_factory=list)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def normalize_tags(tags: Optional[str]) -> set[str]:
    """Comma-separated tags (docs/DATA_SCHEMA.md section 5 convention, e.g.
    "PV,cloudy,SOC,peak_shaving"), trimmed and lowercased. Never raises on
    malformed input (None, empty string, stray/duplicate commas, extra
    whitespace) -- all of those just produce an empty or smaller set, never
    an exception.
    """
    if not tags:
        return set()
    return {t.strip().lower() for t in tags.split(",") if t.strip()}


def tags_overlap_ratio(query_tags: set[str], candidate_tags: set[str]) -> float:
    """Jaccard overlap: |intersection| / |union|. 0.0 if either side is
    empty -- an empty tag set has no meaningful overlap with anything, not
    a perfect or undefined match.
    """
    if not query_tags or not candidate_tags:
        return 0.0
    intersection = query_tags & candidate_tags
    union = query_tags | candidate_tags
    return len(intersection) / len(union)


def confidence_for_score(score: float) -> str:
    if score >= CONFIDENCE_THRESHOLDS["high"]:
        return "high"
    if score >= CONFIDENCE_THRESHOLDS["medium"]:
        return "medium"
    return "low"


def _build_matches_and_differs(
    *,
    query_event_type: Optional[str],
    query_tags_set: set[str],
    query_severity: Optional[str],
    candidate: dict,
    candidate_tags_set: set[str],
    semantic_score: float,
) -> tuple[list[str], list[str]]:
    matches: list[str] = []
    differs: list[str] = []

    if query_event_type is not None:
        if candidate.get("event_type") == query_event_type:
            matches.append(f"event_type: {candidate.get('event_type')}")
        else:
            differs.append(f"event_type: query={query_event_type} vs candidate={candidate.get('event_type')}")

    shared_tags = query_tags_set & candidate_tags_set
    missing_tags = candidate_tags_set - query_tags_set
    if shared_tags:
        matches.append(f"tags: {', '.join(sorted(shared_tags))}")
    if missing_tags:
        differs.append(f"tags: {', '.join(sorted(missing_tags))}")

    # Only ever appears in matches/differs when the query side actually
    # supplies a severity to compare against (case-to-case: the source
    # case's own severity). A candidate merely *having* a severity is not a
    # "match" -- free-text search currently has no query-side severity input
    # at all, so this stays out of matches/differs entirely for that path
    # (PR #37 Codex review, P2 -- previously every candidate with any
    # severity was wrongly shown as a green "match" badge with nothing to
    # compare against). The candidate's own severity is still visible via
    # CaseSearchResult.severity, so no information is lost by omitting it here.
    if query_severity is not None:
        candidate_severity = candidate.get("severity")
        if candidate_severity == query_severity:
            matches.append(f"severity: {candidate_severity}")
        else:
            differs.append(f"severity: query={query_severity} vs candidate={candidate_severity}")

    # case_similarity: a semantic-similarity DESCRIPTION derived from
    # semantic_score, never a claim that the symptoms text specifically is
    # identical or "matches" in the literal sense -- routed to matches/
    # differs by bucket so a low semantic score is visible as a differs
    # entry even if event_type/tags boosts pushed final_score up.
    similarity_label = case_similarity_label(semantic_score)
    similarity_description = f"case_similarity: {similarity_label}（語意相似度 {semantic_score:.2f}，非逐字相符）"
    if semantic_score >= CASE_SIMILARITY_THRESHOLDS["medium"]:
        matches.append(similarity_description)
    else:
        differs.append(similarity_description)

    return matches, differs


def score_case(
    candidate: dict,
    *,
    query_event_type: Optional[str] = None,
    query_tags: Optional[str] = None,
    query_severity: Optional[str] = None,
) -> ScoredCase:
    """candidate must have all of CASE_DISPLAY_FIELDS plus a "distance" key
    (pgvector cosine distance, as returned by
    case_records_queries.fetch_candidate_cases)."""
    distance = float(candidate["distance"])
    semantic_score = clamp(1.0 - distance)

    event_type_match = query_event_type is not None and candidate.get("event_type") == query_event_type
    event_type_boost = WEIGHTS["event_type_match"] if event_type_match else 0.0

    query_tags_set = normalize_tags(query_tags)
    candidate_tags_set = normalize_tags(candidate.get("tags"))
    overlap_ratio = tags_overlap_ratio(query_tags_set, candidate_tags_set)
    tags_boost = WEIGHTS["tags_overlap_max"] * overlap_ratio

    final_score = clamp(semantic_score + event_type_boost + tags_boost)
    confidence = confidence_for_score(final_score)

    matches, differs = _build_matches_and_differs(
        query_event_type=query_event_type,
        query_tags_set=query_tags_set,
        query_severity=query_severity,
        candidate=candidate,
        candidate_tags_set=candidate_tags_set,
        semantic_score=semantic_score,
    )

    return ScoredCase(
        **{field_name: candidate.get(field_name) for field_name in CASE_DISPLAY_FIELDS},
        vector_distance=distance,
        semantic_score=semantic_score,
        event_type_match=event_type_match,
        tags_overlap_ratio=overlap_ratio,
        tags_boost=tags_boost,
        final_score=final_score,
        confidence=confidence,
        matches=matches,
        differs=differs,
    )


def score_candidates(
    candidates: list[dict],
    *,
    query_event_type: Optional[str] = None,
    query_tags: Optional[str] = None,
    query_severity: Optional[str] = None,
) -> list[ScoredCase]:
    scored = [
        score_case(c, query_event_type=query_event_type, query_tags=query_tags, query_severity=query_severity)
        for c in candidates
    ]
    # Stable, fully-deterministic ordering: ties on final_score break on
    # ascending vector_distance, then on case_id, so result order never
    # depends on incidental input/dict-iteration order (same principle as
    # app/services/retrieval.py's score_candidates).
    scored.sort(key=lambda s: (-s.final_score, s.vector_distance, s.case_id))
    return scored
