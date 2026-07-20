from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import text

from app.datasets_queries import (
    get_dataset_by_id,
    get_dataset_summary,
    get_dataset_timeseries,
    list_datasets,
)
from app.db import get_connection, get_db_dependency
from app.ingestion import ALL_ENERGY_TIMESERIES_COLUMNS, IngestionError, parse_and_validate_csv
from app.schemas import DatasetSummary, DatasetSummaryStatistics, IngestResult, TimeseriesPage

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/version")
def version():
    return {"version": "0.1.0"}


@app.get("/db-check")
def db_check():
    try:
        with get_connection() as conn:
            conn.execute(text("SELECT 1"))
        return {"database": "connected"}
    except Exception as e:
        return {"database": "error", "detail": str(e)}


@app.get("/datasets", response_model=list[DatasetSummary])
def get_datasets(conn=Depends(get_db_dependency)):
    return list_datasets(conn)


@app.get("/datasets/{dataset_id}", response_model=DatasetSummary)
def get_dataset(dataset_id: int, conn=Depends(get_db_dependency)):
    dataset = get_dataset_by_id(conn, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"dataset {dataset_id} not found")
    return dataset


@app.get("/datasets/{dataset_id}/summary", response_model=DatasetSummaryStatistics)
def get_dataset_summary_endpoint(dataset_id: int, conn=Depends(get_db_dependency)):
    if get_dataset_by_id(conn, dataset_id) is None:
        raise HTTPException(status_code=404, detail=f"dataset {dataset_id} not found")
    stats = get_dataset_summary(conn, dataset_id)
    return {"dataset_id": dataset_id, **stats}


@app.get("/datasets/{dataset_id}/timeseries", response_model=TimeseriesPage)
def get_dataset_timeseries_endpoint(
    dataset_id: int,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    conn=Depends(get_db_dependency),
):
    if get_dataset_by_id(conn, dataset_id) is None:
        raise HTTPException(status_code=404, detail=f"dataset {dataset_id} not found")
    total, rows = get_dataset_timeseries(conn, dataset_id, limit, offset)
    return {"dataset_id": dataset_id, "total": total, "limit": limit, "offset": offset, "items": rows}


@app.post("/datasets/upload", response_model=IngestResult)
async def upload_dataset(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
):
    content = await file.read()

    try:
        rows, warnings = parse_and_validate_csv(content)
    except IngestionError as e:
        return IngestResult(
            dataset_id=None,
            row_count=0,
            inserted_count=0,
            warnings=[{"row": None, "column": None, "issue": str(e), "action": "upload rejected"}],
            status="failed",
        )

    row_count = len(rows)
    timestamps = [row["timestamp"] for row in rows if row["timestamp"] is not None]
    start_time = min(timestamps) if timestamps else None
    end_time = max(timestamps) if timestamps else None

    try:
        with get_connection() as conn:
            with conn.begin():
                result = conn.execute(
                    text(
                        """
                        INSERT INTO datasets (name, file_name, description, row_count, start_time, end_time, created_at)
                        VALUES (:name, :file_name, :description, :row_count, :start_time, :end_time, :created_at)
                        RETURNING id
                        """
                    ),
                    {
                        "name": name or file.filename,
                        "file_name": file.filename,
                        "description": description,
                        "row_count": row_count,
                        "start_time": start_time,
                        "end_time": end_time,
                        "created_at": datetime.now(timezone.utc),
                    },
                )
                dataset_id = result.scalar_one()

                if rows:
                    for row in rows:
                        row["dataset_id"] = dataset_id
                    columns_sql = ", ".join(ALL_ENERGY_TIMESERIES_COLUMNS + ["dataset_id"])
                    placeholders_sql = ", ".join(
                        f":{c}" for c in ALL_ENERGY_TIMESERIES_COLUMNS + ["dataset_id"]
                    )
                    conn.execute(
                        text(f"INSERT INTO energy_timeseries ({columns_sql}) VALUES ({placeholders_sql})"),
                        rows,
                    )
    except Exception as e:
        return IngestResult(
            dataset_id=None,
            row_count=row_count,
            inserted_count=0,
            warnings=[{"row": None, "column": None, "issue": f"database error: {e}", "action": "transaction rolled back"}],
            status="failed",
        )

    status = "success" if not warnings else "success_with_warnings"
    return IngestResult(
        dataset_id=dataset_id,
        row_count=row_count,
        inserted_count=len(rows),
        warnings=warnings,
        status=status,
    )
