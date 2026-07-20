import math

from app.datasets_queries import (
    SUMMARY_NUMERIC_COLUMNS,
    get_dataset_by_id,
    get_dataset_summary,
    get_dataset_timeseries,
    list_datasets,
)
from app.ingestion import ALL_ENERGY_TIMESERIES_COLUMNS
from app.schemas import TimeseriesRow
from tests.fakes import FakeConnection


def _fake_summary_row(default=2.0, null_columns=()):
    row = {
        "row_count": 10,
        "site_count": 2,
        "start_time": None,
        "end_time": None,
    }
    for col in SUMMARY_NUMERIC_COLUMNS:
        if col in null_columns:
            row[f"{col}_min"] = None
            row[f"{col}_mean"] = None
            row[f"{col}_max"] = None
        else:
            row[f"{col}_min"] = default
            row[f"{col}_mean"] = default
            row[f"{col}_max"] = default
    return row


def test_list_datasets_executes_expected_sql():
    conn = FakeConnection(rows=[])

    list_datasets(conn)

    assert len(conn.executed) == 1
    statement, params = conn.executed[0]
    sql_text = str(statement)
    assert "FROM datasets" in sql_text
    assert "ORDER BY created_at DESC, id DESC" in sql_text


def test_list_datasets_returns_rows_as_dicts():
    rows = [
        {
            "id": 2,
            "name": "b",
            "file_name": "b.csv",
            "description": None,
            "row_count": 10,
            "start_time": None,
            "end_time": None,
            "created_at": None,
        },
        {
            "id": 1,
            "name": "a",
            "file_name": "a.csv",
            "description": None,
            "row_count": 5,
            "start_time": None,
            "end_time": None,
            "created_at": None,
        },
    ]
    conn = FakeConnection(rows=rows)

    result = list_datasets(conn)

    assert result == rows
    assert all(isinstance(row, dict) for row in result)


def test_get_dataset_by_id_executes_expected_sql_with_param():
    conn = FakeConnection(rows=[])

    get_dataset_by_id(conn, 42)

    assert len(conn.executed) == 1
    statement, params = conn.executed[0]
    sql_text = str(statement)
    assert "FROM datasets" in sql_text
    assert "WHERE id = :dataset_id" in sql_text
    assert params == {"dataset_id": 42}


def test_get_dataset_by_id_returns_none_when_not_found():
    conn = FakeConnection(rows=[])

    result = get_dataset_by_id(conn, 999)

    assert result is None


def test_get_dataset_by_id_returns_dict_when_found():
    row = {
        "id": 1,
        "name": "demo",
        "file_name": "demo.csv",
        "description": None,
        "row_count": 5,
        "start_time": None,
        "end_time": None,
        "created_at": None,
    }
    conn = FakeConnection(rows=[row])

    result = get_dataset_by_id(conn, 1)

    assert result == row


def test_get_dataset_summary_executes_expected_sql_covering_all_numeric_columns():
    conn = FakeConnection(rows=[_fake_summary_row()])

    get_dataset_summary(conn, 7)

    assert len(conn.executed) == 1
    statement, params = conn.executed[0]
    sql_text = str(statement)
    assert "FROM energy_timeseries" in sql_text
    assert "WHERE dataset_id = :dataset_id" in sql_text
    assert "COUNT(*) AS row_count" in sql_text
    assert "COUNT(DISTINCT site_id) AS site_count" in sql_text
    assert "MIN(timestamp) AS start_time" in sql_text
    assert "MAX(timestamp) AS end_time" in sql_text
    assert params == {"dataset_id": 7}

    # every SUMMARY_NUMERIC_COLUMNS entry must have min/mean/max expressions;
    # this must hold regardless of how many columns that list actually has.
    for col in SUMMARY_NUMERIC_COLUMNS:
        assert f"MIN({col}) AS {col}_min" in sql_text
        assert f"AVG({col}) AS {col}_mean" in sql_text
        assert f"MAX({col}) AS {col}_max" in sql_text


def test_get_dataset_summary_returns_correct_values_as_float():
    conn = FakeConnection(rows=[_fake_summary_row(default=3.5)])

    result = get_dataset_summary(conn, 1)

    assert result["row_count"] == 10
    assert result["site_count"] == 2
    assert set(result["columns"].keys()) == set(SUMMARY_NUMERIC_COLUMNS)
    for col in SUMMARY_NUMERIC_COLUMNS:
        stats = result["columns"][col]
        assert stats == {"min": 3.5, "mean": 3.5, "max": 3.5}
        assert all(isinstance(v, float) for v in stats.values())


def test_get_dataset_summary_handles_all_null_column_as_none_not_nan():
    null_col = SUMMARY_NUMERIC_COLUMNS[-1]
    conn = FakeConnection(rows=[_fake_summary_row(null_columns=[null_col])])

    result = get_dataset_summary(conn, 1)

    assert result["columns"][null_col] == {"min": None, "mean": None, "max": None}
    # every value in this dataset must be None, never the float NaN
    for stats in result["columns"].values():
        for value in stats.values():
            assert value is None or not math.isnan(value)


def _fake_timeseries_row(row_id, **overrides):
    row = {"id": row_id, "dataset_id": 1}
    for col in ALL_ENERGY_TIMESERIES_COLUMNS:
        row[col] = None
    row.update(overrides)
    return row


def test_get_dataset_timeseries_executes_expected_sql():
    conn = FakeConnection(responses=[[{"total": 0}], []])

    get_dataset_timeseries(conn, 5, limit=50, offset=10)

    assert len(conn.executed) == 2

    count_statement, count_params = conn.executed[0]
    assert "SELECT COUNT(*) AS total" in str(count_statement)
    assert "FROM energy_timeseries WHERE dataset_id = :dataset_id" in str(count_statement)
    assert count_params == {"dataset_id": 5}

    list_statement, list_params = conn.executed[1]
    list_sql = str(list_statement)
    assert "FROM energy_timeseries" in list_sql
    assert "WHERE dataset_id = :dataset_id" in list_sql
    assert "ORDER BY timestamp ASC NULLS LAST, id ASC" in list_sql
    assert "LIMIT :limit OFFSET :offset" in list_sql
    assert list_params == {"dataset_id": 5, "limit": 50, "offset": 10}

    # SELECT must cover every ALL_ENERGY_TIMESERIES_COLUMNS entry, regardless
    # of how many columns that list actually has.
    for col in ALL_ENERGY_TIMESERIES_COLUMNS:
        assert col in list_sql


def test_get_dataset_timeseries_returns_total_and_items():
    rows = [_fake_timeseries_row(1, timestamp=None), _fake_timeseries_row(2, timestamp=None)]
    conn = FakeConnection(responses=[[{"total": 2}], rows])

    total, items = get_dataset_timeseries(conn, 1, limit=100, offset=0)

    assert total == 2
    assert items == rows


def test_get_dataset_timeseries_empty_dataset_returns_zero_and_empty_list():
    conn = FakeConnection(responses=[[{"total": 0}], []])

    total, items = get_dataset_timeseries(conn, 1, limit=100, offset=0)

    assert total == 0
    assert items == []


def test_timeseries_row_schema_matches_all_energy_timeseries_columns():
    schema_fields = set(TimeseriesRow.model_fields.keys()) - {"id", "dataset_id"}
    assert schema_fields == set(ALL_ENERGY_TIMESERIES_COLUMNS)
