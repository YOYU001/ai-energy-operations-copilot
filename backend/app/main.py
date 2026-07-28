import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import text

from app.datasets_queries import (
    get_analysis_run,
    get_dataset_by_id,
    get_dataset_summary,
    get_dataset_timeseries,
    get_dataset_timeseries_for_analysis,
    insert_analysis_run,
    list_datasets,
)
from app.db import get_connection, get_db_dependency
from app.document_chunks_queries import (
    create_processing_document,
    find_supersede_candidate,
    get_document_by_content_hash,
    get_document_by_id,
    list_active_chunks_for_document,
    list_documents,
)
from app.ingestion import ALL_ENERGY_TIMESERIES_COLUMNS, IngestionError, parse_and_validate_csv
from app.schemas import (
    AnalysisRunResponse,
    BatteryDischargeAnalysisResult,
    ChunkSummary,
    DatasetSummary,
    DatasetSummaryStatistics,
    DocumentSummary,
    DocumentUploadResult,
    IngestResult,
    TimeseriesPage,
)
from app.services.embedding_provider import EmbeddingProvider, OpenAIEmbeddingProvider
from app.services.hashing import compute_document_content_hash
from app.services.ingestion_rag import READY_STATUS, ingest_pdf_document
from app.services.rule_engine import (
    ANALYSIS_TYPE,
    RULE_VERSION,
    evaluate_battery_should_discharge_but_did_not,
)

app = FastAPI()

# fail-closed safety cap for rule-engine analysis; not a business rule, just an
# MVP-scale guard against computing a percentile/anomaly scan over an unbounded
# unpaginated query (see get_dataset_timeseries_for_analysis)
MAX_ANALYSIS_ROWS = 50_000

# Step 10 MVP: PDF is the only format with a working parse/chunk/embed
# pipeline (app/services/pdf_parser.py). TXT/MD were mentioned in early Step
# 10 planning but have no parser implementation yet -- rejecting them here
# rather than pretending they're supported is a known, documented gap, not
# an oversight.
SUPPORTED_DOCUMENT_UPLOAD_EXTENSIONS = {".pdf"}


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


def _analysis_run_to_response(run: dict) -> AnalysisRunResponse:
    return AnalysisRunResponse(
        analysis_run_id=run["id"],
        dataset_id=run["dataset_id"],
        analysis_type=run["analysis_type"],
        rule_version=run["rule_version"],
        created_at=run["created_at"],
        result=BatteryDischargeAnalysisResult.model_validate(run["result_json"]),
    )


@app.get("/datasets/{dataset_id}/analysis", response_model=AnalysisRunResponse)
def get_dataset_analysis(dataset_id: int, conn=Depends(get_db_dependency)):
    if get_dataset_by_id(conn, dataset_id) is None:
        raise HTTPException(status_code=404, detail=f"dataset {dataset_id} not found")

    run = get_analysis_run(conn, dataset_id, ANALYSIS_TYPE, RULE_VERSION)
    if run is None:
        raise HTTPException(status_code=404, detail="no analysis run yet for this dataset")
    return _analysis_run_to_response(run)


