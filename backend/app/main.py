import asyncio
import json
import logging
import tempfile
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from app.case_records_queries import get_case_by_case_id
from app.conversations_queries import (
    ConversationMismatch,
    InvalidRegenerateTarget,
    ParentMessageNotFound,
    RegenerateAlreadyInProgress,
    archive_conversation,
    create_conversation,
    create_regenerate_attempt,
    create_streaming_assistant_placeholder,
    finalize_assistant_message,
    get_conversation_with_active_messages,
    insert_user_message,
    list_conversations,
    mark_stale_streaming_attempts_for_conversation,
    mark_stale_streaming_messages_as_failed,
    record_tool_activity,
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
from app.services.answer_classifier import looks_like_diagnostic_question
from app.services.case_similarity import ScoredCase, case_similarity_label
from app.services.chat_provider import (
    ChatDeltaEvent,
    ChatFinishEvent,
    ChatProvider,
    ChatProviderError,
    ChatProviderTimeout,
    ChatToolCallEvent,
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
from app.services.tool_registry import (
    TOOL_SCHEMAS,
    ToolExecutionError,
    UnknownToolError,
    execute_tool,
    summarize_tool_result,
)

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Step 12 Sub-step 3C: one-shot startup reconciliation
    (docs/step12_substep3c_plan.md section 2). Runs exactly once,
    synchronously, before the app accepts requests. Assumption: exactly
    one backend process/worker -- under that assumption every
    status='streaming' row present at boot is necessarily orphaned by a
    prior crash (nothing else could have left a row in that state while
    this process wasn't running yet). Not safe under a multi-worker
    deployment; that remains explicitly out of scope.

    A DB error here must not prevent the app from starting -- crash-
    looping on every boot because reconciliation itself can't reach the
    DB is worse than starting with some rows still 'streaming' from a
    prior crash. Logged at ERROR (not swallowed, not just WARNING)
    because it silently degrades a safety mechanism; the read-time stale
    cleanup (mark_stale_streaming_attempts_for_conversation) is the
    fallback for whatever this pass misses.
    """
    try:
        with get_connection() as conn:
            rowcount = mark_stale_streaming_messages_as_failed(conn)
            conn.commit()
        if rowcount:
            log.warning("startup reconciliation: marked %d stale streaming message(s) as failed", rowcount)
    except Exception:
        log.error(
            "startup reconciliation failed -- app will still start; stale rows rely on read-time cleanup",
            exc_info=True,
        )
    yield


app = FastAPI(lifespan=lifespan)

# Step 12 Sub-step 3C (docs/step12_substep3c_plan.md section 3): read-time
# stale-recovery threshold, comfortably longer than
# OVERALL_GENERATION_TIMEOUT_SECONDS (60s) plus two _finalize_with_fallback
# attempts combined, so a message still 'streaming' past this age is never
# one genuinely still in flight.
STREAMING_STALE_AFTER_SECONDS = 300

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


# Step 12 Sub-step 3B (docs/step12_substep3b_plan.md section 1): closed
# registry + deterministic capability guard is necessary but the guard
# itself lives in generate() (whether zero tool calls were made for a
# diagnostic-classified message); these are the fixed, backend-enforced
# caps on tool-calling that exist independent of what the provider API's
# own limits might be. Fail closed: hitting the cap produces a
# _tool_cap_exceeded_answer(), never a silent truncation.
MAX_TOOL_ROUNDS = 3
MAX_TOOL_CALLS = 5

# Conversation history assembly (docs/step12_substep3b_plan.md section 4):
# message-count cap first, then a total-character cap trims further
# oldest-first. Fixed constants, not user-configurable in this slice.
CONVERSATION_HISTORY_MAX_MESSAGES = 20
CONVERSATION_HISTORY_MAX_TOTAL_CHARS = 8000

# role_mode only changes tone/depth/information density in the system
# prompt -- it must never change tool eligibility, evidence requirements,
# or Internal Knowledge Only enforcement (docs/step12_substep3b_plan.md
# section 3). Reuses the same 4 values already accepted by the DB CHECK
# constraint and the RoleMode Literal in schemas.py; no new mode is added.
ROLE_MODE_FRAMING = {
    "operator": "Prioritize concrete, actionable next steps; minimize jargon; assume no deep EMS/battery engineering background.",
    "engineer": "Full technical detail is expected; use precise terminology (SOC, C-rate, BMS protection logic) without simplification.",
    "executive": "Lead with business/operational impact and risk framing; keep technical detail available but secondary; avoid unexplained jargon.",
    "training": "Explain underlying concepts and reasoning in more depth than an operator/engineer answer would normally include, even at the cost of length -- this mode is explicitly for learning, not fast lookup.",
}

# MVP1_RULES.md section 8 / ADR-006 seven-part structure, expressed as
# fixed Markdown headings (Option A: free-text streaming, not structured
# JSON output -- see docs/step12_substep3b_plan.md section 2). Order
# matters for the system prompt instruction below; _validate_seven_part_structure
# only checks presence, not order, since enforcing order server-side
# without another model round is not worth the complexity for MVP.
SEVEN_PART_HEADINGS = [
    "## Confirmed facts / Finding",
    "## Evidence",
    "## Possible causes",
    "## General engineering background",
    "## Suggested actions / Next checks",
    "## Confidence",
    "## Citations",
]

_SEVEN_PART_INSTRUCTION = (
    "When your answer explains a diagnosis, cites a similar past case, or references "
    "retrieved internal documents, structure your response using exactly these seven "
    "Markdown headings, in this order: "
    + ", ".join(h.lstrip("# ") for h in SEVEN_PART_HEADINGS)
    + ". Confirmed facts and Evidence may only come from tool results returned in this "
    "conversation -- never from your own general knowledge. Possible causes must be "
    "explicitly marked as hypotheses. General engineering background must be kept "
    "separate from Confirmed facts and never presented as a specific fact about this "
    "project. If no tool result supports a claim, say the internal data is insufficient "
    "rather than guessing."
)


def _validate_seven_part_structure(content: str) -> bool:
    return all(heading in content for heading in SEVEN_PART_HEADINGS)


# Deterministic, backend-authored fallback answers (never routed through
# the model) for the two fail-closed paths in generate(): the capability
# guard rejecting a zero-tool-call answer to a diagnostic-classified
# message, and the tool-call round/call cap being reached. Both already
# use the seven-part structure so downstream rendering never has to
# special-case them.
INSUFFICIENT_DATA_ANSWER = (
    "## Confirmed facts / Finding\n"
    "目前內部資料不足，無法針對此問題提供可驗證的結論。\n\n"
    "## Evidence\n"
    "（無：未取得任何內部資料集、文件或案件證據）\n\n"
    "## Possible causes\n"
    "（無法在缺乏證據的情況下列出可能原因）\n\n"
    "## General engineering background\n"
    "（無）\n\n"
    "## Suggested actions / Next checks\n"
    "請提供更具體的資料集 ID、文件名稱或案件編號，以便查詢對應的內部資料。\n\n"
    "## Confidence\n"
    "insufficient data\n\n"
    "## Citations\n"
    "（無）"
)


def _tool_cap_exceeded_answer() -> str:
    return (
        "## Confirmed facts / Finding\n"
        "已達到本次回答可查詢的內部資料工具呼叫上限，以下結論可能不完整。\n\n"
        "## Evidence\n"
        "（部分：僅包含已成功執行的工具查詢結果）\n\n"
        "## Possible causes\n"
        "（可能因證據不完整而未能列出）\n\n"
        "## General engineering background\n"
        "（無）\n\n"
        "## Suggested actions / Next checks\n"
        "建議縮小問題範圍（例如指定單一 dataset 或案件），以便在工具呼叫上限內取得完整證據。\n\n"
        "## Confidence\n"
        "low\n\n"
        "## Citations\n"
        "（部分，請參考已執行的工具呼叫）"
    )

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


def _cleanup_stale_streaming(conn, conversation_id: int) -> None:
    """Explicit, independent call the route makes before reading -- never
    hidden inside get_conversation_with_active_messages, which stays a
    pure read with no side effects (docs/step12_substep3c_plan.md section
    3). Commits immediately: this is self-healing maintenance, not a
    user-facing mutation the caller needs to coordinate with anything
    else in the request."""
    stale_before = datetime.now(timezone.utc) - timedelta(seconds=STREAMING_STALE_AFTER_SECONDS)
    mark_stale_streaming_attempts_for_conversation(conn, conversation_id, stale_before)
    conn.commit()


@app.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: int, conn=Depends(get_db_dependency)):
    _cleanup_stale_streaming(conn, conversation_id)
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
    _cleanup_stale_streaming(conn, conversation_id)
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
    """Maps this conversation's message history plus the new user turn into
    the list[dict] shape AsyncOpenAI expects (docs/step12_substep3b_plan.md
    section 4):
      - only status='completed' messages are included (excludes
        streaming/failed/aborted; superseded regenerate attempts are
        already excluded upstream since prior_messages only ever contains
        is_active=true rows from get_conversation_with_active_messages);
      - capped to the most recent CONVERSATION_HISTORY_MAX_MESSAGES,
        then further trimmed oldest-first if their combined content still
        exceeds CONVERSATION_HISTORY_MAX_TOTAL_CHARS;
      - original chronological order is preserved throughout.
    role_mode only adds tone/depth framing to the system prompt (section 3)
    -- it never changes tool eligibility or evidence requirements, both of
    which are enforced entirely in generate(), independent of this
    function."""
    completed_only = [m for m in prior_messages if m["status"] == "completed"]
    windowed = completed_only[-CONVERSATION_HISTORY_MAX_MESSAGES:]

    total_chars = sum(len(m["content"]) for m in windowed)
    while len(windowed) > 1 and total_chars > CONVERSATION_HISTORY_MAX_TOTAL_CHARS:
        dropped = windowed.pop(0)
        total_chars -= len(dropped["content"])

    system_parts = [_SEVEN_PART_INSTRUCTION]
    if role_mode is not None and role_mode in ROLE_MODE_FRAMING:
        system_parts.append(ROLE_MODE_FRAMING[role_mode])

    messages: list[dict] = [{"role": "system", "content": " ".join(system_parts)}]
    for m in windowed:
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
    tool_calls: Optional[list[dict]] = None,
    citations: Optional[list[dict]] = None,
) -> bool:
    """Phase C. Tries a fresh connection twice before giving up (see
    docs/step12_substep3a_plan.md section 3): the common transient-failure
    case (one blip) self-heals; if both attempts fail, this is a logged,
    documented residual Known Issue (the row stays status='streaming'
    until startup reconciliation or manual intervention -- Sub-step 3C
    scope), not a silently swallowed error. Returns True if the row was
    confirmed finalized (this call or a prior one already did it), False
    if both attempts failed.

    Step 12 Sub-step 3B: also persists tool_calls/citations (if given) via
    record_tool_activity, in the same connection and same fresh-connection
    retry loop as finalize_assistant_message -- not a separate function
    with its own fallback logic, and no change to
    finalize_assistant_message's own signature."""
    for attempt in (1, 2):
        try:
            with get_connection() as conn:
                rowcount = finalize_assistant_message(
                    conn, message_id, content, status, error_message, finish_reason, usage
                )
                if tool_calls is not None or citations is not None:
                    record_tool_activity(conn, message_id, tool_calls, citations)
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


class _StreamAborted(Exception):
    """Internal control-flow signal only (docs/step12_slice4_plan.md's
    disconnect handling, extended to break out of the nested per-round
    loop below) -- never surfaced to callers or the DB."""


async def generate(
    message_id: int,
    provider: ChatProvider,
    messages: list[dict],
    request: Request,
    is_diagnostic: bool,
    build_embedding_provider: Callable[[], EmbeddingProvider],
):
    """Phase B + C. Step 12 Sub-step 3B, revised after review: **two
    strictly separate phases**, not one interleaved loop, to close an
    Internal Knowledge Only gap the first draft had (orchestration-round
    text was streamed live token-by-token before it was known whether that
    text would end up discarded by a tool call, the capability guard, or
    the cap -- meaning the client could see model text the DB never ends
    up persisting, and worse, text that was never actually evidence-backed).

    Phase 1 (orchestration rounds, tools enabled): every round's content
    deltas are buffered locally and NEVER yielded as `token` SSE frames --
    only `tool_call`/`tool_result` frames are ever emitted during this
    phase. A round's buffered text is unconditionally discarded once the
    round ends; it is never the source of the final persisted content.

    Phase 2 (final synthesis, tools disabled): reached only when
    orchestration ends in a genuinely trustworthy state (a round naturally
    stopped without requesting a tool call, and the capability guard does
    not apply). This is the *only* place `token` SSE frames are ever
    emitted from provider output, and `accumulated` here is built
    exclusively from this round's own deltas -- so the exact text streamed
    to the client is always exactly what gets persisted. The two
    backend-authored fallback answers (capability-guard rejection, cap
    exceeded) skip Phase 2 entirely and stream their fixed string directly
    -- also exactly matching what gets persisted, since it's the same
    string in both places by construction.

    Still exactly one finalize call site: every exit path (normal
    completion, cap exceeded, capability-guard rejection, idle/overall
    timeout, provider error, any other exception, or disconnect) assigns
    status/error_message/finish_reason and falls through to the same
    _finalize_with_fallback call. ChatProvider itself never sees SSE --
    all event: tool_call/tool_result/token framing happens here, matching
    the layering already established in Slice 1."""
    yield _sse_frame("message_started", {"message_id": message_id, "attempt_number": 1})

    accumulated = ""
    status, error_message, finish_reason, usage = "completed", None, None, None
    tool_call_log: list[dict] = []
    total_tool_calls = 0
    working_messages = list(messages)
    start = time.monotonic()
    outcome: Optional[str] = None  # "synthesize" | "insufficient_data" | "capped"
    # Lazy: only the two search_* tools ever need an embedding provider,
    # and most messages call neither (this is a real fix, not a
    # micro-optimization -- eagerly building a real OpenAIEmbeddingProvider
    # for every message, even ones that never call a search tool, wastes a
    # client construction and, in this dev environment, actually raised
    # from a broken SSL_CERT_FILE env var before this fix).
    embedding_provider_holder: list[EmbeddingProvider] = []

    def _get_embedding_provider() -> EmbeddingProvider:
        if not embedding_provider_holder:
            embedding_provider_holder.append(build_embedding_provider())
        return embedding_provider_holder[0]

    try:
        # ---------------------------------------------------------------
        # Phase 1: tool orchestration rounds. tools=TOOL_SCHEMAS. Content
        # is buffered per round and never yielded as SSE here.
        # ---------------------------------------------------------------
        for round_num in range(1, MAX_TOOL_ROUNDS + 1):
            round_content = ""
            tool_fragments: dict[int, dict] = {}
            tool_order: list[int] = []
            round_finish_reason: Optional[str] = None
            round_usage: Optional[dict] = None

            stream = provider.stream_chat(working_messages, tools=TOOL_SCHEMAS)
            while True:
                if await request.is_disconnected():
                    raise _StreamAborted()
                try:
                    event = await asyncio.wait_for(stream.__anext__(), timeout=IDLE_TOKEN_TIMEOUT_SECONDS)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    raise ChatProviderTimeout("idle timeout waiting for next token")
                if time.monotonic() - start > OVERALL_GENERATION_TIMEOUT_SECONDS:
                    raise ChatProviderTimeout("overall generation timeout")

                if isinstance(event, ChatDeltaEvent):
                    # buffered ONLY -- this round may still turn into a
                    # tool call or be discarded by the capability guard, so
                    # its text is not yet trustworthy enough to show the
                    # client (Internal Knowledge Only fix).
                    round_content += event.delta
                elif isinstance(event, ChatToolCallEvent):
                    if event.index not in tool_fragments:
                        tool_fragments[event.index] = {"id": None, "name": None, "arguments": ""}
                        tool_order.append(event.index)
                    if event.tool_call_id is not None:
                        tool_fragments[event.index]["id"] = event.tool_call_id
                    if event.name is not None:
                        tool_fragments[event.index]["name"] = event.name
                    tool_fragments[event.index]["arguments"] += event.arguments_delta
                elif isinstance(event, ChatFinishEvent):
                    round_finish_reason, round_usage = event.finish_reason, event.usage

            if round_finish_reason == "tool_calls" and tool_order:
                total_tool_calls += len(tool_order)
                if round_num == MAX_TOOL_ROUNDS or total_tool_calls >= MAX_TOOL_CALLS:
                    # round_content (if any) is discarded here -- never sent, never persisted.
                    outcome = "capped"
                    break

                # round_content (if any -- rare for a tool-calling round) is
                # discarded here too; only the tool call itself carries forward.
                working_messages.append(
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": tool_fragments[idx]["id"],
                                "type": "function",
                                "function": {
                                    "name": tool_fragments[idx]["name"],
                                    "arguments": tool_fragments[idx]["arguments"],
                                },
                            }
                            for idx in tool_order
                        ],
                    }
                )
                for idx in tool_order:
                    name = tool_fragments[idx]["name"]
                    tool_call_id = tool_fragments[idx]["id"]
                    raw_args = tool_fragments[idx]["arguments"]
                    try:
                        args = json.loads(raw_args) if raw_args else {}
                    except ValueError:
                        args = {}
                    yield _sse_frame("tool_call", {"tool_name": name, "arguments": args})
                    try:
                        with get_connection() as tool_conn:
                            result = execute_tool(tool_conn, _get_embedding_provider, name, args)
                        summary = summarize_tool_result(name, result)
                        tool_call_log.append({"tool_name": name, "arguments": args, "summary": summary, "error": False})
                        yield _sse_frame("tool_result", {"tool_name": name, "summary": summary})
                        working_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call_id,
                                "content": json.dumps(jsonable_encoder(result)),
                            }
                        )
                    except UnknownToolError:
                        summary = f"unknown tool: {name}"
                        log.warning("model requested unknown tool: %s", name)
                        tool_call_log.append({"tool_name": name, "arguments": args, "summary": summary, "error": True})
                        yield _sse_frame("tool_result", {"tool_name": name, "summary": summary})
                        working_messages.append(
                            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps({"error": summary})}
                        )
                    except ToolExecutionError:
                        summary = f"{name} failed"
                        log.exception("tool execution failed: %s", name)
                        tool_call_log.append({"tool_name": name, "arguments": args, "summary": summary, "error": True})
                        yield _sse_frame("tool_result", {"tool_name": name, "summary": summary})
                        working_messages.append(
                            {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps({"error": summary})}
                        )
                continue

            # Round ended without requesting a tool call -- round_content is
            # STILL discarded (never streamed); orchestration is over, and
            # the next step decides what actually gets shown/persisted.
            finish_reason, usage = round_finish_reason, round_usage
            if is_diagnostic and not tool_call_log:
                outcome = "insufficient_data"
            else:
                outcome = "synthesize"
            break
        else:
            # exhausted MAX_TOOL_ROUNDS without a terminal round (safety net;
            # the round_num == MAX_TOOL_ROUNDS branch above already covers
            # the expected path to this same outcome)
            outcome = "capped"

        # ---------------------------------------------------------------
        # Phase 2: resolve the outcome. Only "synthesize" ever calls the
        # provider again (with tools=None); the other two outcomes stream
        # a fixed, backend-authored string that is byte-for-byte identical
        # to what gets persisted -- there is no path where the client sees
        # something different from what the DB ends up storing.
        # ---------------------------------------------------------------
        if outcome == "insufficient_data":
            accumulated = INSUFFICIENT_DATA_ANSWER
            finish_reason = "insufficient_data"
            yield _sse_frame("token", {"delta": accumulated})
        elif outcome == "capped":
            accumulated = _tool_cap_exceeded_answer()
            finish_reason = "tool_cap_exceeded"
            yield _sse_frame("token", {"delta": accumulated})
        else:  # "synthesize"
            stream = provider.stream_chat(working_messages, tools=None)
            while True:
                if await request.is_disconnected():
                    raise _StreamAborted()
                try:
                    event = await asyncio.wait_for(stream.__anext__(), timeout=IDLE_TOKEN_TIMEOUT_SECONDS)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    raise ChatProviderTimeout("idle timeout waiting for next token")
                if time.monotonic() - start > OVERALL_GENERATION_TIMEOUT_SECONDS:
                    raise ChatProviderTimeout("overall generation timeout")

                if isinstance(event, ChatDeltaEvent):
                    # the ONLY place provider content is streamed live --
                    # accumulated is built exclusively from this round, so
                    # it always matches exactly what the client received.
                    accumulated += event.delta
                    yield _sse_frame("token", {"delta": event.delta})
                elif isinstance(event, ChatFinishEvent):
                    finish_reason, usage = event.finish_reason, event.usage
                # ChatToolCallEvent is not expected here (tools=None was
                # passed); if a provider somehow still emits one, it is
                # silently ignored -- ignoring is deliberate: tools are
                # disabled for this round by contract, so any such event
                # cannot be trusted as a real, executable tool call.

        if tool_call_log and not _validate_seven_part_structure(accumulated):
            log.warning("message %s: assistant answer missing expected seven-part headings", message_id)
    except _StreamAborted:
        status, error_message = "aborted", None
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

    citations = (
        [{"tool_name": c["tool_name"], "summary": c["summary"]} for c in tool_call_log if not c["error"]]
        if tool_call_log
        else None
    )
    finalized = _finalize_with_fallback(
        message_id, accumulated, status, error_message, finish_reason, usage,
        tool_calls=tool_call_log or None, citations=citations,
    )
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

    is_diagnostic = looks_like_diagnostic_question(content)
    provider_messages = _build_provider_messages(prior_messages, content, role_mode)
    return StreamingResponse(
        generate(assistant_message_id, provider, provider_messages, request, is_diagnostic, _build_embedding_provider),
        media_type="text/event-stream",
    )


