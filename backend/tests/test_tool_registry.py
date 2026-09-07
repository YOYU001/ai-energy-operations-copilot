"""Step 12 Sub-step 3B: tests for app/services/tool_registry.py.

Happy-path tests reuse FakeConnection (the existing fake used by
test_retrieval.py / test_case_retrieval.py / test_datasets_queries.py) so
these exercise the real query-layer functions, not a mocked return value
-- only the DB and embedding provider are faked.
"""

import pytest

from app.services import tool_registry
from app.services.tool_registry import (
    TOOL_SCHEMAS,
    ToolExecutionError,
    UnknownToolError,
    execute_tool,
    summarize_tool_result,
)
from tests.fakes import FakeConnection


class _FakeEmbeddingProvider:
    def embed_batch(self, texts):
        class _Result:
            def __init__(self):
                self.results = [type("R", (), {"vector": [1.0, 0.0, 0.0]})()]

        return _Result()


# ---------------------------------------------------------------------------
# Registry / dispatch
# ---------------------------------------------------------------------------


def test_tool_schemas_cover_exactly_the_five_approved_tools():
    names = {schema["function"]["name"] for schema in TOOL_SCHEMAS}
    assert names == {
        "get_dataset_summary",
        "get_dataset_timeseries",
        "get_dataset_analysis",
        "search_documents",
        "search_similar_cases",
    }


def test_unknown_tool_name_rejected_before_any_db_call():
    conn = FakeConnection()

    with pytest.raises(UnknownToolError):
        execute_tool(conn, None, "drop_all_tables", {})

    assert conn.executed == []  # no DB call was ever attempted


def test_tool_execution_error_wraps_underlying_exception(monkeypatch):
    def _boom(conn, dataset_id):
        raise RuntimeError("simulated query-layer failure")

    monkeypatch.setattr(tool_registry, "get_dataset_summary", _boom)
    conn = FakeConnection(rows=[{"id": 1}])  # dataset must exist so _require_dataset_exists passes through to _boom

    with pytest.raises(ToolExecutionError) as exc_info:
        execute_tool(conn, None, "get_dataset_summary", {"dataset_id": 1})

    assert isinstance(exc_info.value.__cause__, RuntimeError)


# ---------------------------------------------------------------------------
# _require_dataset_exists (multi-agent failure-mode sweep, TODO.md
# 2026-08-28/31): a nonexistent dataset_id must not silently succeed with
# an all-None/empty-shaped result that the groundedness/evidence guard
# would mistake for real evidence.
# ---------------------------------------------------------------------------


def test_get_dataset_summary_raises_tool_execution_error_for_nonexistent_dataset():
    conn = FakeConnection(rows=[])  # get_dataset_by_id finds nothing

    with pytest.raises(ToolExecutionError) as exc_info:
        execute_tool(conn, None, "get_dataset_summary", {"dataset_id": 999})

    assert isinstance(exc_info.value.__cause__, ValueError)


def test_get_dataset_timeseries_raises_tool_execution_error_for_nonexistent_dataset():
    conn = FakeConnection(rows=[])

    with pytest.raises(ToolExecutionError):
        execute_tool(conn, None, "get_dataset_timeseries", {"dataset_id": 999})


def test_get_dataset_analysis_raises_tool_execution_error_for_nonexistent_dataset():
    conn = FakeConnection(rows=[])

    with pytest.raises(ToolExecutionError):
        execute_tool(conn, None, "get_dataset_analysis", {"dataset_id": 999})


# ---------------------------------------------------------------------------
# get_dataset_summary
# ---------------------------------------------------------------------------


def test_get_dataset_summary_happy_path(monkeypatch):
    monkeypatch.setattr(tool_registry, "get_dataset_summary", lambda conn, dataset_id: {"row_count": 10})
    conn = FakeConnection(rows=[{"id": 12}])

    result = execute_tool(conn, None, "get_dataset_summary", {"dataset_id": 12})

    assert result == {"dataset_id": 12, "summary": {"row_count": 10}}