@app.post("/datasets/{dataset_id}/analysis", response_model=AnalysisRunResponse)
def post_dataset_analysis(dataset_id: int, conn=Depends(get_db_dependency)):
    dataset = get_dataset_by_id(conn, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail=f"dataset {dataset_id} not found")

    existing = get_analysis_run(conn, dataset_id, ANALYSIS_TYPE, RULE_VERSION)
    if existing is not None:
        return _analysis_run_to_response(existing)

    if dataset["row_count"] is not None and dataset["row_count"] > MAX_ANALYSIS_ROWS:
        raise HTTPException(
            status_code=422,
            detail="Dataset contains too many rows for the current MVP analysis limit.",
        )

    rows = get_dataset_timeseries_for_analysis(conn, dataset_id)
    result = evaluate_battery_should_discharge_but_did_not(rows)

    try:
        inserted = insert_analysis_run(
            conn,
            dataset_id=dataset_id,
            analysis_type=ANALYSIS_TYPE,
            rule_version=RULE_VERSION,
            result_json=result.model_dump_json(),
            created_at=datetime.now(timezone.utc),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    if inserted is None:
        # a concurrent request won the ON CONFLICT DO NOTHING race and inserted
        # first; re-read its row so both requests return the same result
        inserted = get_analysis_run(conn, dataset_id, ANALYSIS_TYPE, RULE_VERSION)

    return _analysis_run_to_response(inserted)


def _build_embedding_provider() -> EmbeddingProvider:
    """Factory seam for the background ingestion task: production calls the
    real OpenAI-backed provider; tests monkeypatch this function so
    background tasks never make a real API call."""
    return OpenAIEmbeddingProvider()


def _run_document_ingestion_background(document_id: int, temp_path: str, file_name: str) -> None:
    """Runs outside the request/response cycle -- must not reuse the
    request-scoped DB connection (closed by the time this runs) or the
    original UploadFile (its temp handle is not guaranteed to survive past
    the response), only the plain file path and primitive values captured
    while the request was still open.

    ingest_pdf_document already guarantees that any failure from this point
    onward (parse/OCR/chunk/embed/cutover) marks the document 'failed' and
    commits before re-raising -- this wrapper only needs to make sure that
    re-raised exception doesn't crash the background thread, and that the
    temp file is always cleaned up.
    """
    try:
        with get_connection() as conn:
            try:
                ingest_pdf_document(conn, temp_path, file_name, _build_embedding_provider())
            except Exception:
                pass  # already recorded as documents.status='failed' by ingest_pdf_document
    finally:
        Path(temp_path).unlink(missing_ok=True)


@app.post("/documents/upload", response_model=DocumentUploadResult)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    conn=Depends(get_db_dependency),
):
    original_name = file.filename or ""
    extension = Path(original_name).suffix.lower()
    if extension not in SUPPORTED_DOCUMENT_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=(
                f"unsupported file type '{extension or '(none)'}': this MVP only supports PDF uploads "
                "(TXT/MD ingestion is not implemented yet)"
            ),
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="uploaded file is empty")

    with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp:
        tmp.write(content)
        temp_path = tmp.name

    document_content_hash = compute_document_content_hash(temp_path)
    existing = get_document_by_content_hash(conn, document_content_hash)

    if existing is not None and existing["status"] == READY_STATUS:
        Path(temp_path).unlink(missing_ok=True)  # not needed: nothing further will read it
        return DocumentUploadResult(document_id=existing["id"], file_name=original_name, status="already_ingested")

    if existing is not None:
        document_id = existing["id"]
    else:
        supersedes_document_id = find_supersede_candidate(conn, original_name)
        document_id = create_processing_document(
            conn,
            original_name,
            document_content_hash,
            total_pages=None,
            supersedes_document_id=supersedes_document_id,
            title=original_name,
            file_type=extension.lstrip("."),
            source_type="upload",
        )
        conn.commit()

    background_tasks.add_task(_run_document_ingestion_background, document_id, temp_path, original_name)

    return DocumentUploadResult(document_id=document_id, file_name=original_name, status="processing")


@app.get("/documents", response_model=list[DocumentSummary])
def get_documents(conn=Depends(get_db_dependency)):
    return list_documents(conn)


@app.get("/documents/{document_id}", response_model=DocumentSummary)
def get_document(document_id: int, conn=Depends(get_db_dependency)):
    document = get_document_by_id(conn, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail=f"document {document_id} not found")
    return document


@app.get("/documents/{document_id}/chunks", response_model=list[ChunkSummary])
def get_document_chunks(document_id: int, conn=Depends(get_db_dependency)):
    if get_document_by_id(conn, document_id) is None:
        raise HTTPException(status_code=404, detail=f"document {document_id} not found")
    return list_active_chunks_for_document(conn, document_id)


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
