"""Step 11 Sub-step 3: unit tests for app/services/case_retrieval.py.

Uses the plain FakeConnection (backend/tests/fakes.py) with pre-canned
`responses` -- each test controls exactly which rows each sequential
execute() call returns, mirroring how test_case_records_queries.py already
tests fetch_candidate_cases's SQL shape. This keeps these tests focused on
orchestration (self-exclusion, top_k, provider-call-or-not, error mapping)
without depending on FakeCaseRecordsConnection's cosine-distance emulation
(exercised instead at the route level in test_cases_api.py).

No real DB, no real OpenAI calls anywhere in this file.
"""

import pytest

from app.services.case_retrieval import (
    CaseHasNoEmbedding,
    CaseNotFound,
    find_similar_to_case,
    search_by_text,
)
from tests.fakes import FakeConnection


def _candidate(case_id, distance, event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT", tags="peak_shaving"):
    return {
        "id": 1,
        "case_id": case_id,
        "site_id": "SITE-A",
        "event_time": "2026-01-15T13:30:00",
        "event_type": event_type,
        "symptoms": "symptoms text",
        "root_cause": "root cause text",
        "operator_action": "action text",
        "resolution_result": "result text",
        "severity": "high",
        "tags": tags,
        "related_dataset_id": None,
        "related_time_range": None,
        "distance": distance,
    }


class _FakeEmbeddingResult:
    def __init__(self, vector):
        self.results = [_Embedded(vector)]


class _Embedded:
    def __init__(self, vector):
        self.vector = vector


class _FakeEmbeddingProvider:
    def __init__(self, vector=None):
        self.vector = vector or [0.1, 0.2, 0.3]
        self.calls = []

    def embed_batch(self, texts):
        self.calls.append(list(texts))
        return _FakeEmbeddingResult(self.vector)


class _BoomEmbeddingProvider:
    def embed_batch(self, texts):
        raise RuntimeError("simulated embedding provider failure")


# ---------------------------------------------------------------------------
# find_similar_to_case (case-to-case)
# ---------------------------------------------------------------------------


def test_find_similar_to_case_raises_case_not_found():
    conn = FakeConnection(rows=[])
    with pytest.raises(CaseNotFound):
        find_similar_to_case(conn, "missing-case", top_k=5)


def test_find_similar_to_case_raises_case_has_no_embedding():
    case_row = {"case_id": "case-0001", "event_type": "X", "tags": "a", "embedding": None}
    conn = FakeConnection(responses=[[case_row]])
    with pytest.raises(CaseHasNoEmbedding):
        find_similar_to_case(conn, "case-0001", top_k=5)


def test_find_similar_to_case_never_calls_an_embedding_provider():
    # No provider is passed to find_similar_to_case at all -- its signature
    # takes none -- so a successful call is itself the proof.
    case_row = {"case_id": "case-0001", "event_type": "X", "tags": "a", "embedding": "[0.1, 0.2]"}
    candidates = [_candidate("case-0002", distance=0.1)]
    conn = FakeConnection(responses=[[case_row], candidates])

    result = find_similar_to_case(conn, "case-0001", top_k=5)
    assert [s.case_id for s in result] == ["case-0002"]


def test_find_similar_to_case_excludes_self():
    case_row = {"case_id": "case-0001", "event_type": "X", "tags": "a", "embedding": "[0.1, 0.2]"}
    candidates = [
        _candidate("case-0001", distance=0.0),  # self -- must be excluded
        _candidate("case-0002", distance=0.1),
    ]
    conn = FakeConnection(responses=[[case_row], candidates])

    result = find_similar_to_case(conn, "case-0001", top_k=5)
    assert "case-0001" not in [s.case_id for s in result]
    assert [s.case_id for s in result] == ["case-0002"]


def test_find_similar_to_case_respects_top_k():
    case_row = {"case_id": "case-0001", "event_type": "X", "tags": "a", "embedding": "[0.1, 0.2]"}
    candidates = [_candidate(f"case-{i}", distance=i / 10) for i in range(1, 6)]
    conn = FakeConnection(responses=[[case_row], candidates])

    result = find_similar_to_case(conn, "case-0001", top_k=2)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# search_by_text (free-text)
# ---------------------------------------------------------------------------


def test_search_by_text_calls_embedding_provider_exactly_once():
    provider = _FakeEmbeddingProvider()
    candidates = [_candidate("case-0001", distance=0.1)]
    conn = FakeConnection(rows=candidates)

    search_by_text(conn, provider, "battery discharge issue", event_type=None, tags=None, top_k=5)
    assert len(provider.calls) == 1
    assert provider.calls[0] == ["battery discharge issue"]


def test_search_by_text_respects_top_k():
    provider = _FakeEmbeddingProvider()
    candidates = [_candidate(f"case-{i}", distance=i / 10) for i in range(1, 6)]
    conn = FakeConnection(rows=candidates)

    result = search_by_text(conn, provider, "query", event_type=None, tags=None, top_k=3)
    assert len(result) == 3


def test_search_by_text_applies_event_type_and_tags_to_scoring():
    provider = _FakeEmbeddingProvider()
    candidates = [_candidate("case-0001", distance=0.2, event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT", tags="peak_shaving,SOC")]
    conn = FakeConnection(rows=candidates)

    result = search_by_text(
        conn,
        provider,
        "query",
        event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT",
        tags="peak_shaving",
        top_k=5,
    )
    assert result[0].event_type_match is True
    assert result[0].tags_boost > 0.0


def test_search_by_text_propagates_embedding_provider_error():
    conn = FakeConnection(rows=[])
    with pytest.raises(RuntimeError):
        search_by_text(conn, _BoomEmbeddingProvider(), "query", event_type=None, tags=None, top_k=5)


def test_search_by_text_returns_empty_list_when_no_candidates():
    provider = _FakeEmbeddingProvider()
    conn = FakeConnection(rows=[])

    result = search_by_text(conn, provider, "query", event_type=None, tags=None, top_k=5)
    assert result == []


def test_search_by_text_never_leaks_full_embedding_vector_in_result():
    provider = _FakeEmbeddingProvider()
    candidates = [_candidate("case-0001", distance=0.1)]
    conn = FakeConnection(rows=candidates)

    result = search_by_text(conn, provider, "query", event_type=None, tags=None, top_k=5)
    assert not hasattr(result[0], "embedding")
