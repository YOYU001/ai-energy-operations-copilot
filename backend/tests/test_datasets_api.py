from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.datasets_queries import SUMMARY_NUMERIC_COLUMNS
from app.db import get_db_dependency
from app.ingestion import ALL_ENERGY_TIMESERIES_COLUMNS
from app.main import app
from tests.fakes import FakeConnection


def _summary_row(overrides=None, default=1.0):
    """Build a full aggregate-query result row covering every SUMMARY_NUMERIC_COLUMNS entry."""
    row = {
        "row_count": 10,
        "site_count": 1,
        "start_time": datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc),
        "end_time": datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc),
    }
    for col in SUMMARY_NUMERIC_COLUMNS:
        row[f"{col}_min"] = default
        row[f"{col}_mean"] = default
        row[f"{col}_max"] = default
    if overrides:
        row.update(overrides)
    return row


def _timeseries_row(row_id, dataset_id=1, **overrides):
    row = {"id": row_id, "dataset_id": dataset_id}
    for col in ALL_ENERGY_TIMESERIES_COLUMNS:
        row[col] = None
    row.update(overrides)
    return row


def _override_returning(rows):
    def _fake_dependency():
        yield FakeConnection(rows=rows)

    return _fake_dependency


def _use_override(rows):
    app.dependency_overrides[get_db_dependency] = _override_returning(rows)


def _override_with_responses(responses):
    def _fake_dependency():
        yield FakeConnection(responses=responses)

    return _fake_dependency


def _use_override_responses(responses):
    app.dependency_overrides[get_db_dependency] = _override_with_responses(responses)


def _clear_override():
    app.dependency_overrides.pop(get_db_dependency, None)


def test_get_datasets_returns_200_with_expected_schema():
    rows = [
        {
            "id": 1,
            "name": "demo",
            "file_name": "demo.csv",
            "description": "test dataset",
            "row_count": 24,
            "start_time": datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc),
            "end_time": datetime(2026, 7, 10, 23, 0, tzinfo=timezone.utc),
            "created_at": datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
        }
    ]
    _use_override(rows)
    try:
        response = TestClient(app).get("/datasets")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    item = body[0]
    assert item["id"] == 1
    assert item["name"] == "demo"
    assert item["file_name"] == "demo.csv"
    assert item["description"] == "test dataset"
    assert item["row_count"] == 24
    assert set(item.keys()) == {
        "id",
        "name",
        "file_name",
        "description",
        "row_count",
        "start_time",
        "end_time",
        "created_at",
    }
    # round-trip the serialized datetime back to confirm it is a valid ISO timestamp
    assert datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")) == rows[0]["created_at"]


def test_get_datasets_returns_empty_list_when_no_data():
    _use_override([])
    try:
        response = TestClient(app).get("/datasets")
    finally:
        _clear_override()

    assert response.status_code == 200
    assert response.json() == []


def test_get_dataset_returns_200_with_expected_dataset():
    row = {
        "id": 1,
        "name": "demo",
        "file_name": "demo.csv",
        "description": "test dataset",
        "row_count": 24,
        "start_time": datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc),
        "end_time": datetime(2026, 7, 10, 23, 0, tzinfo=timezone.utc),
        "created_at": datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
    }
    _use_override([row])
    try:
        response = TestClient(app).get("/datasets/1")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert body["name"] == "demo"
    assert body["file_name"] == "demo.csv"


def test_get_dataset_returns_404_when_not_found():
    _use_override([])
    try:
        response = TestClient(app).get("/datasets/999")
    finally:
        _clear_override()

    assert response.status_code == 404
    assert "detail" in response.json()


def test_get_dataset_returns_422_for_non_integer_id():
    # no dependency override needed: FastAPI rejects the path param
    # before our route function (or the DB dependency) ever runs
    response = TestClient(app).get("/datasets/abc")

    assert response.status_code == 422


def test_get_datasets_dependency_override_is_used_not_real_db():
    rows = [
        {
            "id": 99,
            "name": "override-marker",
            "file_name": None,
            "description": None,
            "row_count": None,
            "start_time": None,
            "end_time": None,
            "created_at": None,
        }
    ]
    _use_override(rows)
    try:
        response = TestClient(app).get("/datasets")
    finally:
        _clear_override()

    # if the override were not in effect, this call would hit get_connection()
    # and either fail (no DATABASE_URL / no DB) or return real data, not this marker
    assert response.status_code == 200
    assert response.json()[0]["name"] == "override-marker"


