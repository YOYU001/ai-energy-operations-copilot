"""Step 11 Sub-step 2B: unit tests for scripts/seed_case_records.py.

No real DB, no real OpenAI calls anywhere in this file. Normal-mode seeding
is exercised against FakeCaseRecordsConnection + a deterministic fake
embedding provider (reused from tests/pdf_fixtures.py, which is already
generic -- not PDF-specific -- despite its module name).
"""

import json
import sys
from pathlib import Path

import pytest

# scripts/ lives at the repo root, a sibling of backend/ -- pytest's sys.path
# insertion for this test file only reaches backend/ (the nearest ancestor
# without an __init__.py), not the repo root, so scripts.seed_case_records
# is not importable without this. Scoped to this file only, not a global
# conftest.py change.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from scripts.seed_case_records import (
    DEFAULT_SAMPLE_PATH,
    SampleDataError,
    build_case_search_text,
    dry_run,
    load_sample_cases,
    plan_seed,
    run_seed,
)
from tests.fakes import FakeCaseRecordsConnection
from tests.pdf_fixtures import DeterministicFakeEmbeddingProvider


def _case(**overrides):
    base = dict(
        case_id="case-x",
        site_id="SITE-A",
        event_time="2026-01-15T13:30:00",
        event_type="BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT",
        symptoms="symptoms text",
        root_cause="answer-shaped root cause text",
        operator_action="answer-shaped action text",
        resolution_result="answer-shaped result text",
        severity="high",
        tags="peak_shaving,SOC",
        related_dataset_id=None,
        related_time_range="2026-01-15T13:00:00~2026-01-15T14:00:00",
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 9. sample JSON loads successfully (13 cases)
# ---------------------------------------------------------------------------


def test_load_sample_cases_loads_13_real_sample_cases():
    cases = load_sample_cases(DEFAULT_SAMPLE_PATH)
    assert len(cases) == 13
    assert {c["case_id"] for c in cases} == {f"case-{i:04d}" for i in range(1, 14)}


# ---------------------------------------------------------------------------
# 10/11. embedding text composition
# ---------------------------------------------------------------------------


def test_case_search_text_includes_event_type_symptoms_tags():
    case = _case()
    text = build_case_search_text(case)
    assert case["event_type"] in text
    assert case["symptoms"] in text
    assert case["tags"] in text


def test_case_search_text_excludes_answer_shaped_fields():
    case = _case()
    text = build_case_search_text(case)
    assert case["root_cause"] not in text
    assert case["operator_action"] not in text
    assert case["resolution_result"] not in text


def test_case_search_text_handles_missing_optional_fields_gracefully():
    case = _case(tags=None, severity=None)
    text = build_case_search_text(case)  # must not raise
    assert case["event_type"] in text
    assert case["symptoms"] in text


# ---------------------------------------------------------------------------
# 12/13/14. dry-run: no DB connection, no embedding provider call, reports plan
# ---------------------------------------------------------------------------


def test_dry_run_never_imports_or_calls_get_connection(monkeypatch):
    import app.db

    def _boom():
        raise AssertionError("dry_run must never call get_connection")

    monkeypatch.setattr(app.db, "get_connection", _boom)
    items = dry_run(DEFAULT_SAMPLE_PATH)
    assert len(items) == 13


def test_dry_run_requires_no_embedding_provider_argument():
    # dry_run's signature itself takes no provider -- calling it successfully
    # with zero provider-related arguments is the proof it never needs one.
    items = dry_run(DEFAULT_SAMPLE_PATH)
    assert all(item.search_text for item in items)


def test_dry_run_reports_planned_case_count_and_case_ids(capsys):
    from scripts.seed_case_records import print_dry_run_summary

    items = dry_run(DEFAULT_SAMPLE_PATH)
    print_dry_run_summary(items)
    captured = capsys.readouterr()
    assert "13 case(s)" in captured.out
    assert "case-0001" in captured.out


# ---------------------------------------------------------------------------
# 15/16/17. normal mode against fake DB + fake embedding provider
# ---------------------------------------------------------------------------


def test_run_seed_produces_deterministic_embedding_per_case():
    conn = FakeCaseRecordsConnection()
    cases = [_case(case_id="case-a", symptoms="alpha"), _case(case_id="case-b", symptoms="beta")]
    provider = DeterministicFakeEmbeddingProvider()

    results = run_seed(conn, cases, provider)

    assert {r.case_id for r in results} == {"case-a", "case-b"}
    row_a = conn.rows_by_case_id["case-a"]
    row_b = conn.rows_by_case_id["case-b"]
    assert row_a["embedding"] is not None
    assert row_a["embedding"] != row_b["embedding"]  # different search text -> different vector

    # re-embedding identical search text must reproduce the identical vector
    conn2 = FakeCaseRecordsConnection()
    run_seed(conn2, [_case(case_id="case-a", symptoms="alpha")], DeterministicFakeEmbeddingProvider())
    assert conn2.rows_by_case_id["case-a"]["embedding"] == row_a["embedding"]


def test_run_seed_rerun_does_not_produce_duplicates():
    conn = FakeCaseRecordsConnection()
    cases = [_case(case_id=f"case-{i}") for i in range(3)]
    provider = DeterministicFakeEmbeddingProvider()

    run_seed(conn, cases, provider)
    ids_after_first_run = {cid: row["id"] for cid, row in conn.rows_by_case_id.items()}

    run_seed(conn, cases, DeterministicFakeEmbeddingProvider())
    assert len(conn.rows_by_case_id) == 3  # no duplicates
    ids_after_second_run = {cid: row["id"] for cid, row in conn.rows_by_case_id.items()}
    assert ids_after_first_run == ids_after_second_run  # same row identity reused


def test_run_seed_stores_embedding_provenance_metadata():
    conn = FakeCaseRecordsConnection()
    provider = DeterministicFakeEmbeddingProvider()

    run_seed(conn, [_case(case_id="case-a")], provider)

    row = conn.rows_by_case_id["case-a"]
    assert row["embedding_provider"] == provider.provider_name
    assert row["embedding_model"] == provider.model_name
    assert row["embedding_dimensions"] == provider.dimensions
    assert row["embedded_at"] is not None


def test_run_seed_commits_once_all_cases_are_upserted():
    conn = FakeCaseRecordsConnection()
    run_seed(conn, [_case(case_id="case-a")], DeterministicFakeEmbeddingProvider())
    assert conn.committed is True


# ---------------------------------------------------------------------------
# 18. invalid sample data fails clearly, never partially writes
# ---------------------------------------------------------------------------


def test_load_sample_cases_rejects_missing_required_field(tmp_path):
    bad_file = tmp_path / "bad_cases.json"
    bad_file.write_text(
        json.dumps({"cases": [{"case_id": "case-x"}]}),  # missing every other required field
        encoding="utf-8",
    )
    with pytest.raises(SampleDataError):
        load_sample_cases(bad_file)


def test_load_sample_cases_rejects_empty_cases_list(tmp_path):
    bad_file = tmp_path / "empty_cases.json"
    bad_file.write_text(json.dumps({"cases": []}), encoding="utf-8")
    with pytest.raises(SampleDataError):
        load_sample_cases(bad_file)


def test_invalid_sample_data_never_reaches_run_seed(tmp_path):
    bad_file = tmp_path / "bad_cases.json"
    bad_file.write_text(json.dumps({"cases": [{"case_id": "case-x"}]}), encoding="utf-8")

    conn = FakeCaseRecordsConnection()
    with pytest.raises(SampleDataError):
        cases = load_sample_cases(bad_file)
        run_seed(conn, cases, DeterministicFakeEmbeddingProvider())  # never reached

    assert conn.rows_by_case_id == {}  # nothing was written
    assert conn.committed is False


def test_plan_seed_produces_one_item_per_case():
    cases = [_case(case_id="case-a"), _case(case_id="case-b")]
    items = plan_seed(cases)
    assert [item.case_id for item in items] == ["case-a", "case-b"]
