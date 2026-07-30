"""Step 11 Sub-step 2A/2B: unit tests for app/case_records_queries.py.

Uses FakeCaseRecordsConnection (backend/tests/fakes.py) -- no real database,
no OpenAI calls. Covers upsert idempotency and the candidate-query/upsert
SQL shape; real vector-distance/ordering correctness and the real UNIQUE
constraint itself are verified against the real dev DB separately (see the
Sub-step 2B report for the migration verification), matching how Step 10
split unit vs. integration coverage.
"""

from pathlib import Path

from app.case_records_queries import (
    fetch_candidate_cases,
    get_case_by_case_id,
    get_case_by_id,
    get_cases_by_case_ids,
    list_cases,
    upsert_case_record,
)
from tests.fakes import FakeCaseRecordsConnection, FakeConnection

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SQL_PATH = REPO_ROOT / "database" / "schema.sql"


def _kwargs(**overrides):
    base = dict(
        case_id="case-0001",
        site_id="SITE-A",
        event_time="2026-01-15T13:30:00",
        event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT",
        symptoms="symptoms text",
        root_cause="root cause text",
        operator_action="action text",
        resolution_result="result text",
        severity="high",
        tags="peak_shaving,SOC",
        related_dataset_id=None,
        related_time_range="2026-01-15T13:00:00~2026-01-15T14:00:00",
    )
    base.update(overrides)
    return base


def test_get_case_by_case_id_returns_none_when_absent():
    conn = FakeCaseRecordsConnection()
    assert get_case_by_case_id(conn, "missing") is None


def test_upsert_inserts_new_case_and_returns_id():
    conn = FakeCaseRecordsConnection()
    new_id = upsert_case_record(conn, **_kwargs())

    row = get_case_by_case_id(conn, "case-0001")
    assert row["id"] == new_id
    assert row["symptoms"] == "symptoms text"
    assert row["embedding"] is None
    assert row["embedded_at"] is None


def test_upsert_same_case_id_twice_does_not_create_a_duplicate_row():
    conn = FakeCaseRecordsConnection()
    first_id = upsert_case_record(conn, **_kwargs())
    second_id = upsert_case_record(conn, **_kwargs(symptoms="updated symptoms"))

    assert second_id == first_id
    assert len(conn.rows_by_case_id) == 1
    row = get_case_by_case_id(conn, "case-0001")
    assert row["symptoms"] == "updated symptoms"


def test_upsert_with_embedding_sets_embedded_at_and_provenance():
    conn = FakeCaseRecordsConnection()
    upsert_case_record(
        conn,
        **_kwargs(
            embedding=[0.1, 0.2, 0.3],
            embedding_provider="openai",
            embedding_model="text-embedding-3-small",
            embedding_dimensions=3,
            embedding_model_version="v1",
        ),
    )
    row = get_case_by_case_id(conn, "case-0001")
    assert row["embedding"] == "[0.1, 0.2, 0.3]"
    assert row["embedding_provider"] == "openai"
    assert row["embedded_at"] is not None


def test_upsert_without_embedding_does_not_erase_existing_embedding():
    conn = FakeCaseRecordsConnection()
    upsert_case_record(conn, **_kwargs(embedding=[0.1, 0.2], embedding_provider="openai"))
    upsert_case_record(conn, **_kwargs(symptoms="structured field update only"))

    row = get_case_by_case_id(conn, "case-0001")
    assert row["embedding"] == "[0.1, 0.2]"
    assert row["embedding_provider"] == "openai"
    assert row["symptoms"] == "structured field update only"


def test_upsert_with_embedding_content_hash_stores_it_alongside_embedding():
    conn = FakeCaseRecordsConnection()
    upsert_case_record(
        conn,
        **_kwargs(
            embedding=[0.1, 0.2, 0.3],
            embedding_provider="openai",
            embedding_model="text-embedding-3-small",
            embedding_dimensions=3,
            embedding_model_version="v1",
            embedding_content_hash="hash-1",
        ),
    )
    row = get_case_by_case_id(conn, "case-0001")
    assert row["embedding_content_hash"] == "hash-1"


def test_upsert_without_embedding_does_not_erase_existing_embedding_content_hash():
    conn = FakeCaseRecordsConnection()
    upsert_case_record(
        conn,
        **_kwargs(embedding=[0.1, 0.2], embedding_provider="openai", embedding_content_hash="hash-1"),
    )
    upsert_case_record(conn, **_kwargs(symptoms="structured field update only"))

    row = get_case_by_case_id(conn, "case-0001")
    assert row["embedding_content_hash"] == "hash-1"


def test_upsert_can_add_embedding_to_a_row_that_had_none_before():
    conn = FakeCaseRecordsConnection()
    upsert_case_record(conn, **_kwargs())  # no embedding on first insert
    row_before = get_case_by_case_id(conn, "case-0001")
    assert row_before["embedding"] is None

    upsert_case_record(
        conn,
        **_kwargs(
            embedding=[0.4, 0.5],
            embedding_provider="openai",
            embedding_model="text-embedding-3-small",
            embedding_dimensions=2,
            embedding_model_version="v1",
        ),
    )
    row_after = get_case_by_case_id(conn, "case-0001")
    assert row_after["embedding"] == "[0.4, 0.5]"
    assert row_after["embedding_provider"] == "openai"
    assert row_after["embedded_at"] is not None


# ---------------------------------------------------------------------------
# Sub-step 2B: atomic upsert SQL shape (item 2 -- ON CONFLICT (case_id);
# item 3 -- no separate pre-upsert SELECT statement)
# ---------------------------------------------------------------------------