def test_get_dataset_summary_returns_200_with_expected_shape():
    dataset_row = {
        "id": 1,
        "name": "demo",
        "file_name": "demo.csv",
        "description": None,
        "row_count": 10,
        "start_time": None,
        "end_time": None,
        "created_at": None,
    }
    # first execute() call = existence check (get_dataset_by_id), second = aggregate query
    _use_override_responses([[dataset_row], [_summary_row()]])
    try:
        response = TestClient(app).get("/datasets/1/summary")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["dataset_id"] == 1
    assert body["row_count"] == 10
    assert body["site_count"] == 1
    assert set(body["columns"].keys()) == set(SUMMARY_NUMERIC_COLUMNS)
    assert len(body["columns"]) == len(SUMMARY_NUMERIC_COLUMNS)
    sample_col = SUMMARY_NUMERIC_COLUMNS[0]
    assert body["columns"][sample_col] == {"min": 1.0, "mean": 1.0, "max": 1.0}


def test_get_dataset_summary_returns_404_when_dataset_not_found():
    # only the existence check runs; it returns nothing, so the route
    # returns 404 before ever running the aggregate query
    _use_override_responses([[]])
    try:
        response = TestClient(app).get("/datasets/999/summary")
    finally:
        _clear_override()

    assert response.status_code == 404
    assert "detail" in response.json()


def test_get_dataset_summary_all_null_column_serializes_as_json_null_not_nan():
    dataset_row = {
        "id": 1,
        "name": "demo",
        "file_name": "demo.csv",
        "description": None,
        "row_count": 0,
        "start_time": None,
        "end_time": None,
        "created_at": None,
    }
    null_col = SUMMARY_NUMERIC_COLUMNS[0]
    summary_row = _summary_row(
        overrides={
            "row_count": 0,
            "site_count": 0,
            "start_time": None,
            "end_time": None,
            f"{null_col}_min": None,
            f"{null_col}_mean": None,
            f"{null_col}_max": None,
        }
    )
    _use_override_responses([[dataset_row], [summary_row]])
    try:
        response = TestClient(app).get("/datasets/1/summary")
    finally:
        _clear_override()

    assert response.status_code == 200
    assert "NaN" not in response.text
    body = response.json()
    assert body["columns"][null_col] == {"min": None, "mean": None, "max": None}


def _existing_dataset_row(dataset_id=1):
    return {
        "id": dataset_id,
        "name": "demo",
        "file_name": "demo.csv",
        "description": None,
        "row_count": 2,
        "start_time": None,
        "end_time": None,
        "created_at": None,
    }


def test_get_dataset_timeseries_returns_200_with_default_pagination():
    rows = [_timeseries_row(1), _timeseries_row(2)]
    _use_override_responses([[_existing_dataset_row()], [{"total": 2}], rows])
    try:
        response = TestClient(app).get("/datasets/1/timeseries")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["dataset_id"] == 1
    assert body["limit"] == 100
    assert body["offset"] == 0
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert all(item["dataset_id"] == 1 for item in body["items"])


def test_get_dataset_timeseries_respects_custom_limit_and_offset():
    rows = [_timeseries_row(11)]
    _use_override_responses([[_existing_dataset_row()], [{"total": 21}], rows])
    try:
        response = TestClient(app).get("/datasets/1/timeseries?limit=5&offset=10")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 5
    assert body["offset"] == 10
    assert body["total"] == 21
    assert len(body["items"]) == 1


def test_get_dataset_timeseries_returns_404_when_dataset_not_found():
    _use_override_responses([[]])
    try:
        response = TestClient(app).get("/datasets/999/timeseries")
    finally:
        _clear_override()

    assert response.status_code == 404
    assert "detail" in response.json()


def test_get_dataset_timeseries_empty_dataset_returns_total_0_and_empty_items():
    _use_override_responses([[_existing_dataset_row()], [{"total": 0}], []])
    try:
        response = TestClient(app).get("/datasets/1/timeseries")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_get_dataset_timeseries_items_pass_timeseries_row_schema():
    rows = [_timeseries_row(1, pv_forecast_kw=12.5, site_id="site_demo_pv_001")]
    _use_override_responses([[_existing_dataset_row()], [{"total": 1}], rows])
    try:
        response = TestClient(app).get("/datasets/1/timeseries")
    finally:
        _clear_override()

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["id"] == 1
    assert item["dataset_id"] == 1
    assert item["pv_forecast_kw"] == 12.5
    assert item["site_id"] == "site_demo_pv_001"
    assert set(item.keys()) == {"id", "dataset_id"} | set(ALL_ENERGY_TIMESERIES_COLUMNS)


def test_get_dataset_timeseries_limit_zero_returns_422():
    response = TestClient(app).get("/datasets/1/timeseries?limit=0")
    assert response.status_code == 422


def test_get_dataset_timeseries_limit_over_1000_returns_422():
    response = TestClient(app).get("/datasets/1/timeseries?limit=1001")
    assert response.status_code == 422


def test_get_dataset_timeseries_offset_negative_returns_422():
    response = TestClient(app).get("/datasets/1/timeseries?offset=-1")
    assert response.status_code == 422


def test_get_dataset_timeseries_non_integer_limit_returns_422():
    response = TestClient(app).get("/datasets/1/timeseries?limit=abc")
    assert response.status_code == 422
