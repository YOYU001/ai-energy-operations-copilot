from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.db import get_db_dependency
from app.main import app
from app.services.rule_engine import (
    ANALYSIS_TYPE,
    RULE_VERSION,
    evaluate_battery_should_discharge_but_did_not,
)
from tests.fakes import FakeConnection


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


def _timeseries_rows_for_analysis():
    return [
        {
            "timestamp": datetime(2026, 1, 1, h, tzinfo=timezone.utc),
            "electricity_price": p,
            "grid_import_kw": 95.0,
            "contract_capacity_kw": 100.0,
            "battery_soc": 50.0,
            "battery_power_kw": -5.0,
        }
        for h, p in enumerate([3.0, 3.0, 3.0, 7.0, 7.0, 7.0])
    ]


def _analysis_run_row(run_id=1, dataset_id=1, result=None, result_json_as_string=False):
    if result is None:
        result = evaluate_battery_should_discharge_but_did_not(_timeseries_rows_for_analysis())
    return {
        "id": run_id,
        "dataset_id": dataset_id,
        "analysis_type": ANALYSIS_TYPE,
        "rule_version": RULE_VERSION,
        # psycopg2 auto-deserializes jsonb columns to Python objects on read;
        # result_json_as_string exists only to exercise the opposite shape defensively
        "result_json": result.model_dump_json() if result_json_as_string else result.model_dump(mode="json"),
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


class _RaisingOnNthExecuteConnection(FakeConnection):
    """Raises on the Nth execute() call (1-indexed) to simulate a DB error mid-request."""

    def __init__(self, responses, raise_on_call):
        super().__init__(responses=responses)
        self._raise_on_call = raise_on_call

    def execute(self, statement, params=None):
        if len(self.executed) + 1 == self._raise_on_call:
            self.executed.append((statement, params))
            raise RuntimeError("simulated database error")
        return super().execute(statement, params)


# ---------------------------------------------------------------------------
# GET /datasets/{id}/analysis
# ---------------------------------------------------------------------------


def test_get_analysis_returns_404_when_dataset_not_found():
    _use_override_responses([[]])
    try:
        response = TestClient(app).get("/datasets/999/analysis")
    finally:
        _clear_override()

    assert response.status_code == 404
    assert "detail" in response.json()


def test_get_analysis_returns_404_when_not_yet_analyzed():
    _use_override_responses([[_dataset_row()], []])
    try:
        response = TestClient(app).get("/datasets/1/analysis")
    finally:
        _clear_override()

    assert response.status_code == 404
    assert "detail" in response.json()


def test_get_analysis_returns_existing_result_without_running_rule_engine():
    run_row = _analysis_run_row()
    _use_override_responses([[_dataset_row()], [run_row]])
    try:
        response = TestClient(app).get("/datasets/1/analysis")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["analysis_run_id"] == 1
    assert body["dataset_id"] == 1
    assert body["analysis_type"] == ANALYSIS_TYPE
    assert body["rule_version"] == RULE_VERSION
    assert body["result"]["flagged_row_count"] == run_row["result_json"]["flagged_row_count"]
    assert set(body.keys()) == {
        "analysis_run_id", "dataset_id", "analysis_type", "rule_version", "created_at", "result",
    }


# ---------------------------------------------------------------------------
# POST /datasets/{id}/analysis
# ---------------------------------------------------------------------------


def test_post_analysis_returns_404_when_dataset_not_found():
    _use_override_responses([[]])
    try:
        response = TestClient(app).post("/datasets/999/analysis")
    finally:
        _clear_override()

    assert response.status_code == 404


def test_post_analysis_first_run_executes_rule_engine_and_inserts():
    inserted_row = _analysis_run_row()
    conn = FakeConnection(responses=[
        [_dataset_row()],       # get_dataset_by_id
        [],                     # get_analysis_run: no existing result
        _timeseries_rows_for_analysis(),  # get_dataset_timeseries_for_analysis
        [inserted_row],         # insert_analysis_run RETURNING
    ])
    _use_override_connection(conn)
    try:
        response = TestClient(app).post("/datasets/1/analysis")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["rule_version"] == RULE_VERSION
    assert body["result"]["flagged_row_count"] >= 0
    assert conn.committed is True
    assert conn.rolled_back is False

    insert_statement, insert_params = conn.executed[3]
    assert "ON CONFLICT" in str(insert_statement)
    assert "CAST(:result_json AS JSONB)" in str(insert_statement)
    assert isinstance(insert_params["result_json"], str)  # model_dump_json(), not a dict


def test_post_analysis_repeated_call_returns_existing_without_second_insert():
    existing_row = _analysis_run_row()
    conn = FakeConnection(responses=[
        [_dataset_row()],   # get_dataset_by_id
        [existing_row],     # get_analysis_run: already exists
    ])
    _use_override_connection(conn)
    try:
        response = TestClient(app).post("/datasets/1/analysis")
    finally:
        _clear_override()

    assert response.status_code == 200
    assert len(conn.executed) == 2  # never reached timeseries fetch or insert
    assert conn.committed is False


def test_post_analysis_row_count_over_limit_returns_422_without_partial_analysis():
    conn = FakeConnection(responses=[
        [_dataset_row(row_count=50_001)],  # get_dataset_by_id
        [],                                  # get_analysis_run: no existing result
    ])
    _use_override_connection(conn)
    try:
        response = TestClient(app).post("/datasets/1/analysis")
    finally:
        _clear_override()

    assert response.status_code == 422
    assert len(conn.executed) == 2  # never fetched timeseries, never ran the rule engine


def test_post_analysis_on_conflict_do_nothing_then_re_selects():
    concurrent_row = _analysis_run_row()
    conn = FakeConnection(responses=[
        [_dataset_row()],                  # get_dataset_by_id
        [],                                  # get_analysis_run: no existing result yet
        _timeseries_rows_for_analysis(),    # get_dataset_timeseries_for_analysis
        [],                                  # insert_analysis_run: ON CONFLICT DO NOTHING -> no RETURNING row
        [concurrent_row],                   # re-SELECT: the concurrent request's row
    ])
    _use_override_connection(conn)
    try:
        response = TestClient(app).post("/datasets/1/analysis")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["analysis_run_id"] == concurrent_row["id"]
    assert len(conn.executed) == 5
    assert conn.committed is True  # commit() still runs even though 0 rows were affected


def test_post_analysis_zero_anomalies_still_stored():
    zero_anomaly_result = evaluate_battery_should_discharge_but_did_not([])
    inserted_row = _analysis_run_row(result=zero_anomaly_result)
    conn = FakeConnection(responses=[
        [_dataset_row(row_count=0)],  # get_dataset_by_id
        [],                             # get_analysis_run: no existing result
        [],                             # get_dataset_timeseries_for_analysis: empty dataset
        [inserted_row],                # insert_analysis_run RETURNING
    ])
    _use_override_connection(conn)
    try:
        response = TestClient(app).post("/datasets/1/analysis")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["flagged_row_count"] == 0
    assert body["result"]["anomalies"] == []
    assert conn.committed is True


def test_post_analysis_insert_failure_rolls_back_and_propagates():
    conn = _RaisingOnNthExecuteConnection(
        responses=[
            [_dataset_row()],                 # 1: get_dataset_by_id
            [],                                  # 2: get_analysis_run
            _timeseries_rows_for_analysis(),    # 3: get_dataset_timeseries_for_analysis
        ],
        raise_on_call=4,  # the INSERT
    )
    _use_override_connection(conn)
    try:
        response = TestClient(app, raise_server_exceptions=False).post("/datasets/1/analysis")
    finally:
        _clear_override()

    assert response.status_code == 500
    assert conn.rolled_back is True
    assert conn.committed is False
