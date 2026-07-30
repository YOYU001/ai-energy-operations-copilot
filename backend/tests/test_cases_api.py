"""Step 11 Sub-step 3: Case Similarity Backend API route tests.

Uses FakeCaseRecordsConnection (no real DB) via app.dependency_overrides,
exactly like test_documents_api.py uses FakeRagConnection. Rows are seeded
directly by calling the real upsert_case_record against the fake connection
(there is no seed-via-API path), so these tests exercise the real query
layer + real case_similarity scoring, only the DB and embedding provider are
faked.

No real OpenAI API calls: app.main._build_embedding_provider is
monkeypatched to a deterministic fake provider for /cases/search tests.
"""

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.case_records_queries import upsert_case_record
from app.db import get_db_dependency
from app.main import app
from tests.fakes import FakeCaseRecordsConnection

client = TestClient(app)


def _use_fake_connection(conn: FakeCaseRecordsConnection) -> None:
    def _override():
        yield conn

    app.dependency_overrides[get_db_dependency] = _override


def _clear_override():
    app.dependency_overrides.pop(get_db_dependency, None)


def _use_provider(monkeypatch, provider) -> None:
    monkeypatch.setattr(main_module, "_build_embedding_provider", lambda: provider)


def _use_boom_provider(monkeypatch) -> None:
    def _boom():
        raise AssertionError("embedding provider must not be called on this path")

    monkeypatch.setattr(main_module, "_build_embedding_provider", _boom)


def _kwargs(**overrides):
    base = dict(
        case_id="case-0001",
        site_id="SITE-A",
        event_time="2026-01-15T13:30:00",
        event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT",
        symptoms="symptoms text",
        root_cause="answer-shaped root cause",
        operator_action="answer-shaped action",
        resolution_result="answer-shaped result",
        severity="high",
        tags="peak_shaving,SOC",
        related_dataset_id=None,
        related_time_range="2026-01-15T13:00:00~2026-01-15T14:00:00",
    )
    base.update(overrides)
    return base


class _FakeEmbeddingResult:
    def __init__(self, vector):
        self.results = [_Embedded(vector)]


class _Embedded:
    def __init__(self, vector):
        self.vector = vector


class _FakeEmbeddingProvider:
    def __init__(self, vector=None):
        self.vector = vector or [1.0, 0.0, 0.0]
        self.calls = []

    def embed_batch(self, texts):
        self.calls.append(list(texts))
        return _FakeEmbeddingResult(self.vector)


class _BoomEmbeddingProvider:
    def embed_batch(self, texts):
        raise RuntimeError("simulated embedding provider failure")


# ---------------------------------------------------------------------------
# GET /cases
# ---------------------------------------------------------------------------


def test_get_cases_normal_list():
    conn = FakeCaseRecordsConnection()
    upsert_case_record(conn, **_kwargs(case_id="case-0001"))
    upsert_case_record(conn, **_kwargs(case_id="case-0002"))
    _use_fake_connection(conn)
    try:
        response = client.get("/cases")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    ids = {item["case_id"] for item in body["items"]}
    assert ids == {"case-0001", "case-0002"}


def test_get_cases_empty_result():
    conn = FakeCaseRecordsConnection()
    _use_fake_connection(conn)
    try:
        response = client.get("/cases")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body == {"total": 0, "limit": 100, "offset": 0, "items": []}


def test_get_cases_respects_limit_and_offset():
    conn = FakeCaseRecordsConnection()
    for i in range(5):
        upsert_case_record(conn, **_kwargs(case_id=f"case-{i:04d}"))
    _use_fake_connection(conn)
    try:
        response = client.get("/cases", params={"limit": 2, "offset": 0})
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 0


def test_get_cases_rejects_out_of_range_limit():
    conn = FakeCaseRecordsConnection()
    _use_fake_connection(conn)
    try:
        response = client.get("/cases", params={"limit": 0})
    finally:
        _clear_override()

    assert response.status_code == 422