@app.post("/conversations/{conversation_id}/messages/{message_id}/regenerate")
async def post_regenerate(conversation_id: int, message_id: int, request: Request):
    """message_id here is the PARENT USER MESSAGE id (matching
    create_regenerate_attempt's own parameter name), not an assistant
    message id -- easy to misread, documented explicitly per
    docs/step12_substep3c_plan.md section 4. No request body: regenerate
    re-asks the same original user turn; it never accepts new text (use
    POST /conversations/{id}/messages for that). Reconnect to an existing
    SSE stream is not supported -- this always creates a brand-new
    assistant attempt; it never resumes or replays a previous attempt's
    token stream (section 8)."""
    with get_connection() as conn:
        detail = get_conversation_with_active_messages(conn, conversation_id)
        if detail is None or detail["conversation"]["archived_at"] is not None:
            raise HTTPException(status_code=404, detail=f"conversation {conversation_id} not found")
        role_mode = detail["conversation"]["role_mode"]

        parent_message = next((m for m in detail["messages"] if m["id"] == message_id), None)

        provider = _build_chat_provider()
        try:
            assistant_message_id = create_regenerate_attempt(
                conn, conversation_id, message_id, provider.provider_name, provider.model_name,
            )
        except ParentMessageNotFound:
            raise HTTPException(status_code=404, detail=f"message {message_id} not found")
        except ConversationMismatch:
            # treated identically to "not found" -- no disclosure that this
            # id belongs to a different conversation
            raise HTTPException(status_code=404, detail=f"message {message_id} not found")
        except InvalidRegenerateTarget:
            raise HTTPException(status_code=400, detail="message is not a regenerable user message")
        except RegenerateAlreadyInProgress:
            raise HTTPException(status_code=409, detail="a response is already being generated for this message")
        conn.commit()

        parent_content = parent_message["content"]
        # detail was fetched before create_regenerate_attempt flipped the
        # previous attempt's is_active to false, so it can still contain
        # that soon-to-be-superseded assistant reply -- exclude it here by
        # parent_user_message_id, not just is_active, or the provider would
        # see an answer that's about to be replaced by this very call.
        prior_messages = [
            m
            for m in detail["messages"]
            if m["id"] != message_id and m.get("parent_user_message_id") != message_id
        ]
    # connection closed here -- before generate() is ever called.

    is_diagnostic = looks_like_diagnostic_question(parent_content)
    provider_messages = _build_provider_messages(prior_messages, parent_content, role_mode)
    return StreamingResponse(
        generate(assistant_message_id, provider, provider_messages, request, is_diagnostic, _build_embedding_provider),
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
