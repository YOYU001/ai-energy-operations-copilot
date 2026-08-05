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
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.conversations_queries import (
    RegenerateAlreadyInProgress,
    create_conversation,
    create_regenerate_attempt,
    create_streaming_assistant_placeholder,
    finalize_assistant_message,
    insert_user_message,
    mark_stale_streaming_attempts_for_conversation,
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
    it. Cleans up afterwards regardless of test outcome.

    The seeded first attempt is finalized to 'completed' before yielding
    (Step 12 Sub-step 3C fixture fix): create_regenerate_attempt now
    rejects regenerating over a still-'streaming' active attempt (the
    in-flight guard, docs/step12_substep3c_plan.md section 6). This
    fixture's actual purpose -- proving FOR UPDATE serializes two
    concurrent regenerate calls against a *normal* parent -- was never
    about regenerating while the original send is still streaming; no
    real UI would offer a "regenerate" action during that window anyway,
    so a completed precondition is the realistic case, not a workaround."""
    conversation_id = create_conversation(setup_conn, role_mode=None)
    user_message_id = insert_user_message(setup_conn, conversation_id, "integration test concurrency message")
    first_attempt_id = create_streaming_assistant_placeholder(
        setup_conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini"
    )
    finalize_assistant_message(setup_conn, first_attempt_id, "seeded answer", "completed", None, "stop", None)
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


def test_concurrent_regenerate_calls_serialize_and_second_is_rejected_in_flight(seeded_parent_message):
    """Step 12 Sub-step 3C revision: this test previously asserted BOTH
    concurrent regenerate calls succeed (producing attempts 2 and 3). That
    is no longer correct behavior -- create_regenerate_attempt now rejects
    (RegenerateAlreadyInProgress) a regenerate call made while the current
    active attempt is still 'streaming' (the in-flight guard,
    docs/step12_substep3c_plan.md section 6), and the holder's regenerate
    call always creates its new attempt with status='streaming' (never
    'completed') -- so by the time the waiter's blocked FOR UPDATE
    unblocks, it always sees a still-streaming attempt and must be
    rejected. This test now proves exactly that: the lock still fully
    serializes the two calls (same proof-of-blocking mechanism as before,
    unchanged below), but only ONE of them ends up creating a new attempt;
    the other gets RegenerateAlreadyInProgress, not a second successful
    attempt."""
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

    # Exactly one of the two calls succeeds; the other is rejected as
    # already-in-progress -- neither an unhandled error nor a second
    # successful attempt.
    assert set(results.keys()) | set(errors.keys()) == {"holder", "waiter"}
    assert len(results) == 1, f"expected exactly one success, got results={results} errors={errors}"
    succeeded_thread = next(iter(results))
    rejected_thread = "holder" if succeeded_thread == "waiter" else "waiter"
    assert isinstance(errors[rejected_thread], RegenerateAlreadyInProgress)

    with get_connection() as verify_conn:
        rows = verify_conn.execute(
            text(
                "SELECT id, attempt_number, is_active FROM chat_messages "
                "WHERE parent_user_message_id = :id ORDER BY attempt_number"
            ),
            {"id": user_message_id},
        ).mappings().all()

    # Exactly 2 attempts exist: the seeded (completed) attempt 1, and the
    # one new attempt the succeeding call created -- never a 3rd.
    attempt_numbers = [r["attempt_number"] for r in rows]
    assert attempt_numbers == [1, 2]

    by_id = {r["id"]: r["attempt_number"] for r in rows}
    assert by_id[results[succeeded_thread]] == 2

    active_rows = [r for r in rows if r["is_active"]]
    assert len(active_rows) == 1, "exactly one attempt for this parent must remain active"
    assert active_rows[0]["attempt_number"] == 2
    assert active_rows[0]["id"] == results[succeeded_thread]


def test_stale_cleanup_never_overwrites_a_message_finalized_before_it_runs(seeded_parent_message):
    """Step 12 Sub-step 3C: mark_stale_streaming_attempts_for_conversation's
    WHERE status='streaming' guard must never clobber a message a
    (real, concurrent-in-spirit) finalize already transitioned to a
    terminal status -- proven here against the real DB, not just asserted
    by code review."""
    conversation_id, user_message_id = seeded_parent_message

    with get_connection() as conn:
        second_id = create_regenerate_attempt(conn, conversation_id, user_message_id, "openai", "gpt-4o-mini")
        conn.commit()

    # Simulate: this attempt started long enough ago to be "stale" by the
    # read-time cleanup's cutoff, but a real finalize call reaches it
    # first (matching how a normal request's Phase C would).
    with get_connection() as backdate_conn:
        backdate_conn.execute(
            text("UPDATE chat_messages SET created_at = now() - interval '10 minutes' WHERE id = :id"),
            {"id": second_id},
        )
        backdate_conn.commit()

    with get_connection() as finalize_conn:
        finalize_assistant_message(finalize_conn, second_id, "real answer", "completed", None, "stop", None)
        finalize_conn.commit()

    stale_before = datetime.now(timezone.utc) - timedelta(seconds=300)
    with get_connection() as cleanup_conn:
        affected = mark_stale_streaming_attempts_for_conversation(cleanup_conn, conversation_id, stale_before)
        cleanup_conn.commit()

    assert affected == 0, "cleanup must not match an already-finalized row"
    with get_connection() as verify_conn:
        row = verify_conn.execute(
            text("SELECT status, content FROM chat_messages WHERE id = :id"),
            {"id": second_id},
        ).mappings().first()
    assert row["status"] == "completed"
    assert row["content"] == "real answer"


def test_stale_cleanup_marks_a_genuinely_old_streaming_row_as_failed(seeded_parent_message):
    conversation_id, user_message_id = seeded_parent_message

    with get_connection() as conn:
        second_id = create_regenerate_attempt(conn, conversation_id, user_message_id, "openai", "gpt-4o-mini")
        conn.commit()

    with get_connection() as backdate_conn:
        backdate_conn.execute(
            text("UPDATE chat_messages SET created_at = now() - interval '10 minutes' WHERE id = :id"),
            {"id": second_id},
        )
        backdate_conn.commit()

    stale_before = datetime.now(timezone.utc) - timedelta(seconds=300)
    with get_connection() as cleanup_conn:
        affected = mark_stale_streaming_attempts_for_conversation(cleanup_conn, conversation_id, stale_before)
        cleanup_conn.commit()

    assert affected == 1
    with get_connection() as verify_conn:
        row = verify_conn.execute(
            text("SELECT status, error_message FROM chat_messages WHERE id = :id"),
            {"id": second_id},
        ).mappings().first()
    assert row["status"] == "failed"
    assert row["error_message"] == "stale_streaming"
