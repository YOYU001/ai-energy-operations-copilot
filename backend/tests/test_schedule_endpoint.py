from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.db import get_db_dependency
from app.main import app
from app.services.battery_scheduling import ANALYSIS_TYPE, RULE_VERSION, evaluate_battery_scheduling
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


def _timeseries_rows():
    return [
        {
            "timestamp": datetime(2026, 1, 1, h, tzinfo=timezone.utc),
            "site_id": "site_a",
            "electricity_price": p,
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
        for h, p in enumerate([3.0, 3.0, 3.0, 7.0, 7.0, 7.0])
    ]


def _run_row(run_id=1, dataset_id=1, result=None):
    if result is None:
        result = evaluate_battery_scheduling(_timeseries_rows())
    return {
        "id": run_id,
        "dataset_id": dataset_id,
        "analysis_type": ANALYSIS_TYPE,
        "rule_version": RULE_VERSION,
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


def test_get_schedule_404_when_dataset_not_found():
    _use_override_responses([[]])
    try:
        response = TestClient(app).get("/datasets/999/schedule")
    finally:
        _clear_override()
    assert response.status_code == 404


def test_get_schedule_404_when_not_yet_run():
    _use_override_responses([[_dataset_row()], []])
    try:
        response = TestClient(app).get("/datasets/1/schedule")
    finally:
        _clear_override()
    assert response.status_code == 404


def test_get_schedule_returns_existing_result():
    run_row = _run_row()
    _use_override_responses([[_dataset_row()], [run_row]])
    try:
        response = TestClient(app).get("/datasets/1/schedule")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["analysis_type"] == ANALYSIS_TYPE
    assert body["rule_version"] == RULE_VERSION


def test_post_schedule_first_run_executes_and_inserts():
    inserted_row = _run_row()
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
        response = TestClient(app).post("/datasets/1/schedule")
    finally:
        _clear_override()

    assert response.status_code == 200
    assert conn.committed is True


def test_post_schedule_repeated_call_returns_existing_without_second_insert():
    existing_row = _run_row()
    conn = FakeConnection(responses=[[_dataset_row()], [existing_row]])
    _use_override_connection(conn)
    try:
        response = TestClient(app).post("/datasets/1/schedule")
    finally:
        _clear_override()

    assert response.status_code == 200
    assert len(conn.executed) == 2


def test_post_schedule_row_count_over_limit_returns_422():
    conn = FakeConnection(responses=[[_dataset_row(row_count=50_001)], []])
    _use_override_connection(conn)
    try:
        response = TestClient(app).post("/datasets/1/schedule")
    finally:
        _clear_override()

    assert response.status_code == 422
    assert len(conn.executed) == 2
