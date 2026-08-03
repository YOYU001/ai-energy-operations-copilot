import asyncio
import json
import logging
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from app.case_records_queries import get_case_by_case_id
from app.conversations_queries import (
    archive_conversation,
    create_conversation,
    create_streaming_assistant_placeholder,
    finalize_assistant_message,
    get_conversation_with_active_messages,
    insert_user_message,
    list_conversations,
    update_conversation,
)
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
    CaseDetail,
    CasesPage,
    CaseSearchRequest,
    CaseSearchResult,
    CaseSummary,
    ChatMessageSummary,
    ChunkSummary,
    ConversationCreateRequest,
    ConversationDetail,
    ConversationsPage,
    ConversationSummary,
    ConversationUpdateRequest,
    DatasetSummary,
    DatasetSummaryStatistics,
    DocumentSummary,
    DocumentUploadResult,
    IngestResult,
    PostMessageRequest,
    TimeseriesPage,
)
from app.services.case_retrieval import (
    DEFAULT_TOP_K,
    MAX_TOP_K,
    MIN_TOP_K,
    CaseHasNoEmbedding,
    CaseNotFound,
    find_similar_to_case,
    list_case_summaries,
    search_by_text,
)
from app.services.case_similarity import ScoredCase, case_similarity_label
from app.services.chat_provider import (
    ChatDeltaEvent,
    ChatFinishEvent,
    ChatProvider,
    ChatProviderError,
    ChatProviderTimeout,
    OpenAIChatProvider,
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

log = logging.getLogger(__name__)

# fail-closed safety cap for rule-engine analysis; not a business rule, just an
# MVP-scale guard against computing a percentile/anomaly scan over an unbounded
# unpaginated query (see get_dataset_timeseries_for_analysis)
MAX_ANALYSIS_ROWS = 50_000

# Step 12 Sub-step 3A Slice 4 timeout contract (docs/step12_substep3a_plan.md
# section 2): one idle-timeout mechanism covers both "waiting for the first
# token" and "waiting for the next token after N have already arrived";
# OVERALL_GENERATION_TIMEOUT_SECONDS is a separate wall-clock hard cap on the
# whole streaming call. Fixed constants, not env-configurable, matching how
# MAX_ANALYSIS_ROWS above is a hardcoded constant.
IDLE_TOKEN_TIMEOUT_SECONDS = 15
OVERALL_GENERATION_TIMEOUT_SECONDS = 60

# Sanitized, stable DB error_message codes -> public-safe SSE/HTTP wording.
# Three-tier separation (docs/step12_substep3_plan.md section 10): DB stores
# the code on the left, this dict produces the public string, and the raw
# exception detail only ever reaches the server log (log.exception calls in
# generate()), never the DB or the client.
_PUBLIC_ERROR_MESSAGES = {
    "provider_timeout": "assistant response failed, please try again",
    "provider_error": "assistant response failed, please try again",
    "persistence_failed": "assistant response failed, please try again",
}


def _public_error_message(code: Optional[str]) -> str:
    return _PUBLIC_ERROR_MESSAGES.get(code, "assistant response failed, please try again")

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


def _scored_case_to_search_result(s: ScoredCase) -> CaseSearchResult:
    return CaseSearchResult(
        case_id=s.case_id,
        event_type=s.event_type,
        symptoms=s.symptoms,
        tags=s.tags,
        severity=s.severity,
        semantic_score=s.semantic_score,
        event_type_match=s.event_type_match,
        tags_boost=s.tags_boost,
        final_score=s.final_score,
        confidence=s.confidence,
        case_similarity=case_similarity_label(s.semantic_score),
        matches=s.matches,
        differs=s.differs,
    )


@app.get("/cases", response_model=CasesPage)
def get_cases(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    conn=Depends(get_db_dependency),
):
    total, items = list_case_summaries(conn, limit, offset)
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@app.get("/cases/{case_id}", response_model=CaseDetail)
def get_case(case_id: str, conn=Depends(get_db_dependency)):
    case = get_case_by_case_id(conn, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"case {case_id} not found")
    return case


@app.get("/cases/{case_id}/similar", response_model=list[CaseSearchResult])
def get_similar_cases(
    case_id: str,
    top_k: int = Query(DEFAULT_TOP_K, ge=MIN_TOP_K, le=MAX_TOP_K),
    conn=Depends(get_db_dependency),
):
    try:
        scored = find_similar_to_case(conn, case_id, top_k)
    except CaseNotFound:
        raise HTTPException(status_code=404, detail=f"case {case_id} not found")
    except CaseHasNoEmbedding:
        raise HTTPException(
            status_code=422,
            detail="this case has no embedding yet, cannot compute similarity",
        )
    return [_scored_case_to_search_result(s) for s in scored]


@app.post("/cases/search", response_model=list[CaseSearchResult])
def post_case_search(request: CaseSearchRequest, conn=Depends(get_db_dependency)):
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query must not be blank")

    scored = search_by_text(
        conn,
        _build_embedding_provider(),
        query,
        event_type=request.event_type,
        tags=request.tags,
        top_k=request.top_k,
    )
    return [_scored_case_to_search_result(s) for s in scored]


@app.post("/conversations", response_model=ConversationSummary, status_code=201)
def post_conversation(request: ConversationCreateRequest, conn=Depends(get_db_dependency)):
    new_id = create_conversation(conn, role_mode=request.role_mode)
    conn.commit()
    detail = get_conversation_with_active_messages(conn, new_id)
    return detail["conversation"]


@app.get("/conversations", response_model=ConversationsPage)
def get_conversations(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    conn=Depends(get_db_dependency),
):
    total, items = list_conversations(conn, limit, offset)
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@app.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: int, conn=Depends(get_db_dependency)):
    detail = get_conversation_with_active_messages(conn, conversation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"conversation {conversation_id} not found")
    return detail


