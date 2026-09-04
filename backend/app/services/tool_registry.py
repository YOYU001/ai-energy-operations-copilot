"""Step 12 Sub-step 3B: closed tool registry for controlled tool-calling.

Per ADR-002 (docs/DECISIONS.md) and docs/step12_substep3_plan.md section 9:
the LLM never generates SQL. It selects one of exactly 5 pre-approved
tools by name; the backend validates the name against this fixed registry
(unknown names are rejected before any DB call) and dispatches to plain
Python functions that call existing, already-scoped query-layer functions
(datasets_queries.py, rule_engine.py, retrieval.py, case_retrieval.py) --
no new SQL is written here, only wiring.
"""

from __future__ import annotations

from typing import Callable

from app.datasets_queries import (
    get_analysis_run,
    get_dataset_by_id,
    get_dataset_summary,
    get_dataset_timeseries,
    get_dataset_timeseries_for_analysis,
)
from app.services.case_retrieval import DEFAULT_TOP_K as CASE_DEFAULT_TOP_K
from app.services.case_retrieval import MAX_TOP_K as CASE_MAX_TOP_K
from app.services.case_retrieval import search_by_text
from app.services.retrieval import retrieve_chunks
from app.services.rule_engine import ANALYSIS_TYPE, RULE_VERSION, evaluate_battery_should_discharge_but_did_not


class UnknownToolError(Exception):
    """Raised when the model requests a tool name outside the closed
    registry. Callers must reject this before any DB call -- there is no
    fallback that attempts to interpret an unknown tool name as SQL or a
    dynamic query."""


class ToolExecutionError(Exception):
    """Wraps any exception raised by the underlying query-layer function,
    so callers can report a tool-error result back to the model instead of
    treating it as a ChatProviderError (a tool failing is not the same
    class of problem as the LLM API itself failing)."""


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_dataset_summary",
            "description": "Get summary statistics (min/mean/max per column) for one uploaded CSV energy timeseries dataset, identified by its internal numeric dataset_id. Only use this for a dataset that was actually uploaded as a CSV file. Never use this for a specification, calculation, or finding that is described in writing inside a PDF report (e.g. a battery's estimated usable capacity from a research report) -- that is not a CSV dataset even if the topic sounds similar; use search_documents instead. This dataset_id is also NOT the same thing as a table number printed inside a PDF (e.g. '表4', '表3').",
            "parameters": {
                "type": "object",
                "properties": {"dataset_id": {"type": "integer"}},
                "required": ["dataset_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dataset_timeseries",
            "description": "Get raw energy timeseries rows for one uploaded CSV dataset (paginated), identified by its internal numeric dataset_id. Only use this for a dataset that was actually uploaded as a CSV file. Never use this for a specification, calculation, or finding that is described in writing inside a PDF report -- that is not a CSV dataset even if the topic sounds similar; use search_documents instead. This dataset_id is also NOT the same thing as a table number printed inside a PDF (e.g. '表4', '表3').",
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "integer"},
                    "limit": {"type": "integer", "description": "max rows, default 100"},
                    "offset": {"type": "integer", "description": "default 0"},
                },
                "required": ["dataset_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dataset_analysis",
            "description": "Get the rule-based anomaly diagnosis result (BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT) for one dataset.",
            "parameters": {
                "type": "object",
                "properties": {"dataset_id": {"type": "integer"}},
                "required": ["dataset_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Search internal uploaded documents (PDF knowledge base: research reports, technical specifications, calculations, tables, figures) by semantic similarity to a query. Use this for ANY question about content described in writing inside an internal PDF report -- specifications, estimated/calculated values, findings, methodology -- not only explicit table/figure/page references (e.g. '表4', '圖2', '第37頁'), though those always belong here too. A table/figure number inside a PDF is never a dataset_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_text": {
                        "type": "string",
                        "description": (
                            "A natural-language query with enough descriptive context to match well "
                            "against semantic (embedding) search -- NOT a bare number, an isolated ID, or "
                            "a single short keyword alone (e.g. just '1140922' or just '天數'), which tend "
                            "to retrieve poorly since they carry little semantic content. When unsure, "
                            "closely follow the user's own question wording rather than stripping it down "
                            "to isolated keywords."
                        ),
                    },
                    "document_id": {"type": ["integer", "null"], "description": "restrict to one document, optional"},
                    "top_k": {"type": "integer", "description": "default 5"},
                },
                "required": ["query_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_similar_cases",
            "description": "Search internal past case records by semantic similarity to a query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_text": {"type": "string"},
                    "event_type": {
                        "type": ["string", "null"],
                        # "boost", not "filter" (multi-agent failure-mode sweep, TODO.md
                        # 2026-08-28/31): app/services/case_similarity.py never excludes
                        # non-matching candidates on this field, it only adds a small
                        # score boost to the top semantically-nearest candidates that
                        # happen to match. The old wording ("optional exact filter")
                        # described behavior this tool never actually had.
                        "description": (
                            "optional -- boosts the ranking of results whose event_type exactly "
                            "matches this value; does NOT exclude non-matching results, since "
                            "results are still selected by semantic similarity to query_text first"
                        ),
                    },
                    "tags": {
                        "type": ["string", "null"],
                        "description": (
                            "optional comma-separated tags -- boosts the ranking of results whose "
                            "tags overlap with these; does NOT exclude non-matching results, since "
                            "results are still selected by semantic similarity to query_text first"
                        ),
                    },
                    "top_k": {"type": "integer", "description": "default 5"},
                },
                "required": ["query_text"],
            },
        },
    },
]