def test_get_cases_summary_excludes_answer_shaped_fields():
    conn = FakeCaseRecordsConnection()
    upsert_case_record(conn, **_kwargs())
    _use_fake_connection(conn)
    try:
        response = client.get("/cases")
    finally:
        _clear_override()

    item = response.json()["items"][0]
    assert "root_cause" not in item
    assert "operator_action" not in item
    assert "resolution_result" not in item
    assert "embedding" not in item


# ---------------------------------------------------------------------------
# GET /cases/{case_id}
# ---------------------------------------------------------------------------


def test_get_case_detail_normal():
    conn = FakeCaseRecordsConnection()
    upsert_case_record(conn, **_kwargs())
    _use_fake_connection(conn)
    try:
        response = client.get("/cases/case-0001")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == "case-0001"
    assert body["root_cause"] == "answer-shaped root cause"
    assert body["operator_action"] == "answer-shaped action"
    assert body["resolution_result"] == "answer-shaped result"
    assert "embedding" not in body


def test_get_case_detail_404_when_absent():
    conn = FakeCaseRecordsConnection()
    _use_fake_connection(conn)
    try:
        response = client.get("/cases/does-not-exist")
    finally:
        _clear_override()

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /cases/{case_id}/similar
# ---------------------------------------------------------------------------


def test_get_similar_cases_excludes_self_and_never_calls_embedding_provider(monkeypatch):
    conn = FakeCaseRecordsConnection()
    upsert_case_record(conn, **_kwargs(case_id="case-0001", embedding=[1.0, 0.0, 0.0]))
    upsert_case_record(conn, **_kwargs(case_id="case-0002", embedding=[0.9, 0.1, 0.0]))
    upsert_case_record(conn, **_kwargs(case_id="case-0003", embedding=[0.0, 1.0, 0.0]))
    _use_fake_connection(conn)
    _use_boom_provider(monkeypatch)
    try:
        response = client.get("/cases/case-0001/similar")
    finally:
        _clear_override()

    assert response.status_code == 200
    ids = [item["case_id"] for item in response.json()]
    assert "case-0001" not in ids
    assert "case-0002" in ids
    assert "case-0003" in ids


def test_get_similar_cases_respects_top_k(monkeypatch):
    conn = FakeCaseRecordsConnection()
    upsert_case_record(conn, **_kwargs(case_id="case-0000", embedding=[1.0, 0.0, 0.0]))
    for i in range(1, 6):
        upsert_case_record(conn, **_kwargs(case_id=f"case-000{i}", embedding=[1.0 - i * 0.1, i * 0.1, 0.0]))
    _use_fake_connection(conn)
    _use_boom_provider(monkeypatch)
    try:
        response = client.get("/cases/case-0000/similar", params={"top_k": 2})
    finally:
        _clear_override()

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_similar_cases_404_when_case_absent(monkeypatch):
    conn = FakeCaseRecordsConnection()
    _use_fake_connection(conn)
    _use_boom_provider(monkeypatch)
    try:
        response = client.get("/cases/does-not-exist/similar")
    finally:
        _clear_override()

    assert response.status_code == 404


def test_get_similar_cases_422_when_no_embedding(monkeypatch):
    conn = FakeCaseRecordsConnection()
    upsert_case_record(conn, **_kwargs(case_id="case-0001"))  # no embedding passed
    _use_fake_connection(conn)
    _use_boom_provider(monkeypatch)
    try:
        response = client.get("/cases/case-0001/similar")
    finally:
        _clear_override()

    assert response.status_code == 422
    assert "no embedding yet" in response.json()["detail"]


def test_get_similar_cases_result_excludes_answer_shaped_fields(monkeypatch):
    conn = FakeCaseRecordsConnection()
    upsert_case_record(conn, **_kwargs(case_id="case-0001", embedding=[1.0, 0.0, 0.0]))
    upsert_case_record(conn, **_kwargs(case_id="case-0002", embedding=[0.9, 0.1, 0.0]))
    _use_fake_connection(conn)
    _use_boom_provider(monkeypatch)
    try:
        response = client.get("/cases/case-0001/similar")
    finally:
        _clear_override()

    item = response.json()[0]
    assert "root_cause" not in item
    assert "operator_action" not in item
    assert "resolution_result" not in item
    assert "embedding" not in item
    assert set(item.keys()) == {
        "case_id",
        "event_type",
        "symptoms",
        "tags",
        "severity",
        "semantic_score",
        "event_type_match",
        "tags_boost",
        "final_score",
        "confidence",
        "case_similarity",
        "matches",
        "differs",
    }