@app.patch("/conversations/{conversation_id}", response_model=ConversationSummary)
def patch_conversation(
    conversation_id: int,
    request: ConversationUpdateRequest,
    conn=Depends(get_db_dependency),
):
    updated = update_conversation(conn, conversation_id, title=request.title, role_mode=request.role_mode)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"conversation {conversation_id} not found")
    conn.commit()
    return updated


@app.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, conn=Depends(get_db_dependency)):
    rowcount = archive_conversation(conn, conversation_id)
    if rowcount == 0:
        raise HTTPException(status_code=404, detail=f"conversation {conversation_id} not found")
    conn.commit()
    return {"archived": True}


@app.get("/conversations/{conversation_id}/messages", response_model=list[ChatMessageSummary])
def get_conversation_messages(conversation_id: int, conn=Depends(get_db_dependency)):
    """Read model only -- no message-creation endpoint here. Per
    docs/step12_substep3a_plan.md, POST /conversations/{id}/messages'
    approved contract is the future SSE endpoint (Phase A resolves
    ChatProvider before creating the assistant placeholder); this slice
    does not introduce a temporary JSON-returning POST at that path that
    would later have to change shape. Reuses
    get_conversation_with_active_messages exactly as GET /conversations/{id}
    does -- same ordering (created_at, id), same is_active=true filter."""
    detail = get_conversation_with_active_messages(conn, conversation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"conversation {conversation_id} not found")
    return detail["messages"]


def _build_chat_provider() -> ChatProvider:
    """Factory seam matching _build_embedding_provider(): production calls
    the real OpenAI-backed provider; tests monkeypatch this so no real API
    call happens. Resolved once per request (see post_message), before the
    assistant placeholder is created, so its real provider_name/model_name
    can be recorded at creation time -- no network I/O happens in
    OpenAIChatProvider.__init__ itself, so this is safe to call from a
    synchronous Phase A block."""
    return OpenAIChatProvider()