_DATASET_TOOL_NAMES = {"get_dataset_summary", "get_dataset_timeseries", "get_dataset_analysis"}

# A structural (not prompt-based) fix for the "表4" (PDF table number) vs
# dataset_id confusion (TODO.md, 2026-08-26): rewording tool descriptions and
# injecting an explicit system instruction were both tried first and were
# too weak to reliably stop gpt-4o-mini from calling a dataset tool with a
# guessed dataset_id for PDF table/figure questions. main.py's
# post_message/post_regenerate pass this list instead of TOOL_SCHEMAS for a
# turn where looks_like_pdf_table_or_figure_reference matches, so the model
# is never even offered the dataset tools and cannot select them.
NON_DATASET_TOOL_SCHEMAS: list[dict] = [s for s in TOOL_SCHEMAS if s["function"]["name"] not in _DATASET_TOOL_NAMES]


def _require_dataset_exists(conn, dataset_id: int) -> None:
    """get_dataset_summary/get_dataset_timeseries both explicitly document
    "assumes the caller has already confirmed the dataset exists" -- true
    for main.py's REST endpoints (which call get_dataset_by_id first), but
    the tool-calling path never did (multi-agent failure-mode sweep,
    TODO.md 2026-08-28/31). A nonexistent dataset_id (e.g. one the model
    guessed) doesn't error at the SQL layer -- SUMMARY_SQL is an aggregate
    query that always returns exactly one row, with row_count=0 and every
    stat NULL, indistinguishable in shape from "a real dataset with no
    rows yet". main.py's _tool_result_is_empty only special-cases the
    `results` key (search_documents/search_similar_cases' shape), so that
    all-None dict was always counted as valid evidence, and a diagnostic
    question could never fall through to INSUFFICIENT_DATA_ANSWER even
    though nothing real was ever found. Raising here lets execute_tool's
    existing `except Exception` wrapper turn this into the same
    ToolExecutionError path already used for any other tool failure --
    reported back to the model as a tool error and correctly excluded from
    evidence_results, with no new code path needed in main.py."""
    if get_dataset_by_id(conn, dataset_id) is None:
        raise ValueError(f"dataset_id {dataset_id} does not exist")


def _tool_get_dataset_summary(conn, args: dict, get_embedding_provider) -> dict:
    dataset_id = args["dataset_id"]
    _require_dataset_exists(conn, dataset_id)
    return {"dataset_id": dataset_id, "summary": get_dataset_summary(conn, dataset_id)}


def _tool_get_dataset_timeseries(conn, args: dict, get_embedding_provider) -> dict:
    dataset_id = args["dataset_id"]
    _require_dataset_exists(conn, dataset_id)
    limit = args.get("limit") or 100
    offset = args.get("offset") or 0
    total, rows = get_dataset_timeseries(conn, dataset_id, limit, offset)
    return {"dataset_id": dataset_id, "total": total, "rows": rows}