def test_upsert_sql_uses_on_conflict_case_id():
    conn = FakeConnection(rows=[{"id": 1}])
    upsert_case_record(conn, **_kwargs())

    statement, _ = conn.executed[-1]
    sql = str(statement)
    assert "ON CONFLICT (case_id) DO UPDATE" in sql
    assert "INSERT INTO case_records" in sql
    assert "RETURNING id" in sql


def test_upsert_executes_exactly_one_statement_no_pre_upsert_select():
    conn = FakeConnection(rows=[{"id": 1}])
    upsert_case_record(conn, **_kwargs())

    assert len(conn.executed) == 1  # a single atomic INSERT ... ON CONFLICT, not SELECT-then-branch


# ---------------------------------------------------------------------------
# Sub-step 2B: schema source-of-truth check (item 1 -- case_id NOT NULL +
# UNIQUE). Lightweight text check against database/schema.sql, matching this
# project's convention of no ORM/migration framework to introspect instead.
# ---------------------------------------------------------------------------


def test_schema_sql_declares_case_id_not_null_unique():
    schema_text = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    assert "case_id TEXT NOT NULL UNIQUE" in schema_text


def test_schema_sql_has_repeatable_upgrade_path_for_existing_databases():
    """PR #37 Codex review, P1: CREATE TABLE IF NOT EXISTS alone is a no-op
    against a case_records table created before case_id was NOT NULL UNIQUE
    -- schema.sql must also carry an idempotent upgrade path that (a) never
    silently drops/rewrites bad existing data, and (b) is safe to re-run.
    """
    schema_text = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS embedding_content_hash" in schema_text
    assert "RAISE EXCEPTION" in schema_text
    assert "case_records_case_id_key" in schema_text
    assert "ALTER COLUMN case_id SET NOT NULL" in schema_text


def test_get_case_by_id():
    conn = FakeCaseRecordsConnection()
    new_id = upsert_case_record(conn, **_kwargs())
    row = get_case_by_id(conn, new_id)
    assert row["case_id"] == "case-0001"


def test_get_case_by_id_returns_none_when_absent():
    conn = FakeCaseRecordsConnection()
    assert get_case_by_id(conn, 999) is None


def test_list_cases_returns_all_inserted_rows():
    conn = FakeCaseRecordsConnection()
    upsert_case_record(conn, **_kwargs(case_id="case-0001"))
    upsert_case_record(conn, **_kwargs(case_id="case-0002"))

    total, rows = list_cases(conn, limit=100, offset=0)
    assert total == 2
    assert {r["case_id"] for r in rows} == {"case-0001", "case-0002"}


def test_list_cases_respects_limit_and_offset():
    conn = FakeCaseRecordsConnection()
    for i in range(5):
        upsert_case_record(conn, **_kwargs(case_id=f"case-{i:04d}"))

    total, rows = list_cases(conn, limit=2, offset=0)
    assert total == 5
    assert len(rows) == 2

    total, rows = list_cases(conn, limit=2, offset=4)
    assert total == 5
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# fetch_candidate_cases SQL shape (parameterization, filters) -- uses the
# existing simple FakeConnection (canned rows, records executed SQL/params),
# same pattern as test_retrieval.py's fetch_candidates tests.
# ---------------------------------------------------------------------------


def test_fetch_candidate_cases_filters_embedded_rows_only():
    conn = FakeConnection(rows=[])
    fetch_candidate_cases(conn, [0.1, 0.2])

    statement, params = conn.executed[-1]
    sql = str(statement)
    assert "embedding IS NOT NULL" in sql
    assert "ORDER BY distance" in sql
    assert params["qv"] == str([0.1, 0.2])
    assert params["k"] == 30


def test_fetch_candidate_cases_respects_pool_size_param():
    conn = FakeConnection(rows=[])
    fetch_candidate_cases(conn, [0.1, 0.2], pool_size=5)

    _, params = conn.executed[-1]
    assert params["k"] == 5


def test_fetch_candidate_cases_parameterizes_query_vector_not_string_interpolated():
    conn = FakeConnection(rows=[])
    query_vector = [0.1, 0.2, 0.3]
    fetch_candidate_cases(conn, query_vector)

    statement, params = conn.executed[-1]
    assert ":qv" in str(statement)
    assert str(query_vector) not in str(statement)
    assert params["qv"] == str(query_vector)


# ---------------------------------------------------------------------------
# get_cases_by_case_ids -- bulk fetch used by scripts/seed_case_records.py's
# embedding-idempotency check (fix: avoid redundant case embedding requests)
# ---------------------------------------------------------------------------


def test_get_cases_by_case_ids_returns_only_matching_existing_rows():
    conn = FakeCaseRecordsConnection()
    upsert_case_record(conn, **_kwargs(case_id="case-0001"))
    upsert_case_record(conn, **_kwargs(case_id="case-0002"))
    upsert_case_record(conn, **_kwargs(case_id="case-0003"))

    result = get_cases_by_case_ids(conn, ["case-0001", "case-0003", "case-missing"])

    assert set(result.keys()) == {"case-0001", "case-0003"}
    assert result["case-0001"]["case_id"] == "case-0001"


def test_get_cases_by_case_ids_returns_empty_dict_for_empty_input():
    conn = FakeCaseRecordsConnection()
    assert get_cases_by_case_ids(conn, []) == {}


def test_get_cases_by_case_ids_uses_any_parameterized_query_not_one_per_id():
    conn = FakeConnection(rows=[])
    get_cases_by_case_ids(conn, ["case-a", "case-b"])

    assert len(conn.executed) == 1  # single batch query, not one SELECT per case_id
    statement, params = conn.executed[-1]
    assert "= ANY(:ids)" in str(statement)
    assert params["ids"] == ["case-a", "case-b"]
