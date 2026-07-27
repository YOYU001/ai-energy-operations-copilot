from sqlalchemy import text

from app.ingestion import ALL_ENERGY_TIMESERIES_COLUMNS, NUMERIC_FLOAT_COLUMNS, NUMERIC_INT_COLUMNS

LIST_DATASETS_SQL = text(
    """
    SELECT id, name, file_name, description, row_count, start_time, end_time, created_at
    FROM datasets
    ORDER BY created_at DESC, id DESC
    """
)


def list_datasets(conn):
    """Return every row in datasets, newest first.

    conn must expose the same execute(...).mappings().all() interface as a
    SQLAlchemy Connection (a real one in production, a fake/stub in tests).
    """
    result = conn.execute(LIST_DATASETS_SQL)
    return [dict(row) for row in result.mappings().all()]


GET_DATASET_BY_ID_SQL = text(
    """
    SELECT id, name, file_name, description, row_count, start_time, end_time, created_at
    FROM datasets
    WHERE id = :dataset_id
    """
)


def get_dataset_by_id(conn, dataset_id):
    """Return a single dataset row as a dict, or None if it doesn't exist."""
    result = conn.execute(GET_DATASET_BY_ID_SQL, {"dataset_id": dataset_id})
    row = result.mappings().first()
    return dict(row) if row else None


# single source of truth for "which energy_timeseries columns are numeric":
# reused from ingestion.py so this list can never drift from what Step 4 validates.
SUMMARY_NUMERIC_COLUMNS = NUMERIC_FLOAT_COLUMNS + NUMERIC_INT_COLUMNS


def _build_summary_sql():
    column_exprs = []
    for col in SUMMARY_NUMERIC_COLUMNS:
        column_exprs.append(f"MIN({col}) AS {col}_min")
        column_exprs.append(f"AVG({col}) AS {col}_mean")
        column_exprs.append(f"MAX({col}) AS {col}_max")
    return text(
        f"""
        SELECT
            COUNT(*) AS row_count,
            COUNT(DISTINCT site_id) AS site_count,
            MIN(timestamp) AS start_time,
            MAX(timestamp) AS end_time,
            {", ".join(column_exprs)}
        FROM energy_timeseries
        WHERE dataset_id = :dataset_id
        """
    )


SUMMARY_SQL = _build_summary_sql()


def _to_float_or_none(value):
    return float(value) if value is not None else None


def get_dataset_summary(conn, dataset_id):
    """Return descriptive statistics for a dataset's energy_timeseries rows.

    Assumes the caller has already confirmed the dataset exists; a dataset
    with zero energy_timeseries rows is a valid state (row_count=0, all
    column stats None), not an error.
    """
    row = conn.execute(SUMMARY_SQL, {"dataset_id": dataset_id}).mappings().first()
    columns = {
        col: {
            "min": _to_float_or_none(row[f"{col}_min"]),
            "mean": _to_float_or_none(row[f"{col}_mean"]),
            "max": _to_float_or_none(row[f"{col}_max"]),
        }
        for col in SUMMARY_NUMERIC_COLUMNS
    }
    return {
        "row_count": row["row_count"],
        "site_count": row["site_count"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "columns": columns,
    }


COUNT_TIMESERIES_SQL = text(
    "SELECT COUNT(*) AS total FROM energy_timeseries WHERE dataset_id = :dataset_id"
)

LIST_TIMESERIES_SQL = text(
    f"""
    SELECT id, dataset_id, {", ".join(ALL_ENERGY_TIMESERIES_COLUMNS)}
    FROM energy_timeseries
    WHERE dataset_id = :dataset_id
    ORDER BY timestamp ASC NULLS LAST, id ASC
    LIMIT :limit OFFSET :offset
    """
)


def get_dataset_timeseries(conn, dataset_id, limit, offset):
    """Return (total, items) for a dataset's energy_timeseries rows.

    total counts every row for this dataset regardless of limit/offset;
    items is the current page, ordered by timestamp ASC NULLS LAST, id ASC.
    Assumes the caller has already confirmed the dataset exists.
    """
    total = conn.execute(COUNT_TIMESERIES_SQL, {"dataset_id": dataset_id}).mappings().first()["total"]
    rows = conn.execute(
        LIST_TIMESERIES_SQL,
        {"dataset_id": dataset_id, "limit": limit, "offset": offset},
    ).mappings().all()
    return total, [dict(row) for row in rows]


GET_TIMESERIES_FOR_ANALYSIS_SQL = text(
    """
    SELECT timestamp, electricity_price, grid_import_kw, contract_capacity_kw, battery_soc, battery_power_kw
    FROM energy_timeseries
    WHERE dataset_id = :dataset_id
    ORDER BY timestamp ASC NULLS LAST, id ASC
    """
)


def get_dataset_timeseries_for_analysis(conn, dataset_id):
    """Return every rule-relevant column for one dataset's energy_timeseries rows, unpaginated.

    Unlike get_dataset_timeseries (capped at 1000 rows for dashboard charts),
    rule evaluation needs the full dataset: a partial view would compute a
    wrong price threshold and silently miss anomalies past row 1000. Callers
    must guard against oversized datasets themselves (see MAX_ANALYSIS_ROWS
    in main.py) before calling this — there is no LIMIT here by design.
    """
    rows = conn.execute(GET_TIMESERIES_FOR_ANALYSIS_SQL, {"dataset_id": dataset_id}).mappings().all()
    return [dict(row) for row in rows]


GET_ANALYSIS_RUN_SQL = text(
    """
    SELECT id, dataset_id, analysis_type, rule_version, result_json, created_at
    FROM analysis_runs
    WHERE dataset_id = :dataset_id AND analysis_type = :analysis_type AND rule_version = :rule_version
    """
)


def get_analysis_run(conn, dataset_id, analysis_type, rule_version):
    """Return the stored analysis_runs row for this (dataset_id, analysis_type, rule_version), or None."""
    row = conn.execute(
        GET_ANALYSIS_RUN_SQL,
        {"dataset_id": dataset_id, "analysis_type": analysis_type, "rule_version": rule_version},
    ).mappings().first()
    return dict(row) if row else None


INSERT_ANALYSIS_RUN_SQL = text(
    """
    INSERT INTO analysis_runs (dataset_id, analysis_type, rule_version, result_json, created_at)
    VALUES (:dataset_id, :analysis_type, :rule_version, CAST(:result_json AS JSONB), :created_at)
    ON CONFLICT (dataset_id, analysis_type, rule_version) DO NOTHING
    RETURNING id, dataset_id, analysis_type, rule_version, result_json, created_at
    """
)


def insert_analysis_run(conn, dataset_id, analysis_type, rule_version, result_json, created_at):
    """Insert one analysis_runs row; result_json must already be a JSON string.

    Returns None if a concurrent request already inserted the same
    (dataset_id, analysis_type, rule_version) first (ON CONFLICT DO NOTHING) —
    the caller must re-SELECT via get_analysis_run in that case.
    """
    row = conn.execute(
        INSERT_ANALYSIS_RUN_SQL,
        {
            "dataset_id": dataset_id,
            "analysis_type": analysis_type,
            "rule_version": rule_version,
            "result_json": result_json,
            "created_at": created_at,
        },
    ).mappings().first()
    return dict(row) if row else None
