"""Step 12 Sub-step 3C: tests for POST /conversations/{id}/messages/{message_id}/regenerate.

Uses FakeConversationsConnection (no real DB) via monkeypatching
app.main.get_connection directly -- this endpoint does not use
Depends(get_db_dependency), matching post_message's existing convention
(docs/step12_substep3a_plan.md section 6).
"""

from fastapi.testclient import TestClient

import app.main as main_module
from app.conversations_queries import (
    ConversationMismatch,
    InvalidRegenerateTarget,
    ParentMessageNotFound,
    RegenerateAlreadyInProgress,
    create_conversation,
    create_streaming_assistant_placeholder,
    finalize_assistant_message,
    insert_user_message,
)
from app.main import app
from app.services.chat_provider import ChatDeltaEvent, ChatFinishEvent
from tests.fakes import FakeConversationsConnection

client = TestClient(app)


class _FakeConnCtx:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        return False


def _use_fake_get_connection(monkeypatch, conn: FakeConversationsConnection) -> None:
    monkeypatch.setattr(main_module, "get_connection", lambda: _FakeConnCtx(conn))


class _FakeCompletingProvider:
    provider_name = "fake"
    model_name = "fake-model"

    def stream_chat(self, messages, tools=None, tool_choice=None):
        async def _gen():
            yield ChatDeltaEvent(delta="regenerated answer")
            yield ChatFinishEvent(finish_reason="stop", usage=None)

        return _gen()


def _use_fake_chat_provider(monkeypatch):
    monkeypatch.setattr(main_module, "_build_chat_provider", lambda: _FakeCompletingProvider())


# ---------------------------------------------------------------------------
# 404 / 400 / 409 validation
# ---------------------------------------------------------------------------


def test_regenerate_404_when_conversation_missing(monkeypatch):
    conn = FakeConversationsConnection()
    _use_fake_get_connection(monkeypatch, conn)

    response = client.post("/conversations/999/messages/1/regenerate")

    assert response.status_code == 404


def test_regenerate_404_when_conversation_archived(monkeypatch):
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    conn.conversations_by_id[conversation_id]["archived_at"] = "2026-01-01T00:00:00"
    _use_fake_get_connection(monkeypatch, conn)

    response = client.post(f"/conversations/{conversation_id}/messages/1/regenerate")

    assert response.status_code == 404


def test_regenerate_404_when_parent_message_missing(monkeypatch):
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    _use_fake_get_connection(monkeypatch, conn)
    _use_fake_chat_provider(monkeypatch)

    def _raise_not_found(conn, conversation_id, message_id, provider, model):
        raise ParentMessageNotFound(message_id)

    monkeypatch.setattr(main_module, "create_regenerate_attempt", _raise_not_found)

    response = client.post(f"/conversations/{conversation_id}/messages/999/regenerate")

    assert response.status_code == 404


def test_regenerate_404_when_conversation_mismatch(monkeypatch):
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    _use_fake_get_connection(monkeypatch, conn)
    _use_fake_chat_provider(monkeypatch)

    def _raise_mismatch(conn, conversation_id, message_id, provider, model):
        raise ConversationMismatch(message_id)

    monkeypatch.setattr(main_module, "create_regenerate_attempt", _raise_mismatch)

    response = client.post(f"/conversations/{conversation_id}/messages/1/regenerate")

    assert response.status_code == 404


def test_regenerate_400_when_target_is_not_a_user_message(monkeypatch):
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    _use_fake_get_connection(monkeypatch, conn)
    _use_fake_chat_provider(monkeypatch)

    def _raise_invalid(conn, conversation_id, message_id, provider, model):
        raise InvalidRegenerateTarget(message_id)

    monkeypatch.setattr(main_module, "create_regenerate_attempt", _raise_invalid)

    response = client.post(f"/conversations/{conversation_id}/messages/1/regenerate")

    assert response.status_code == 400


def test_regenerate_409_when_already_in_progress(monkeypatch):
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    _use_fake_get_connection(monkeypatch, conn)
    _use_fake_chat_provider(monkeypatch)

    def _raise_in_progress(conn, conversation_id, message_id, provider, model):
        raise RegenerateAlreadyInProgress(message_id)

    monkeypatch.setattr(main_module, "create_regenerate_attempt", _raise_in_progress)

    response = client.post(f"/conversations/{conversation_id}/messages/1/regenerate")

    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Happy path -- real create_regenerate_attempt against a fake connection,
# fake ChatProvider for the stream itself.
# ---------------------------------------------------------------------------


def _seed_conversation_with_finalized_attempt(conn, status: str):
    # A short conversational-opener message (per app/services/answer_classifier.py's
    # allowlist) so the capability guard doesn't reject _FakeCompletingProvider's
    # zero-tool-call "regenerated answer" -- this fixture is about regenerate
    # attempt lifecycle mechanics, not capability-guard behavior (covered
    # separately in test_answer_classifier.py).
    conversation_id = create_conversation(conn)
    user_message_id = insert_user_message(conn, conversation_id, "hi, summarize the weather")
    first_attempt_id = create_streaming_assistant_placeholder(
        conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini"
    )
    finalize_assistant_message(conn, first_attempt_id, "first answer", status, None, "stop", None)
    return conversation_id, user_message_id, first_attempt_id