# ---------------------------------------------------------------------------
# POST /cases/search
# ---------------------------------------------------------------------------


def test_post_case_search_normal(monkeypatch):
    conn = FakeCaseRecordsConnection()
    upsert_case_record(conn, **_kwargs(case_id="case-0001", embedding=[1.0, 0.0, 0.0]))
    _use_fake_connection(conn)
    _use_provider(monkeypatch, _FakeEmbeddingProvider(vector=[1.0, 0.0, 0.0]))
    try:
        response = client.post("/cases/search", json={"query": "battery discharge issue"})
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["case_id"] == "case-0001"


def test_post_case_search_rejects_blank_query(monkeypatch):
    conn = FakeCaseRecordsConnection()
    _use_fake_connection(conn)
    _use_boom_provider(monkeypatch)
    try:
        response = client.post("/cases/search", json={"query": "   "})
    finally:
        _clear_override()

    assert response.status_code == 400


def test_post_case_search_rejects_top_k_out_of_range(monkeypatch):
    conn = FakeCaseRecordsConnection()
    _use_fake_connection(conn)
    _use_boom_provider(monkeypatch)
    try:
        response = client.post("/cases/search", json={"query": "x", "top_k": 21})
    finally:
        _clear_override()

    assert response.status_code == 422


def test_post_case_search_applies_optional_event_type_and_tags(monkeypatch):
    conn = FakeCaseRecordsConnection()
    upsert_case_record(
        conn,
        **_kwargs(
            case_id="case-0001",
            event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT",
            tags="peak_shaving,SOC",
            embedding=[1.0, 0.0, 0.0],
        ),
    )
    _use_fake_connection(conn)
    _use_provider(monkeypatch, _FakeEmbeddingProvider(vector=[1.0, 0.0, 0.0]))
    try:
        response = client.post(
            "/cases/search",
            json={"query": "x", "event_type": "BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT", "tags": "peak_shaving"},
        )
    finally:
        _clear_override()

    body = response.json()[0]
    assert body["event_type_match"] is True
    assert body["tags_boost"] > 0.0


def test_post_case_search_embedding_provider_error(monkeypatch):
    conn = FakeCaseRecordsConnection()
    upsert_case_record(conn, **_kwargs(case_id="case-0001", embedding=[1.0, 0.0, 0.0]))
    _use_fake_connection(conn)
    _use_provider(monkeypatch, _BoomEmbeddingProvider())
    try:
        with pytest.raises(RuntimeError):
            client.post("/cases/search", json={"query": "x"})
    finally:
        _clear_override()


def test_post_case_search_no_candidates_returns_empty_list(monkeypatch):
    conn = FakeCaseRecordsConnection()
    _use_fake_connection(conn)
    _use_provider(monkeypatch, _FakeEmbeddingProvider())
    try:
        response = client.post("/cases/search", json={"query": "x"})
    finally:
        _clear_override()

    assert response.status_code == 200
    assert response.json() == []


def test_post_case_search_result_excludes_answer_shaped_fields_and_embedding(monkeypatch):
    conn = FakeCaseRecordsConnection()
    upsert_case_record(conn, **_kwargs(case_id="case-0001", embedding=[1.0, 0.0, 0.0]))
    _use_fake_connection(conn)
    _use_provider(monkeypatch, _FakeEmbeddingProvider(vector=[1.0, 0.0, 0.0]))
    try:
        response = client.post("/cases/search", json={"query": "x"})
    finally:
        _clear_override()

    item = response.json()[0]
    assert "root_cause" not in item
    assert "operator_action" not in item
    assert "resolution_result" not in item
    assert "embedding" not in item
