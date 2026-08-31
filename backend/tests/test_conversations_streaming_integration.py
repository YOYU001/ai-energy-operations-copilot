"""Step 12 Sub-step 3A Slice 4: real dev PostgreSQL integration test.

Fake-connection tests (test_chat_streaming.py, test_conversations_api.py)
prove SQL shape and the generator's branching logic against a single
simulated connection -- they cannot prove that Phase A's connection is
actually returned to the real connection pool before Phase B/C run, or
that Phase C's fresh connection genuinely persists against a real
database. This test exercises the full POST /conversations/{id}/messages
endpoint against the real dev DB (via TestClient, which drains the SSE
generator synchronously within the app process -- no real network
streaming involved) with a fake ChatProvider (no real OpenAI call), then
verifies both properties directly.

Isolation: uses a conversation created specifically for this test and
cleaned up in fixture teardown regardless of outcome, matching the
existing convention in test_conversations_queries_integration.py.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.main as main_module
from app.conversations_queries import create_conversation
from app.db import engine, get_connection
from app.main import app
from app.services.chat_provider import ChatDeltaEvent, ChatFinishEvent

client = TestClient(app)


class _FakeCompletingProvider:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self, on_stream_start=None):
        self._on_stream_start = on_stream_start

    def stream_chat(self, messages, tools=None, tool_choice=None):
        if self._on_stream_start is not None:
            self._on_stream_start()

        async def _gen():
            yield ChatDeltaEvent(delta="integration test answer")
            yield ChatFinishEvent(finish_reason="stop", usage=None)

        return _gen()


@pytest.fixture
def seeded_conversation():
    with get_connection() as conn:
        conversation_id = create_conversation(conn, role_mode=None)
        conn.commit()

    try:
        yield conversation_id
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


def test_phase_a_connection_closed_before_phase_b_starts(monkeypatch, seeded_conversation):
    """Phase A's `with get_connection() as conn:` block must have already
    returned its connection to the pool by the time the provider's
    stream_chat is first invoked (Phase B) -- proven by checking the
    pool's checked-out-connection count at that exact moment, not merely
    asserted by code review."""
    checked_out_during_phase_b = []

    def _record_checkout():
        checked_out_during_phase_b.append(engine.pool.checkedout())

    monkeypatch.setattr(
        main_module, "_build_chat_provider", lambda: _FakeCompletingProvider(on_stream_start=_record_checkout)
    )

    baseline = engine.pool.checkedout()
    response = client.post(
        f"/conversations/{seeded_conversation}/messages", json={"content": "integration test question"}
    )

    assert response.status_code == 200
    # Step 12 Sub-step 3B: stream_chat is called at least once (Phase 1
    # tool-orchestration round) and, since this message has no tool call,
    # a second time (Phase 2 final synthesis, tools=None) -- both calls
    # happen after Phase A's connection already closed.
    assert len(checked_out_during_phase_b) >= 1
    # Phase A's connection must already be back in the pool by the time
    # every one of these provider calls starts -- no net increase over baseline.
    assert all(count <= baseline for count in checked_out_during_phase_b)


def test_phase_c_finalize_persists_against_real_db(monkeypatch, seeded_conversation):
    """Phase C opens its own fresh connection (app.main.get_connection,
    the real one -- not monkeypatched in this test) and its commit must be
    durably visible via a completely separate connection afterward."""
    monkeypatch.setattr(main_module, "_build_chat_provider", lambda: _FakeCompletingProvider())

    # A short conversational-opener message (per
    # app/services/answer_classifier.py's allowlist) so the capability
    # guard doesn't reject _FakeCompletingProvider's zero-tool-call answer
    # -- this test is about Phase C's DB persistence, not capability-guard
    # behavior (covered separately in test_answer_classifier.py).
    response = client.post(
        f"/conversations/{seeded_conversation}/messages", json={"content": "hi, give me a test answer"}
    )
    assert response.status_code == 200

    with get_connection() as verify_conn:
        row = verify_conn.execute(
            text(
                "SELECT status, content, finish_reason FROM chat_messages "
                "WHERE conversation_id = :id AND role = 'assistant'"
            ),
            {"id": seeded_conversation},
        ).mappings().first()

    assert row is not None
    assert row["status"] == "completed"
    assert row["content"] == "integration test answer"
    assert row["finish_reason"] == "stop"

    # the pool has no permanently leaked checked-out connection after the
    # full Phase A -> B -> C cycle completes
    assert engine.pool.checkedout() == 0


def test_regenerate_full_http_cycle_against_real_db(monkeypatch, seeded_conversation):
    """Step 12 Sub-step 3C: end-to-end regenerate through the real HTTP
    route and real DB -- first send, then regenerate. Proves the attempt
    lifecycle (old attempt inactive, new attempt the sole active one,
    attempt_number incremented) and that no row is left in a non-terminal
    'streaming' state after the full cycle, using the real
    create_regenerate_attempt/finalize_assistant_message/Phase A-C wiring,
    not a fake connection."""
    monkeypatch.setattr(main_module, "_build_chat_provider", lambda: _FakeCompletingProvider())

    first_response = client.post(
        f"/conversations/{seeded_conversation}/messages", json={"content": "integration test question"}
    )
    assert first_response.status_code == 200

    with get_connection() as conn:
        user_message_id = conn.execute(
            text("SELECT id FROM chat_messages WHERE conversation_id = :id AND role = 'user'"),
            {"id": seeded_conversation},
        ).mappings().first()["id"]
        first_attempt_id = conn.execute(
            text("SELECT id FROM chat_messages WHERE conversation_id = :id AND role = 'assistant'"),
            {"id": seeded_conversation},
        ).mappings().first()["id"]

    regenerate_response = client.post(
        f"/conversations/{seeded_conversation}/messages/{user_message_id}/regenerate"
    )
    assert regenerate_response.status_code == 200

    with get_connection() as verify_conn:
        rows = verify_conn.execute(
            text(
                "SELECT id, attempt_number, is_active, status FROM chat_messages "
                "WHERE parent_user_message_id = :id ORDER BY attempt_number"
            ),
            {"id": user_message_id},
        ).mappings().all()

    assert [r["attempt_number"] for r in rows] == [1, 2]
    assert rows[0]["id"] == first_attempt_id
    assert rows[0]["is_active"] is False
    assert rows[1]["is_active"] is True
    assert rows[1]["status"] == "completed"

    # no message for this parent is left in a non-terminal 'streaming' state
    assert all(r["status"] != "streaming" for r in rows)
    assert engine.pool.checkedout() == 0