def test_regenerate_happy_path_creates_next_attempt_and_streams(monkeypatch):
    conn = FakeConversationsConnection()
    conversation_id, user_message_id, first_attempt_id = _seed_conversation_with_finalized_attempt(conn, "completed")
    _use_fake_get_connection(monkeypatch, conn)
    _use_fake_chat_provider(monkeypatch)

    response = client.post(f"/conversations/{conversation_id}/messages/{user_message_id}/regenerate")

    assert response.status_code == 200
    body = response.text
    assert "event: message_started" in body
    assert "regenerated answer" in body
    assert "event: message_completed" in body

    # attempt lifecycle: old attempt inactive, new attempt is the sole active one
    assert conn.messages_by_id[first_attempt_id]["is_active"] is False
    active = [
        m for m in conn.messages_by_id.values()
        if m.get("parent_user_message_id") == user_message_id and m.get("is_active")
    ]
    assert len(active) == 1
    assert active[0]["attempt_number"] == 2
    assert active[0]["content"] == "regenerated answer"
    assert active[0]["status"] == "completed"


def test_regenerate_works_after_failed_attempt(monkeypatch):
    conn = FakeConversationsConnection()
    conversation_id, user_message_id, _ = _seed_conversation_with_finalized_attempt(conn, "failed")
    _use_fake_get_connection(monkeypatch, conn)
    _use_fake_chat_provider(monkeypatch)

    response = client.post(f"/conversations/{conversation_id}/messages/{user_message_id}/regenerate")

    assert response.status_code == 200
    assert "regenerated answer" in response.text


def test_regenerate_works_after_aborted_attempt(monkeypatch):
    conn = FakeConversationsConnection()
    conversation_id, user_message_id, _ = _seed_conversation_with_finalized_attempt(conn, "aborted")
    _use_fake_get_connection(monkeypatch, conn)
    _use_fake_chat_provider(monkeypatch)

    response = client.post(f"/conversations/{conversation_id}/messages/{user_message_id}/regenerate")

    assert response.status_code == 200
    assert "regenerated answer" in response.text


# ---------------------------------------------------------------------------
# Regenerate context must not include the superseded assistant reply
# ---------------------------------------------------------------------------


class _RecordingProvider:
    """Like _FakeCompletingProvider, but records the `messages` argument so
    tests can assert exactly what context was sent to the provider."""

    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self):
        self.received_messages: list = None

    def stream_chat(self, messages, tools=None, tool_choice=None):
        self.received_messages = messages

        async def _gen():
            yield ChatDeltaEvent(delta="regenerated answer")
            yield ChatFinishEvent(finish_reason="stop", usage=None)

        return _gen()


def test_regenerate_context_excludes_superseded_assistant_reply(monkeypatch):
    conn = FakeConversationsConnection()
    conversation_id, user_message_id, first_attempt_id = _seed_conversation_with_finalized_attempt(conn, "completed")
    _use_fake_get_connection(monkeypatch, conn)

    recording_provider = _RecordingProvider()
    monkeypatch.setattr(main_module, "_build_chat_provider", lambda: recording_provider)

    response = client.post(f"/conversations/{conversation_id}/messages/{user_message_id}/regenerate")

    assert response.status_code == 200
    assert recording_provider.received_messages is not None

    contents = [m["content"] for m in recording_provider.received_messages]
    # the parent user message must appear exactly once (as the new turn),
    # not duplicated from conversation history
    assert contents.count("hi, summarize the weather") == 1
    # the superseded first attempt's answer must not leak into context
    assert "first answer" not in contents


def test_regenerate_context_keeps_earlier_legitimate_history(monkeypatch):
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    earlier_user_id = insert_user_message(conn, conversation_id, "what is the site's current SOC?")
    earlier_attempt_id = create_streaming_assistant_placeholder(
        conn, conversation_id, earlier_user_id, 1, "openai", "gpt-4o-mini"
    )
    finalize_assistant_message(conn, earlier_attempt_id, "SOC is 80%", "completed", None, "stop", None)

    user_message_id = insert_user_message(conn, conversation_id, "please summarize the weather today")
    first_attempt_id = create_streaming_assistant_placeholder(
        conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini"
    )
    finalize_assistant_message(conn, first_attempt_id, "first answer", "completed", None, "stop", None)

    _use_fake_get_connection(monkeypatch, conn)
    recording_provider = _RecordingProvider()
    monkeypatch.setattr(main_module, "_build_chat_provider", lambda: recording_provider)

    response = client.post(f"/conversations/{conversation_id}/messages/{user_message_id}/regenerate")

    assert response.status_code == 200
    contents = [m["content"] for m in recording_provider.received_messages]

    # earlier, unrelated turn is preserved
    assert "what is the site's current SOC?" in contents
    assert "SOC is 80%" in contents
    # superseded reply to the message being regenerated is still excluded
    assert "first answer" not in contents


def test_regenerate_409_when_first_attempt_still_streaming(monkeypatch):
    conn = FakeConversationsConnection()
    conversation_id = create_conversation(conn)
    user_message_id = insert_user_message(conn, conversation_id, "why?")
    create_streaming_assistant_placeholder(conn, conversation_id, user_message_id, 1, "openai", "gpt-4o-mini")
    # never finalized -- still streaming
    _use_fake_get_connection(monkeypatch, conn)
    _use_fake_chat_provider(monkeypatch)

    response = client.post(f"/conversations/{conversation_id}/messages/{user_message_id}/regenerate")

    assert response.status_code == 409
