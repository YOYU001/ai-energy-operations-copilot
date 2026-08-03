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
            "description": "Get summary statistics (min/mean/max per column) for one energy timeseries dataset.",
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
            "description": "Get raw energy timeseries rows for one dataset (paginated).",
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
            "description": "Search internal uploaded documents (PDF knowledge base) by semantic similarity to a query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_text": {"type": "string"},
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
                    "event_type": {"type": ["string", "null"], "description": "optional exact event_type filter"},
                    "tags": {"type": ["string", "null"], "description": "optional comma-separated tags filter"},
                    "top_k": {"type": "integer", "description": "default 5"},
                },
                "required": ["query_text"],
            },
        },
    },
]


def _tool_get_dataset_summary(conn, args: dict, get_embedding_provider) -> dict:
    dataset_id = args["dataset_id"]
    return {"dataset_id": dataset_id, "summary": get_dataset_summary(conn, dataset_id)}


def _tool_get_dataset_timeseries(conn, args: dict, get_embedding_provider) -> dict:
    dataset_id = args["dataset_id"]
    limit = args.get("limit") or 100
    offset = args.get("offset") or 0
    total, rows = get_dataset_timeseries(conn, dataset_id, limit, offset)
    return {"dataset_id": dataset_id, "total": total, "rows": rows}


def _tool_get_dataset_analysis(conn, args: dict, get_embedding_provider) -> dict:
    dataset_id = args["dataset_id"]
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
    top_k = min(args.get("top_k") or CASE_DEFAULT_TOP_K, CASE_MAX_TOP_K)
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