def test_get_dataset_summary_never_calls_the_embedding_provider_factory(monkeypatch):
    """A non-search tool must never build an embedding provider at all --
    proves the laziness fix (a real OpenAI client construction is wasteful
    and, in some environments, can fail outright for a tool that has
    nothing to do with embeddings)."""
    monkeypatch.setattr(tool_registry, "get_dataset_summary", lambda conn, dataset_id: {"row_count": 10})
    conn = FakeConnection(rows=[{"id": 12}])

    def _boom():
        raise AssertionError("embedding provider factory must not be called for get_dataset_summary")

    execute_tool(conn, _boom, "get_dataset_summary", {"dataset_id": 12})


# ---------------------------------------------------------------------------
# search_documents
# ---------------------------------------------------------------------------


def test_search_documents_happy_path_calls_retrieve_chunks_with_real_scoring():
    row = {
        "chunk_id": "doc1::0001",
        "document_id": 1,
        "chunk_type": "prose",
        "content": "battery discharge behavior",
        "file_name": "manual.pdf",
        "page_index_start": 0,
        "page_index_end": 0,
        "pdf_page_number_start": 5,
        "pdf_page_number_end": 5,
        "printed_page_number_map": {},
        "section_title": "Battery Ops",
        "table_title": None,
        "distance": 0.1,
    }
    conn = FakeConnection(rows=[row])

    result = execute_tool(conn, lambda: _FakeEmbeddingProvider(), "search_documents", {"query_text": "battery discharge"})

    assert len(result["results"]) == 1
    assert result["results"][0]["file_name"] == "manual.pdf"
    assert result["results"][0]["document_id"] == 1
    assert result["results"][0]["pdf_page_number_start"] == 5
    assert "content" in result["results"][0]


# ---------------------------------------------------------------------------
# search_similar_cases
# ---------------------------------------------------------------------------


def test_search_similar_cases_happy_path_calls_search_by_text_with_real_scoring():
    row = {
        "case_id": "case-0001",
        "site_id": "SITE-A",
        "event_time": None,
        "event_type": "BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT",
        "symptoms": "did not discharge",
        "root_cause": "answer-shaped",
        "operator_action": "answer-shaped",
        "resolution_result": "answer-shaped",
        "severity": "high",
        "tags": "peak_shaving",
        "related_dataset_id": None,
        "related_time_range": None,
        "distance": 0.1,
    }
    conn = FakeConnection(rows=[row])

    result = execute_tool(conn, lambda: _FakeEmbeddingProvider(), "search_similar_cases", {"query_text": "battery discharge issue"})

    assert len(result["results"]) == 1
    item = result["results"][0]
    assert item["case_id"] == "case-0001"
    assert "root_cause" not in item  # answer-shaped fields never surfaced to the model
    assert "matches" in item and "differs" in item


def test_search_similar_cases_negative_top_k_is_clamped_to_at_least_one():
    """multi-agent failure-mode sweep, TODO.md 2026-08-28/31: top_k=-1 used
    to flow straight into search_by_text's `scored[:top_k]`, which Python
    silently interprets as "drop the last 1 result" rather than an error --
    with 3 candidates that meant 2 results came back instead of a clamped,
    well-defined count."""
    rows = [
        {
            "case_id": f"case-000{i}",
            "site_id": "SITE-A",
            "event_time": None,
            "event_type": "BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT",
            "symptoms": "did not discharge",
            "root_cause": "answer-shaped",
            "operator_action": "answer-shaped",
            "resolution_result": "answer-shaped",
            "severity": "high",
            "tags": "peak_shaving",
            "related_dataset_id": None,
            "related_time_range": None,
            "distance": 0.1 * i,
        }
        for i in range(1, 4)
    ]
    conn = FakeConnection(rows=rows)

    result = execute_tool(
        conn, lambda: _FakeEmbeddingProvider(), "search_similar_cases", {"query_text": "battery discharge issue", "top_k": -1}
    )

    assert len(result["results"]) == 1  # clamped to 1, not len(candidates) - 1 == 2


# ---------------------------------------------------------------------------
# summarize_tool_result
# ---------------------------------------------------------------------------


def test_summarize_tool_result_is_short_and_non_sensitive():
    summary = summarize_tool_result("search_documents", {"results": [{"content": "sensitive raw excerpt text"}] * 3})
    assert "sensitive raw excerpt text" not in summary
    assert "3" in summary