def _sse_frame(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _build_provider_messages(
    prior_messages: list[dict], user_content: str, role_mode: Optional[str]
) -> list[dict]:
    """Maps this conversation's active message history plus the new user
    turn into the list[dict] shape AsyncOpenAI expects. No seven-part
    response structure or tool-calling framing here -- that is Sub-step 3B
    scope (docs/step12_substep3_plan.md section 9); this is intentionally
    the simplest correct mapping for 3A."""
    messages: list[dict] = []
    if role_mode is not None:
        messages.append({"role": "system", "content": f"Respond in {role_mode} mode."})
    for m in prior_messages:
        messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": user_content})
    return messages


def _finalize_with_fallback(
    message_id: int,
    content: str,
    status: str,
    error_message: Optional[str],
    finish_reason: Optional[str],
    usage: Optional[dict],
) -> bool:
    """Phase C. Tries a fresh connection twice before giving up (see
    docs/step12_substep3a_plan.md section 3): the common transient-failure
    case (one blip) self-heals; if both attempts fail, this is a logged,
    documented residual Known Issue (the row stays status='streaming'
    until startup reconciliation or manual intervention -- Sub-step 3C
    scope), not a silently swallowed error. Returns True if the row was
    confirmed finalized (this call or a prior one already did it), False
    if both attempts failed."""
    for attempt in (1, 2):
        try:
            with get_connection() as conn:
                rowcount = finalize_assistant_message(
                    conn, message_id, content, status, error_message, finish_reason, usage
                )
                conn.commit()
            if rowcount == 0:
                # Already finalized by something else (e.g. a race with
                # startup reconciliation) -- not a failure of this call.
                log.info("finalize no-op: message %s already left 'streaming'", message_id)
            return True
        except Exception:
            log.exception("finalize attempt %d failed for message %s", attempt, message_id)
            # attempt 1 failing falls through to a second try with a brand
            # new connection (not a retry on the same broken one);
            # attempt 2 failing falls through to the return False below.
    return False


async def generate(message_id: int, provider: ChatProvider, messages: list[dict], request: Request):
    """Phase B + C. One generator, one finalize call site: every exit from
    the loop below (normal completion, idle/overall timeout, provider
    error, any other exception, or disconnect) assigns status/error_message
    and falls through to the same _finalize_with_fallback call -- no
    branch returns or re-raises past it. See
    docs/step12_slice4_plan.md sections 5 and 8."""
    yield _sse_frame("message_started", {"message_id": message_id, "attempt_number": 1})

    accumulated = ""
    status, error_message, finish_reason, usage = "completed", None, None, None
    start = time.monotonic()
    try:
        stream = provider.stream_chat(messages, tools=None)
        while True:
            if await request.is_disconnected():
                status, error_message = "aborted", None
                break
            try:
                event = await asyncio.wait_for(stream.__anext__(), timeout=IDLE_TOKEN_TIMEOUT_SECONDS)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                raise ChatProviderTimeout("idle timeout waiting for next token")
            if time.monotonic() - start > OVERALL_GENERATION_TIMEOUT_SECONDS:
                raise ChatProviderTimeout("overall generation timeout")
            if isinstance(event, ChatDeltaEvent):
                accumulated += event.delta
                yield _sse_frame("token", {"delta": event.delta})
            elif isinstance(event, ChatFinishEvent):
                finish_reason, usage = event.finish_reason, event.usage
    except ChatProviderTimeout:
        log.exception("chat provider timed out for message %s", message_id)
        status, error_message = "failed", "provider_timeout"
    except ChatProviderError:
        log.exception("chat provider error for message %s", message_id)
        status, error_message = "failed", "provider_error"
    except Exception:
        # catch-all fail-closed path, per docs/step12_substep3_plan.md section 7
        log.exception("unexpected error in chat generation for message %s", message_id)
        status, error_message = "failed", "provider_error"

    finalized = _finalize_with_fallback(message_id, accumulated, status, error_message, finish_reason, usage)
    if not await request.is_disconnected():
        if status == "completed":
            yield _sse_frame(
                "message_completed",
                {"message_id": message_id, "finish_reason": finish_reason, "usage": usage},
            )
        else:
            yield _sse_frame(
                "message_failed",
                {"message_id": message_id, "error": _public_error_message(error_message)},
            )
    if not finalized:
        log.error("message %s left in a non-terminal DB state after two finalize attempts", message_id)


@app.post("/conversations/{conversation_id}/messages")
async def post_message(conversation_id: int, body: PostMessageRequest, request: Request):
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="content must not be blank")

    with get_connection() as conn:
        detail = get_conversation_with_active_messages(conn, conversation_id)
        if detail is None or detail["conversation"]["archived_at"] is not None:
            raise HTTPException(status_code=404, detail=f"conversation {conversation_id} not found")
        role_mode = detail["conversation"]["role_mode"]
        prior_messages = detail["messages"]

        provider = _build_chat_provider()

        user_message_id = insert_user_message(conn, conversation_id, content)
        assistant_message_id = create_streaming_assistant_placeholder(
            conn, conversation_id, user_message_id,
            attempt_number=1, provider=provider.provider_name, model=provider.model_name,
        )
        conn.commit()
    # connection closed here -- before generate() is ever called.

    provider_messages = _build_provider_messages(prior_messages, content, role_mode)
    return StreamingResponse(
        generate(assistant_message_id, provider, provider_messages, request),
        media_type="text/event-stream",
    )


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
