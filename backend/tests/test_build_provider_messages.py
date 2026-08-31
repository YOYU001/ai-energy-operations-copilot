"""Tests for app.main._tools_for_turn -- the structural fix (TODO.md,
2026-08-26) for the "表4" (PDF table number) vs dataset_id confusion.

An earlier version of this file tested a natural-language system-prompt
instruction (_PDF_TABLE_FIGURE_INSTRUCTION, injected by
_build_provider_messages) meant to stop the model from calling a dataset
tool for PDF table/figure questions. That instruction was removed after
being superseded by this structural fix: post_message/post_regenerate now
call _tools_for_turn to decide which tools are even offered to the model,
so the wrong ones are physically unselectable rather than merely
discouraged in the prompt."""

import logging

from app.main import CONVERSATION_HISTORY_MAX_MESSAGES, CONVERSATION_HISTORY_MAX_TOTAL_CHARS, _build_provider_messages, _tools_for_turn
from app.services.tool_registry import NON_DATASET_TOOL_SCHEMAS, TOOL_SCHEMAS


def test_pdf_table_reference_returns_the_filtered_tool_list():
    tools = _tools_for_turn("表4中，2024年8月30日這天記錄了幾個超約時段？")
    assert tools is NON_DATASET_TOOL_SCHEMAS
    names = {s["function"]["name"] for s in tools}
    assert names == {"search_documents", "search_similar_cases"}


def test_non_table_question_returns_the_full_tool_list():
    tools = _tools_for_turn("新進人員實習表中，實習人員與導師姓名分別是誰？")
    assert tools is TOOL_SCHEMAS


def test_english_figure_reference_also_triggers_the_filter():
    tools = _tools_for_turn("What does Table 3 say about the inverter rating?")
    assert tools is NON_DATASET_TOOL_SCHEMAS


# ---------------------------------------------------------------------------
# _build_provider_messages windowing/trimming (multi-agent failure-mode
# sweep, TODO.md 2026-08-28/31): both caps used to trim silently, with no
# log signal to explain a later vague answer to a referential follow-up
# question. No test previously exercised either trim path at all.
# ---------------------------------------------------------------------------


def _completed_message(role: str, content: str) -> dict:
    return {"status": "completed", "role": role, "content": content}


def test_no_truncation_warning_when_history_fits_within_both_caps():
    prior = [_completed_message("user", "短訊息")] * 3
    messages = _build_provider_messages(prior, "新的問題", None, conversation_id=42)
    assert len(messages) == 1 + 3 + 1  # system + 3 prior + new user turn


def test_message_count_cap_drops_oldest_and_logs_a_warning(caplog):
    prior = [_completed_message("user", f"訊息{i}") for i in range(CONVERSATION_HISTORY_MAX_MESSAGES + 5)]
    with caplog.at_level(logging.WARNING, logger="app.main"):
        messages = _build_provider_messages(prior, "新的問題", None, conversation_id=42)

    # system + capped history + new user turn
    assert len(messages) == 1 + CONVERSATION_HISTORY_MAX_MESSAGES + 1
    # the oldest messages were dropped, not the newest -- the most recent
    # prior message must still be present right before the new user turn
    assert messages[-2]["content"] == f"訊息{CONVERSATION_HISTORY_MAX_MESSAGES + 4}"
    assert any("dropped" in record.message and "42" in record.message for record in caplog.records)


def test_char_length_cap_drops_oldest_and_logs_a_warning(caplog):
    # 3 messages that individually fit the message-count cap but together
    # exceed the char cap, forcing the oldest-first char-based trim path.
    # Distinct fill characters so the oldest (dropped) and newest (kept)
    # big message can't be confused with each other by content equality.
    oldest_big = "甲" * (CONVERSATION_HISTORY_MAX_TOTAL_CHARS // 2 + 1)
    newest_big = "乙" * (CONVERSATION_HISTORY_MAX_TOTAL_CHARS // 2 + 1)
    prior = [
        _completed_message("user", oldest_big),
        _completed_message("assistant", newest_big),
        _completed_message("user", "小"),
    ]
    with caplog.at_level(logging.WARNING, logger="app.main"):
        messages = _build_provider_messages(prior, "新的問題", None, conversation_id=7)

    contents = [m["content"] for m in messages]
    assert oldest_big not in contents  # dropped by the char cap
    assert newest_big in contents  # kept -- only the oldest offending message is dropped
    assert any("dropped" in record.message and "7" in record.message for record in caplog.records)


def test_no_warning_logged_when_nothing_is_dropped(caplog):
    prior = [_completed_message("user", "小訊息")]
    with caplog.at_level(logging.WARNING, logger="app.main"):
        _build_provider_messages(prior, "新的問題", None, conversation_id=99)

    assert caplog.records == []
