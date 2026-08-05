"""Step 12 Sub-step 1: unit tests for app/conversations_queries.py.

Uses FakeConversationsConnection (backend/tests/fakes.py) for behavioral
tests (idempotency, attempt numbering, validation) -- but that fake
independently re-implements several critical WHERE clauses (archived
filtering, is_active filtering, the finalize idempotency guard, the stale
filter), so those behavioral tests alone would still pass even if the
corresponding clause were accidentally deleted from the real SQL in
conversations_queries.py. The "SQL shape" section below uses the plain
recording FakeConnection (matching test_case_records_queries.py's
precedent, e.g. test_upsert_sql_uses_on_conflict_case_id) to assert the
actual executed SQL text contains those specific clauses, closing that gap
(Codex final-acceptance review, Medium finding #1).

The concurrency guarantee itself (SELECT ... FOR UPDATE actually
serializing two real callers) is NOT provable with any fake connection --
see test_conversations_queries_integration.py for the real-Postgres test
that covers that specifically.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

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
from tests.fakes import FakeConnection, FakeConversationsConnection

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SQL_PATH = REPO_ROOT / "database" / "schema.sql"


def test_create_conversation_returns_new_id():
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn, role_mode="engineer")
    assert conversation_id == 1


def test_list_conversations_excludes_archived():
    conn = FakeConversationsConnection()
    a = create_conversation(conn)
    b = create_conversation(conn)
    archive_conversation(conn, a)

    total, items = list_conversations(conn, limit=10, offset=0)
    assert total == 1
    assert [c["id"] for c in items] == [b]


def test_list_conversations_respects_limit_and_offset():
    conn = FakeConversationsConnection()
    for _ in range(5):
        create_conversation(conn)

    total, items = list_conversations(conn, limit=2, offset=0)
    assert total == 5
    assert len(items) == 2

    total, items = list_conversations(conn, limit=2, offset=4)
    assert total == 5
    assert len(items) == 1


def test_get_conversation_with_active_messages_returns_none_when_absent():
    conn = FakeConversationsConnection()
    assert get_conversation_with_active_messages(conn, 999) is None


def test_get_conversation_with_active_messages_returns_none_when_archived():
    """Archived conversations are treated as not-found by this function --
    every caller (GET /conversations/{id}, GET .../messages, POST
    .../messages, POST .../regenerate) inherits this without needing its
    own archived_at check."""
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    archive_conversation(conn, conversation_id)

    assert get_conversation_with_active_messages(conn, conversation_id) is None


def test_get_conversation_with_active_messages_only_returns_active_rows():
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    user_message_id = insert_user_message(conn, conversation_id, "hello")
    first_attempt_id = create_streaming_assistant_placeholder(conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini")
    # must be finalized before regenerating -- create_regenerate_attempt now
    # rejects regenerating over a still-streaming active attempt (Sub-step 3C)
    finalize_assistant_message(conn, first_attempt_id, "answer", "completed", None, "stop", None)
    regenerated_id = create_regenerate_attempt(conn, conversation_id, user_message_id, "openai", "gpt-4o-mini")

    result = get_conversation_with_active_messages(conn, conversation_id)
    assert result["conversation"]["id"] == conversation_id
    message_ids = [m["id"] for m in result["messages"]]
    assert user_message_id in message_ids
    assert regenerated_id in message_ids
    # the first (now-superseded) assistant attempt must not appear
    assert len(message_ids) == 2


def test_update_conversation_only_overwrites_supplied_fields():
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn, role_mode="operator")

    update_conversation(conn, conversation_id, title="My chat")
    row = get_conversation_with_active_messages(conn, conversation_id)["conversation"]
    assert row["title"] == "My chat"
    assert row["role_mode"] == "operator"  # untouched

    update_conversation(conn, conversation_id, role_mode="executive")
    row = get_conversation_with_active_messages(conn, conversation_id)["conversation"]
    assert row["title"] == "My chat"  # still untouched
    assert row["role_mode"] == "executive"


def test_update_conversation_returns_none_when_archived():
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn, role_mode="operator")
    archive_conversation(conn, conversation_id)

    result = update_conversation(conn, conversation_id, title="sneaky rename")

    assert result is None
    assert conn.conversations_by_id[conversation_id]["title"] is None
    assert conn.conversations_by_id[conversation_id]["role_mode"] == "operator"


def test_update_conversation_returns_none_when_absent():
    conn = FakeConversationsConnection()
    assert update_conversation(conn, 999, title="x") is None


def test_archive_conversation_returns_zero_when_already_archived():
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    assert archive_conversation(conn, conversation_id) == 1
    assert archive_conversation(conn, conversation_id) == 0


# ---------------------------------------------------------------------------
# insert_user_message: conditional title generation
# ---------------------------------------------------------------------------


def test_insert_user_message_sets_title_on_first_message():
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)

    insert_user_message(conn, conversation_id, "How is my battery doing today?")

    row = get_conversation_with_active_messages(conn, conversation_id)["conversation"]
    assert row["title"] == "How is my battery doing today?"[:40]


def test_insert_user_message_does_not_overwrite_existing_title():
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    insert_user_message(conn, conversation_id, "first message")
    insert_user_message(conn, conversation_id, "second message, much longer than the first")

    row = get_conversation_with_active_messages(conn, conversation_id)["conversation"]
    assert row["title"] == "first message"


def test_insert_user_message_truncates_title_to_40_chars():
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    long_message = "x" * 100

    insert_user_message(conn, conversation_id, long_message)

    row = get_conversation_with_active_messages(conn, conversation_id)["conversation"]
    assert row["title"] == "x" * 40


# ---------------------------------------------------------------------------
# finalize_assistant_message: idempotency
# ---------------------------------------------------------------------------


def test_finalize_assistant_message_transitions_from_streaming():
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    user_message_id = insert_user_message(conn, conversation_id, "hi")
    message_id = create_streaming_assistant_placeholder(
        conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini"
    )

    rows_affected = finalize_assistant_message(
        conn, message_id, content="final answer", status="completed",
        error_message=None, finish_reason="stop", usage={"total_tokens": 42},
    )
    assert rows_affected == 1

    row = conn.messages_by_id[message_id]
    assert row["status"] == "completed"
    assert row["content"] == "final answer"
    assert row["completed_at"] is not None


def test_finalize_assistant_message_is_a_no_op_when_already_finalized():
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    user_message_id = insert_user_message(conn, conversation_id, "hi")
    message_id = create_streaming_assistant_placeholder(
        conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini"
    )
    finalize_assistant_message(
        conn, message_id, content="first", status="completed",
        error_message=None, finish_reason="stop", usage=None,
    )

    rows_affected = finalize_assistant_message(
        conn, message_id, content="should not apply", status="failed",
        error_message="ignored", finish_reason=None, usage=None,
    )
    assert rows_affected == 0
    # original completed content must be untouched
    assert conn.messages_by_id[message_id]["content"] == "first"
    assert conn.messages_by_id[message_id]["status"] == "completed"


# ---------------------------------------------------------------------------
# create_regenerate_attempt: validation, attempt numbering, is_active
# ---------------------------------------------------------------------------


def test_create_regenerate_attempt_raises_when_parent_not_found():
    conn = FakeConversationsConnection()
    with pytest.raises(ParentMessageNotFound):
        create_regenerate_attempt(conn, conversation_id=1, parent_user_message_id=999, provider=None, model=None)


def test_create_regenerate_attempt_raises_when_parent_is_not_a_user_message():
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    user_message_id = insert_user_message(conn, conversation_id, "hi")
    assistant_message_id = create_streaming_assistant_placeholder(
        conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini"
    )

    with pytest.raises(InvalidRegenerateTarget):
        create_regenerate_attempt(conn, conversation_id, assistant_message_id, provider=None, model=None)


def test_create_regenerate_attempt_raises_when_conversation_mismatch():
    conn = FakeConversationsConnection()
    conversation_a = create_conversation(conn)
    conversation_b = create_conversation(conn)
    user_message_id = insert_user_message(conn, conversation_a, "hi")

    with pytest.raises(ConversationMismatch):
        create_regenerate_attempt(conn, conversation_b, user_message_id, provider=None, model=None)


def test_create_regenerate_attempt_increments_attempt_number_and_swaps_active():
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    user_message_id = insert_user_message(conn, conversation_id, "hi")
    first_attempt_id = create_streaming_assistant_placeholder(
        conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini"
    )
    # must be finalized before regenerating (Sub-step 3C in-flight guard)
    finalize_assistant_message(conn, first_attempt_id, "answer", "completed", None, "stop", None)

    second_attempt_id = create_regenerate_attempt(conn, conversation_id, user_message_id, "openai", "gpt-4o-mini")

    assert conn.messages_by_id[first_attempt_id]["is_active"] is False
    assert conn.messages_by_id[second_attempt_id]["is_active"] is True
    assert conn.messages_by_id[second_attempt_id]["attempt_number"] == 2
    assert conn.messages_by_id[second_attempt_id]["regenerated_from_message_id"] == first_attempt_id


def test_create_regenerate_attempt_handles_no_prior_active_attempt():
    # Edge case from docs/step12_substep1_plan.md section 2 step 4: every
    # prior attempt failed before ever being marked active is not modeled
    # here (is_active is always true on insert in this fake), but a
    # regenerate call when there simply is no active row yet must still
    # work and set regenerated_from_message_id to None.
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    user_message_id = insert_user_message(conn, conversation_id, "hi")
    first_attempt_id = create_streaming_assistant_placeholder(
        conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini"
    )
    conn.messages_by_id[first_attempt_id]["is_active"] = False

    new_id = create_regenerate_attempt(conn, conversation_id, user_message_id, "openai", "gpt-4o-mini")

    assert conn.messages_by_id[new_id]["regenerated_from_message_id"] is None
    assert conn.messages_by_id[new_id]["attempt_number"] == 2


def test_multiple_regenerates_keep_incrementing_attempt_number():
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    user_message_id = insert_user_message(conn, conversation_id, "hi")
    first_id = create_streaming_assistant_placeholder(conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini")
    # each attempt must be finalized before the next regenerate call
    # (Sub-step 3C in-flight guard rejects regenerating over 'streaming')
    finalize_assistant_message(conn, first_id, "answer 1", "completed", None, "stop", None)

    second_id = create_regenerate_attempt(conn, conversation_id, user_message_id, "openai", "gpt-4o-mini")
    finalize_assistant_message(conn, second_id, "answer 2", "completed", None, "stop", None)
    third_id = create_regenerate_attempt(conn, conversation_id, user_message_id, "openai", "gpt-4o-mini")

    assert conn.messages_by_id[second_id]["attempt_number"] == 2
    assert conn.messages_by_id[third_id]["attempt_number"] == 3
    assert conn.messages_by_id[second_id]["is_active"] is False
    assert conn.messages_by_id[third_id]["is_active"] is True


# ---------------------------------------------------------------------------
# record_tool_activity (Step 12 Sub-step 3B)
# ---------------------------------------------------------------------------


def test_record_tool_activity_persists_tool_calls_and_citations():
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    user_message_id = insert_user_message(conn, conversation_id, "hi")
    message_id = create_streaming_assistant_placeholder(
        conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini"
    )
    tool_calls = [{"tool_name": "get_dataset_summary", "arguments": {"dataset_id": 1}, "summary": "ok", "error": False}]
    citations = [{"tool_name": "get_dataset_summary", "summary": "ok"}]

    rowcount = record_tool_activity(conn, message_id, tool_calls, citations)

    assert rowcount == 1
    assert conn.messages_by_id[message_id]["tool_calls"] == tool_calls
    assert conn.messages_by_id[message_id]["citations"] == citations


def test_record_tool_activity_does_not_touch_status_or_content():
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    user_message_id = insert_user_message(conn, conversation_id, "hi")
    message_id = create_streaming_assistant_placeholder(
        conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini"
    )
    finalize_assistant_message(conn, message_id, "final answer", "completed", None, "stop", None)

    record_tool_activity(conn, message_id, [{"tool_name": "x"}], None)

    assert conn.messages_by_id[message_id]["status"] == "completed"
    assert conn.messages_by_id[message_id]["content"] == "final answer"


def test_record_tool_activity_returns_zero_when_message_absent():
    conn = FakeConversationsConnection()

    rowcount = record_tool_activity(conn, 999, [{"tool_name": "x"}], None)

    assert rowcount == 0


# ---------------------------------------------------------------------------
# mark_stale_streaming_messages_as_failed
# ---------------------------------------------------------------------------


def test_mark_stale_streaming_messages_as_failed_only_affects_streaming_rows():
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    user_message_id = insert_user_message(conn, conversation_id, "hi")
    streaming_id = create_streaming_assistant_placeholder(
        conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini"
    )
    completed_id = create_streaming_assistant_placeholder(
        conn, conversation_id, user_message_id, 2, "openai", "gpt-4o-mini"
    )
    finalize_assistant_message(
        conn, completed_id, content="done", status="completed",
        error_message=None, finish_reason="stop", usage=None,
    )

    affected = mark_stale_streaming_messages_as_failed(conn)

    assert affected == 1
    assert conn.messages_by_id[streaming_id]["status"] == "failed"
    assert conn.messages_by_id[streaming_id]["error_message"] == "interrupted by server restart"
    assert conn.messages_by_id[completed_id]["status"] == "completed"  # untouched


# ---------------------------------------------------------------------------
# create_regenerate_attempt in-flight guard (Step 12 Sub-step 3C)
# ---------------------------------------------------------------------------


def test_create_regenerate_attempt_rejects_when_active_attempt_is_streaming():
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    user_message_id = insert_user_message(conn, conversation_id, "hi")
    create_streaming_assistant_placeholder(conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini")
    # never finalized -- still 'streaming'

    with pytest.raises(RegenerateAlreadyInProgress):
        create_regenerate_attempt(conn, conversation_id, user_message_id, "openai", "gpt-4o-mini")


@pytest.mark.parametrize("status", ["completed", "failed", "aborted"])
def test_create_regenerate_attempt_succeeds_for_any_terminal_status(status):
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    user_message_id = insert_user_message(conn, conversation_id, "hi")
    first_id = create_streaming_assistant_placeholder(conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini")
    finalize_assistant_message(conn, first_id, "answer", status, None, "stop", None)

    new_id = create_regenerate_attempt(conn, conversation_id, user_message_id, "openai", "gpt-4o-mini")

    assert conn.messages_by_id[new_id]["attempt_number"] == 2


# ---------------------------------------------------------------------------
# mark_stale_streaming_attempts_for_conversation (Step 12 Sub-step 3C)
# ---------------------------------------------------------------------------


def test_mark_stale_streaming_attempts_marks_old_streaming_row_as_failed():
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    user_message_id = insert_user_message(conn, conversation_id, "hi")
    streaming_id = create_streaming_assistant_placeholder(conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini")
    conn.messages_by_id[streaming_id]["created_at"] = datetime.now(timezone.utc) - timedelta(seconds=600)
    stale_before = datetime.now(timezone.utc) - timedelta(seconds=300)

    affected = mark_stale_streaming_attempts_for_conversation(conn, conversation_id, stale_before)

    assert affected == 1
    row = conn.messages_by_id[streaming_id]
    assert row["status"] == "failed"
    assert row["error_message"] == "stale_streaming"
    assert row["completed_at"] is not None


def test_mark_stale_streaming_attempts_does_not_touch_recent_streaming_row():
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    user_message_id = insert_user_message(conn, conversation_id, "hi")
    streaming_id = create_streaming_assistant_placeholder(conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini")
    # created_at defaults to "just now" -- well within the cutoff window
    stale_before = datetime.now(timezone.utc) - timedelta(seconds=300)

    affected = mark_stale_streaming_attempts_for_conversation(conn, conversation_id, stale_before)

    assert affected == 0
    assert conn.messages_by_id[streaming_id]["status"] == "streaming"


def test_mark_stale_streaming_attempts_does_not_touch_non_streaming_rows():
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    user_message_id = insert_user_message(conn, conversation_id, "hi")
    completed_id = create_streaming_assistant_placeholder(conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini")
    finalize_assistant_message(conn, completed_id, "answer", "completed", None, "stop", None)
    conn.messages_by_id[completed_id]["created_at"] = datetime.now(timezone.utc) - timedelta(seconds=600)
    stale_before = datetime.now(timezone.utc) - timedelta(seconds=300)

    affected = mark_stale_streaming_attempts_for_conversation(conn, conversation_id, stale_before)

    assert affected == 0
    assert conn.messages_by_id[completed_id]["status"] == "completed"


def test_mark_stale_streaming_attempts_does_not_touch_other_conversations():
    conn = FakeConversationsConnection()
    conversation_id_a = create_conversation(conn)
    conversation_id_b = create_conversation(conn)
    user_message_id_b = insert_user_message(conn, conversation_id_b, "hi")
    streaming_id_b = create_streaming_assistant_placeholder(conn, conversation_id_b, user_message_id_b, 1, "openai", "gpt-4o-mini")
    conn.messages_by_id[streaming_id_b]["created_at"] = datetime.now(timezone.utc) - timedelta(seconds=600)
    stale_before = datetime.now(timezone.utc) - timedelta(seconds=300)

    affected = mark_stale_streaming_attempts_for_conversation(conn, conversation_id_a, stale_before)

    assert affected == 0
    assert conn.messages_by_id[streaming_id_b]["status"] == "streaming"


# ---------------------------------------------------------------------------
# SQL shape (recording FakeConnection, not FakeConversationsConnection --
# these assert against the actual executed SQL text so a deleted WHERE
# clause in conversations_queries.py would be caught even though
# FakeConversationsConnection independently re-implements the same
# filtering and would not notice)
# ---------------------------------------------------------------------------


def test_list_conversations_sql_filters_archived():
    conn = FakeConnection(responses=[[{"total": 0}], []])
    list_conversations(conn, limit=10, offset=0)
    statements = [str(statement) for statement, _ in conn.executed]
    assert any("archived_at IS NULL" in sql for sql in statements)


def test_get_conversation_with_active_messages_sql_filters_is_active():
    conversation_row = {
        "id": 1, "title": None, "role_mode": None,
        "created_at": None, "updated_at": None, "archived_at": None,
    }
    conn = FakeConnection(responses=[[conversation_row], []])
    get_conversation_with_active_messages(conn, 1)
    statements = [str(statement) for statement, _ in conn.executed]
    assert any("is_active = true" in sql for sql in statements)


def test_archive_conversation_sql_guards_already_archived():
    conn = FakeConnection(rows=[])
    archive_conversation(conn, 1)
    statement, _ = conn.executed[-1]
    assert "archived_at IS NULL" in str(statement)


def test_finalize_assistant_message_sql_guards_streaming_status():
    # The single most safety-critical clause in this module: without this
    # guard, finalize would overwrite an already-terminal message. This
    # test would fail if `AND status = 'streaming'` were ever deleted from
    # the real UPDATE, even though FakeConversationsConnection's own
    # idempotency check (test_finalize_assistant_message_is_a_no_op_...
    # above) would not notice such a regression on its own.
    conn = FakeConnection(rows=[])
    finalize_assistant_message(
        conn, message_id=1, content="x", status="completed",
        error_message=None, finish_reason=None, usage=None,
    )
    statement, _ = conn.executed[-1]
    sql = str(statement)
    assert "status = 'streaming'" in sql
    assert ":message_id" in sql


def test_create_regenerate_attempt_sql_uses_for_update():
    conn = FakeConnection(
        responses=[
            [{"id": 1, "conversation_id": 1, "role": "user"}],  # lock parent
            [{"id": 5, "status": "completed"}],  # current active attempt (not streaming -- guard passes)
            [{"max_attempt": 1}],  # max attempt_number
            [],  # retire old active attempt
            [{"id": 6}],  # insert new attempt
        ]
    )
    create_regenerate_attempt(conn, conversation_id=1, parent_user_message_id=1, provider=None, model=None)
    statements = [str(statement) for statement, _ in conn.executed]
    assert any("FOR UPDATE" in sql for sql in statements)


def test_mark_stale_streaming_messages_as_failed_sql_filters_streaming():
    conn = FakeConnection(rows=[])
    mark_stale_streaming_messages_as_failed(conn)
    statement, _ = conn.executed[-1]
    assert "WHERE status = 'streaming'" in str(statement)


# ---------------------------------------------------------------------------
# schema.sql source-of-truth checks (Codex final-acceptance review, Medium
# finding #3) -- lightweight text checks against the real schema.sql,
# matching this project's no-ORM/no-migration-framework convention (see
# test_case_records_queries.py::test_schema_sql_declares_case_id_not_null_unique).
# Constraint-rejection behavior and the legacy-row-abort path are covered by
# a real-Postgres test in test_conversations_queries_integration.py instead
# of here, since actually violating them requires a real database.
# ---------------------------------------------------------------------------


def test_schema_sql_declares_all_five_check_constraints():
    schema_text = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    for constraint_name in (
        "conversations_role_mode_check",
        "chat_messages_role_check",
        "chat_messages_status_check",
        "chat_messages_attempt_number_check",
        "chat_messages_role_shape_check",
    ):
        assert constraint_name in schema_text, f"missing {constraint_name}"


def test_schema_sql_declares_both_unique_guarantees():
    schema_text = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    assert "chat_messages_parent_attempt_key" in schema_text
    assert "UNIQUE (parent_user_message_id, attempt_number)" in schema_text
    assert "chat_messages_active_attempt_key" in schema_text
    assert "WHERE is_active" in schema_text


def test_schema_sql_aborts_on_legacy_orphan_rows():
    schema_text = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    assert "RAISE EXCEPTION" in schema_text
    assert "no conversation_id" in schema_text


def test_schema_sql_guards_session_id_removal_by_column_existence():
    # The bug a prior Codex review pass caught: referencing session_id
    # directly on a second migration run (after it's already been dropped)
    # would break re-runnability. This asserts the column-existence guard
    # is still present around that check.
    schema_text = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    assert "column_name = 'session_id'" in schema_text
    assert "DROP COLUMN session_id" in schema_text
