from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.db import get_db_dependency
from app.main import _green_ops_rule_version, app
from app.services.green_operations_index import ANALYSIS_TYPE, evaluate_green_operations_index
from tests.fakes import FakeConnection

MAX_GAP = 6.0


def _dataset_row(dataset_id=1, row_count=10):
    return {
        "id": dataset_id,
        "name": "demo",
        "file_name": "demo.csv",
        "description": None,
        "row_count": row_count,
        "start_time": None,
        "end_time": None,
        "created_at": None,
    }


def _timeseries_rows():
    return [
        {
            "timestamp": datetime(2026, 1, 1, h, tzinfo=timezone.utc),
            "site_id": "site_a",
            "electricity_price": 5.0,
            "grid_import_kw": 10.0,
            "grid_export_kw": 0.0,
            "contract_capacity_kw": 100.0,
            "battery_soc": 50.0,
            "battery_soh": 90.0,
            "battery_power_kw": 0.0,
            "battery_temperature": 25.0,
            "battery_health_status": "normal",
            "battery_is_second_life": False,
            "pv_actual_kw": 5.0,
            "load_kw": 10.0,
        }
        for h in range(3)
    ]


def _run_row(run_id=1, dataset_id=1, max_gap=MAX_GAP, result=None):
    if result is None:
        result = evaluate_green_operations_index(_timeseries_rows(), max_gap)
    return {
        "id": run_id,
        "dataset_id": dataset_id,
        "analysis_type": ANALYSIS_TYPE,
        "rule_version": _green_ops_rule_version(max_gap),
        "result_json": result.model_dump(mode="json"),
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }


def _use_override_responses(responses):
    def _fake_dependency():
        yield FakeConnection(responses=responses)

    app.dependency_overrides[get_db_dependency] = _fake_dependency


def _use_override_connection(conn):
    def _fake_dependency():
        yield conn

    app.dependency_overrides[get_db_dependency] = _fake_dependency


def _clear_override():
    app.dependency_overrides.pop(get_db_dependency, None)


# ---------------------------------------------------------------------------
# 422: missing / invalid max_expected_interval_hours
# ---------------------------------------------------------------------------


def test_get_green_ops_422_when_param_missing():
    _use_override_responses([])
    try:
        response = TestClient(app).get("/datasets/1/green-operations-index")
    finally:
        _clear_override()
    assert response.status_code == 422


def test_post_green_ops_422_when_param_missing():
    _use_override_responses([])
    try:
        response = TestClient(app).post("/datasets/1/green-operations-index")
    finally:
        _clear_override()
    assert response.status_code == 422


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "0", "-5"])
def test_post_green_ops_422_for_non_finite_or_nonpositive(value):
    _use_override_responses([])
    try:
        response = TestClient(app).post(
            "/datasets/1/green-operations-index", params={"max_expected_interval_hours": value}
        )
    finally:
        _clear_override()
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------


def test_get_green_ops_404_when_dataset_not_found():
    _use_override_responses([[]])
    try:
        response = TestClient(app).get(
            "/datasets/999/green-operations-index", params={"max_expected_interval_hours": 6}
        )
    finally:
        _clear_override()
    assert response.status_code == 404


def test_get_green_ops_404_when_no_run_for_these_params():
    _use_override_responses([[_dataset_row()], []])
    try:
        response = TestClient(app).get(
            "/datasets/1/green-operations-index", params={"max_expected_interval_hours": 6}
        )
    finally:
        _clear_override()
    assert response.status_code == 404


def test_get_green_ops_returns_run_matching_params_and_echoes_parameter():
    run_row = _run_row(max_gap=6.0)
    _use_override_responses([[_dataset_row()], [run_row]])
    try:
        response = TestClient(app).get(
            "/datasets/1/green-operations-index", params={"max_expected_interval_hours": 6.0}
        )
    finally:
        _clear_override()

    assert response.status_code == 200
    assert response.json()["result"]["max_expected_interval_hours"] == 6.0


def test_get_green_ops_ignores_max_analysis_rows_even_when_dataset_is_oversized():
    run_row = _run_row(max_gap=6.0)
    _use_override_responses([[_dataset_row(row_count=999_999)], [run_row]])
    try:
        response = TestClient(app).get(
            "/datasets/1/green-operations-index", params={"max_expected_interval_hours": 6.0}
        )
    finally:
        _clear_override()
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# POST: identity / idempotency / different-params-do-not-collide
# ---------------------------------------------------------------------------