def _tool_get_dataset_analysis(conn, args: dict, get_embedding_provider) -> dict:
    dataset_id = args["dataset_id"]
    _require_dataset_exists(conn, dataset_id)
    run = get_analysis_run(conn, dataset_id, ANALYSIS_TYPE, RULE_VERSION)
    if run is not None:
        return {"dataset_id": dataset_id, "analysis": run["result_json"], "source": "cached"}
    rows = get_dataset_timeseries_for_analysis(conn, dataset_id)
    result = evaluate_battery_should_discharge_but_did_not(rows)
    return {"dataset_id": dataset_id, "analysis": result.model_dump(), "source": "computed"}


def _tool_search_documents(conn, args: dict, get_embedding_provider) -> dict:
    query_text = args["query_text"]
    document_id = args.get("document_id")
    top_k = args.get("top_k") or 5
    scored = retrieve_chunks(
        conn, query_text, embedding_provider=get_embedding_provider(), document_id=document_id, top_k=top_k
    )
    return {
        "results": [
            {
                "document_id": s.document_id,
                "file_name": s.file_name,
                "chunk_id": s.chunk_id,
                "pdf_page_number_start": s.pdf_page_number_start,
                "pdf_page_number_end": s.pdf_page_number_end,
                "section_title": s.section_title,
                "content": s.content,
            }
            for s in scored
        ]
    }


def _tool_search_similar_cases(conn, args: dict, get_embedding_provider) -> dict:
    query_text = args["query_text"]
    event_type = args.get("event_type")
    tags = args.get("tags")
    # max(1, ...) (multi-agent failure-mode sweep, TODO.md 2026-08-28/31):
    # the schema only declares top_k as {"type": "integer"}, with no
    # minimum, so the model could pass a negative value. Without a lower
    # bound, a negative top_k flowed straight into search_by_text's
    # scored[:top_k] -- Python's negative-slice semantics silently DROP
    # that many results from the end instead of raising or returning an
    # empty list, so the model would receive fewer (or zero) case results
    # with no error to react to.
    top_k = max(1, min(args.get("top_k") or CASE_DEFAULT_TOP_K, CASE_MAX_TOP_K))
    scored = search_by_text(conn, get_embedding_provider(), query_text, event_type=event_type, tags=tags, top_k=top_k)
    return {
        "results": [
            {
                "case_id": s.case_id,
                "event_type": s.event_type,
                "symptoms": s.symptoms,
                "semantic_score": s.semantic_score,
                "confidence": s.confidence,
                "matches": s.matches,
                "differs": s.differs,
            }
            for s in scored
        ]
    }


_TOOL_HANDLERS: dict[str, Callable] = {
    "get_dataset_summary": _tool_get_dataset_summary,
    "get_dataset_timeseries": _tool_get_dataset_timeseries,
    "get_dataset_analysis": _tool_get_dataset_analysis,
    "search_documents": _tool_search_documents,
    "search_similar_cases": _tool_search_similar_cases,
}


def execute_tool(conn, get_embedding_provider, tool_name: str, arguments: dict) -> dict:
    """`get_embedding_provider` is a zero-arg callable (not an
    already-built provider) -- only search_documents/search_similar_cases
    ever call it. This keeps building a real embedding provider (a real
    OpenAI client construction) lazy and skipped entirely for the three
    dataset/analysis tools and for any message that never calls a search
    tool at all."""
    handler = _TOOL_HANDLERS.get(tool_name)
    if handler is None:
        raise UnknownToolError(tool_name)
    try:
        return handler(conn, arguments, get_embedding_provider)
    except Exception as exc:  # noqa: BLE001 -- reported back to the model as a tool error, not raised as a provider failure
        raise ToolExecutionError(f"{tool_name} failed: {exc}") from exc


def summarize_tool_result(tool_name: str, result: dict) -> str:
    """Short, non-sensitive description for the tool_result SSE frame --
    never the raw result dict (docs/step12_substep3_plan.md section 4)."""
    if tool_name == "search_documents":
        return f"found {len(result.get('results', []))} matching document excerpt(s)"
    if tool_name == "search_similar_cases":
        return f"found {len(result.get('results', []))} similar case(s)"
    if tool_name == "get_dataset_summary":
        return f"retrieved summary for dataset {result.get('dataset_id')}"
    if tool_name == "get_dataset_timeseries":
        return f"retrieved {len(result.get('rows', []))} timeseries row(s) for dataset {result.get('dataset_id')}"
    if tool_name == "get_dataset_analysis":
        return f"retrieved analysis for dataset {result.get('dataset_id')}"
    return "tool executed"  # pragma: no cover -- unreachable for the 5 registered tools
