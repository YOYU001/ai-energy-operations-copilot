"""Tests for app.main._known_document_ids / _sanitize_tool_args (TODO.md
"mode 2" finding, 2026-08-28): search_documents has no companion "list
documents" tool, so a document_id the model passes that it never actually
saw in an earlier tool result this turn was guessed, not observed -- a
guessed document_id silently zeroes out the search instead of erroring."""

from app.main import _known_document_ids, _sanitize_tool_args


def _search_documents_evidence(*document_ids: int) -> dict:
    return {
        "tool_name": "search_documents",
        "result": {"results": [{"document_id": doc_id, "content": "..."} for doc_id in document_ids]},
    }


def test_known_document_ids_empty_when_no_prior_search_documents_evidence():
    assert _known_document_ids([]) == set()


def test_known_document_ids_collects_ids_seen_across_multiple_results():
    evidence_results = [_search_documents_evidence(3, 4), _search_documents_evidence(7)]
    assert _known_document_ids(evidence_results) == {3, 4, 7}


def test_known_document_ids_ignores_non_search_documents_evidence():
    evidence_results = [{"tool_name": "get_dataset_summary", "result": {"dataset_id": 12, "summary": {}}}]
    assert _known_document_ids(evidence_results) == set()


def test_sanitize_tool_args_strips_a_never_seen_document_id():
    args = {"query_text": "表4 超約時段", "document_id": 1}
    sanitized = _sanitize_tool_args("search_documents", args, evidence_results=[])
    assert sanitized == {"query_text": "表4 超約時段", "document_id": None}


def test_sanitize_tool_args_keeps_a_document_id_seen_earlier_this_turn():
    evidence_results = [_search_documents_evidence(3)]
    args = {"query_text": "表4 超約時段", "document_id": 3}
    sanitized = _sanitize_tool_args("search_documents", args, evidence_results)
    assert sanitized == {"query_text": "表4 超約時段", "document_id": 3}


def test_sanitize_tool_args_leaves_other_tools_and_missing_document_id_untouched():
    args = {"dataset_id": 12}
    assert _sanitize_tool_args("get_dataset_summary", args, evidence_results=[]) == {"dataset_id": 12}
    args_no_filter = {"query_text": "表4"}
    assert _sanitize_tool_args("search_documents", args_no_filter, evidence_results=[]) == args_no_filter