def test_post_green_ops_first_run_executes_and_inserts_with_canonical_rule_version():
    inserted_row = _run_row(max_gap=6.0)
    conn = FakeConnection(
        responses=[
            [_dataset_row()],
            [],
            _timeseries_rows(),
            [inserted_row],
        ]
    )
    _use_override_connection(conn)
    try:
        response = TestClient(app).post(
            "/datasets/1/green-operations-index", params={"max_expected_interval_hours": 6.0}
        )
    finally:
        _clear_override()

    assert response.status_code == 200
    assert conn.committed is True

    expected_rule_version = _green_ops_rule_version(6.0)
    assert conn.executed[1][1]["rule_version"] == expected_rule_version
    assert conn.executed[3][1]["rule_version"] == expected_rule_version
    assert response.json()["result"]["max_expected_interval_hours"] == 6.0


def test_post_green_ops_repeated_call_same_params_hits_existing_run_without_insert():
    existing_row = _run_row(max_gap=6.0)
    conn = FakeConnection(responses=[[_dataset_row()], [existing_row]])
    _use_override_connection(conn)
    try:
        response = TestClient(app).post(
            "/datasets/1/green-operations-index", params={"max_expected_interval_hours": 6.0}
        )
    finally:
        _clear_override()

    assert response.status_code == 200
    assert len(conn.executed) == 2
    assert conn.committed is False


def test_post_green_ops_6_6point0_and_6e0_all_query_the_same_rule_version():
    seen_rule_versions = set()
    for literal in (6, 6.0, "6e0"):
        existing_row = _run_row(max_gap=6.0)
        conn = FakeConnection(responses=[[_dataset_row()], [existing_row]])
        _use_override_connection(conn)
        try:
            response = TestClient(app).post(
                "/datasets/1/green-operations-index", params={"max_expected_interval_hours": literal}
            )
        finally:
            _clear_override()
        assert response.status_code == 200
        seen_rule_versions.add(conn.executed[1][1]["rule_version"])

    assert len(seen_rule_versions) == 1


def test_post_green_ops_different_params_query_different_rule_versions_not_the_old_run():
    conn_a = FakeConnection(responses=[[_dataset_row()], [_run_row(max_gap=6.0)]])
    _use_override_connection(conn_a)
    try:
        TestClient(app).post("/datasets/1/green-operations-index", params={"max_expected_interval_hours": 6})
    finally:
        _clear_override()
    rule_version_a = conn_a.executed[1][1]["rule_version"]

    conn_b = FakeConnection(responses=[[_dataset_row()], [_run_row(max_gap=2.0)]])
    _use_override_connection(conn_b)
    try:
        TestClient(app).post("/datasets/1/green-operations-index", params={"max_expected_interval_hours": 2})
    finally:
        _clear_override()
    rule_version_b = conn_b.executed[1][1]["rule_version"]

    assert rule_version_a != rule_version_b


def test_post_green_ops_row_count_over_limit_returns_422():
    conn = FakeConnection(responses=[[_dataset_row(row_count=50_001)], []])
    _use_override_connection(conn)
    try:
        response = TestClient(app).post(
            "/datasets/1/green-operations-index", params={"max_expected_interval_hours": 6}
        )
    finally:
        _clear_override()

    assert response.status_code == 422
    assert len(conn.executed) == 2


def test_post_green_ops_on_conflict_do_nothing_then_re_selects():
    concurrent_row = _run_row(max_gap=6.0)
    conn = FakeConnection(
        responses=[
            [_dataset_row()],
            [],
            _timeseries_rows(),
            [],
            [concurrent_row],
        ]
    )
    _use_override_connection(conn)
    try:
        response = TestClient(app).post(
            "/datasets/1/green-operations-index", params={"max_expected_interval_hours": 6.0}
        )
    finally:
        _clear_override()

    assert response.status_code == 200
    assert response.json()["analysis_run_id"] == concurrent_row["id"]
    assert conn.committed is True


def test_post_green_ops_zero_rows_still_stored():
    empty_result = evaluate_green_operations_index([], 6.0)
    inserted_row = _run_row(max_gap=6.0, result=empty_result)
    conn = FakeConnection(
        responses=[
            [_dataset_row(row_count=0)],
            [],
            [],
            [inserted_row],
        ]
    )
    _use_override_connection(conn)
    try:
        response = TestClient(app).post(
            "/datasets/1/green-operations-index", params={"max_expected_interval_hours": 6.0}
        )
    finally:
        _clear_override()

    assert response.status_code == 200
    assert response.json()["result"]["site_count"] == 0
    assert conn.committed is True
