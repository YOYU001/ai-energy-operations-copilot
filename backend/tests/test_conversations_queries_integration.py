"""Step 12 Sub-step 1: real dev PostgreSQL integration test for
app/conversations_queries.py.

FakeConversationsConnection (test_conversations_queries.py) only proves SQL
shape against a single simulated connection -- it cannot prove that
SELECT ... FOR UPDATE actually serializes two concurrent callers, which is
the entire point of create_regenerate_attempt's locking contract (see
docs/step12_substep1_plan.md section 2). This test opens two real
connections against the dev database and deterministically forces lock
contention between them, rather than merely hoping two threads race
(a bare threading.Barrier before the call does not prove anything: the
"holder" thread could simply finish and commit before the "waiter" thread
starts, in which case the test would pass vacuously even if FOR UPDATE
were accidentally removed -- second-pass Codex review of an earlier draft
of this test).

The "holder" thread takes the parent row's FOR UPDATE lock directly and
sits on it (via an Event) before ever calling create_regenerate_attempt.
The "waiter" thread is only started once the holder confirms it has the
lock. The test then polls pg_locks itself for a real, not-yet-granted
lock request (not a fixed sleep + thread.is_alive() proxy, which can't
distinguish "waiter hasn't reached the DB yet" from "waiter is genuinely
blocked" -- a second Codex review pass caught this) and additionally
checks the waiter thread is still alive with no result -- that is the
actual proof of serialization. Only after that proof does the test
release the holder and let both complete.

Isolation: rows use a conversation created specifically for this test and
cleaned up in fixture teardown regardless of outcome.
"""

import threading
import time

import pytest
from sqlalchemy import text

from app.conversations_queries import (
    create_conversation,
    create_regenerate_attempt,
    create_streaming_assistant_placeholder,
    insert_user_message,
)
from app.db import get_connection


@pytest.fixture
def setup_conn():
    with get_connection() as conn:
        try:
            yield conn
        finally:
            conn.rollback()


@pytest.fixture
def seeded_parent_message(setup_conn):
    """Create a conversation with a user message and its first assistant
    attempt, committed so the two concurrent test connections can both see
    it. Cleans up afterwards regardless of test outcome."""
    conversation_id = create_conversation(setup_conn, role_mode=None)
    user_message_id = insert_user_message(setup_conn, conversation_id, "integration test concurrency message")
    create_streaming_assistant_placeholder(
        setup_conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini"
    )
    setup_conn.commit()

    try:
        yield conversation_id, user_message_id
    finally:
        with get_connection() as cleanup_conn:
            cleanup_conn.execute(
                text("DELETE FROM chat_messages WHERE conversation_id = :id"),
                {"id": conversation_id},
            )
            cleanup_conn.execute(
                text("DELETE FROM conversations WHERE id = :id"),
                {"id": conversation_id},
            )
            cleanup_conn.commit()


