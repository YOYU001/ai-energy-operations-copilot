"""Step 12 Sub-step 3C: tests for app.main.lifespan (startup
reconciliation wiring around the already-existing
mark_stale_streaming_messages_as_failed). Fake-connection tests drive the
lifespan context manager directly; one real-Postgres test proves it
against an actual seeded row.
"""

import asyncio

import pytest
from sqlalchemy import text

import app.main as main_module
from app.conversations_queries import create_conversation, create_streaming_assistant_placeholder, insert_user_message
from app.db import get_connection


def run_async(coro):
    return asyncio.run(coro)


class _FakeConnCtx:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        pass


async def _run_lifespan_once():
    async with main_module.lifespan(None):
        pass


def test_lifespan_marks_stale_streaming_as_failed(monkeypatch, caplog):
    monkeypatch.setattr(main_module, "get_connection", lambda: _FakeConnCtx())
    monkeypatch.setattr(main_module, "mark_stale_streaming_messages_as_failed", lambda conn: 3)

    with caplog.at_level("WARNING"):
        run_async(_run_lifespan_once())

    assert any("3 stale streaming" in r.message for r in caplog.records)


def test_lifespan_is_a_noop_when_nothing_streaming(monkeypatch, caplog):
    monkeypatch.setattr(main_module, "get_connection", lambda: _FakeConnCtx())
    monkeypatch.setattr(main_module, "mark_stale_streaming_messages_as_failed", lambda conn: 0)

    with caplog.at_level("WARNING"):
        run_async(_run_lifespan_once())

    assert not any("stale streaming" in r.message for r in caplog.records)


def test_lifespan_db_error_is_logged_and_does_not_prevent_startup(monkeypatch, caplog):
    def _boom(conn):
        raise RuntimeError("simulated db outage")

    monkeypatch.setattr(main_module, "get_connection", lambda: _FakeConnCtx())
    monkeypatch.setattr(main_module, "mark_stale_streaming_messages_as_failed", _boom)

    with caplog.at_level("ERROR"):
        # must not raise -- the app still needs to start
        run_async(_run_lifespan_once())

    assert any(r.levelname == "ERROR" and "startup reconciliation failed" in r.message for r in caplog.records)


def test_lifespan_marks_real_streaming_row_as_failed():
    with get_connection() as conn:
        conversation_id = create_conversation(conn, role_mode=None)
        user_message_id = insert_user_message(conn, conversation_id, "will be interrupted")
        message_id = create_streaming_assistant_placeholder(
            conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini"
        )
        conn.commit()

    try:
        run_async(_run_lifespan_once())

        with get_connection() as verify_conn:
            row = verify_conn.execute(
                text("SELECT status, error_message FROM chat_messages WHERE id = :id"),
                {"id": message_id},
            ).mappings().first()

        assert row["status"] == "failed"
        assert row["error_message"] == "interrupted by server restart"
    finally:
        with get_connection() as cleanup_conn:
            cleanup_conn.execute(text("DELETE FROM chat_messages WHERE conversation_id = :id"), {"id": conversation_id})
            cleanup_conn.execute(text("DELETE FROM conversations WHERE id = :id"), {"id": conversation_id})
            cleanup_conn.commit()