def test_concurrent_regenerate_calls_serialize_and_produce_no_duplicate_attempt_numbers(seeded_parent_message):
    conversation_id, user_message_id = seeded_parent_message

    lock_acquired = threading.Event()
    release_lock = threading.Event()
    results = {}
    errors = {}

    def holder():
        try:
            with get_connection() as conn:
                # Take the same row lock create_regenerate_attempt would
                # take, directly, on this connection's open transaction --
                # then sit on it until told to proceed. This is what forces
                # real contention instead of hoping for a race.
                conn.execute(
                    text("SELECT id FROM chat_messages WHERE id = :id FOR UPDATE"),
                    {"id": user_message_id},
                )
                lock_acquired.set()
                # Generous timeout: this is a safety net against the test
                # hanging forever, not a correctness dependency -- release
                # is always signaled explicitly by the main thread below,
                # never relied upon to fire from a race with the polling
                # loop's own (up to ~10s) deadline.
                release_lock.wait(timeout=20)
                new_id = create_regenerate_attempt(conn, conversation_id, user_message_id, "openai", "gpt-4o-mini")
                conn.commit()
                results["holder"] = new_id
        except Exception as exc:  # noqa: BLE001 -- test needs to see whatever actually happened
            errors["holder"] = exc

    def waiter():
        try:
            with get_connection() as conn:
                new_id = create_regenerate_attempt(conn, conversation_id, user_message_id, "openai", "gpt-4o-mini")
                conn.commit()
                results["waiter"] = new_id
        except Exception as exc:  # noqa: BLE001
            errors["waiter"] = exc

    holder_thread = threading.Thread(target=holder)
    holder_thread.start()
    assert lock_acquired.wait(timeout=10), "holder never acquired the lock"

    waiter_thread = threading.Thread(target=waiter)
    waiter_thread.start()

    # The actual proof of serialization: poll pg_locks itself for a real,
    # not-yet-granted lock request on chat_messages -- not a fixed sleep +
    # thread.is_alive() proxy (Codex final-acceptance review, Medium
    # finding #2: a flat sleep can't tell "waiter hasn't reached the DB
    # yet" apart from "waiter is genuinely blocked in Postgres", and a
    # short/fixed timeout on the holder side risks flaky false failures on
    # a slow environment). This asserts, at the database level, that a
    # second request for this row is actually queued behind the holder's
    # lock while the holder still holds it.
    # Row-level FOR UPDATE contention in Postgres shows up in pg_locks as
    # the *waiting* session holding an ungranted lock request of type
    # 'transactionid' (it's waiting for the blocking transaction to finish,
    # not a direct not-granted lock on the relation/tuple itself) -- a
    # not-granted lock on relation='chat_messages' would not appear here.
    with get_connection() as poll_conn:
        deadline = time.monotonic() + 10
        blocked_request_seen = False
        while time.monotonic() < deadline:
            pending = poll_conn.execute(
                text("SELECT count(*) AS n FROM pg_locks WHERE NOT granted AND locktype = 'transactionid'")
            ).mappings().first()["n"]
            if pending > 0:
                blocked_request_seen = True
                break
            time.sleep(0.02)
    assert blocked_request_seen, "waiter's FOR UPDATE request never showed up as a pending (not-granted) transactionid lock in pg_locks"
    assert waiter_thread.is_alive(), "waiter must still be blocked while holder holds the parent-row lock"
    assert "waiter" not in results and "waiter" not in errors, (
        "waiter must not have completed or failed while the holder still holds the lock"
    )

    release_lock.set()
    holder_thread.join(timeout=15)
    waiter_thread.join(timeout=15)

    assert not errors, f"concurrent regenerate calls raised: {errors}"
    assert set(results.keys()) == {"holder", "waiter"}

    with get_connection() as verify_conn:
        rows = verify_conn.execute(
            text(
                "SELECT id, attempt_number, is_active FROM chat_messages "
                "WHERE parent_user_message_id = :id ORDER BY attempt_number"
            ),
            {"id": user_message_id},
        ).mappings().all()

    # Deterministic, not just "happens to be sorted": the holder's commit
    # necessarily lands first (it held the lock the whole time), so its
    # attempt must be 2 and the waiter's (unblocked only afterward) must be 3,
    # on top of the seed fixture's attempt 1.
    attempt_numbers = [r["attempt_number"] for r in rows]
    assert attempt_numbers == [1, 2, 3]

    # Not just "the numbers 1/2/3 exist somewhere" -- explicitly tie each
    # thread's own returned id back to the attempt_number it must have
    # produced, so this would fail if the ordering were ever coincidental
    # rather than actually enforced by the lock.
    by_id = {r["id"]: r["attempt_number"] for r in rows}
    assert by_id[results["holder"]] == 2
    assert by_id[results["waiter"]] == 3

    active_rows = [r for r in rows if r["is_active"]]
    assert len(active_rows) == 1, "exactly one attempt for this parent must remain active"
    assert active_rows[0]["attempt_number"] == 3
    assert active_rows[0]["id"] == results["waiter"]
