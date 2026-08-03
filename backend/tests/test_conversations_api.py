"""Step 12 Sub-step 3A: Conversation CRUD + Message read model API tests.

Uses FakeConversationsConnection (no real DB) via app.dependency_overrides,
exactly like test_cases_api.py uses FakeCaseRecordsConnection.

Slice 2 covers the 5 conversation CRUD endpoints. Slice 3 adds
GET /conversations/{id}/messages as a read-only message list endpoint --
per user decision, POST /conversations/{id}/messages is deliberately NOT
introduced in this slice (its approved contract is the future SSE
endpoint; see docs/step12_substep3a_plan.md), so Slice 3 test data is
seeded directly via the existing conversations_queries functions
(insert_user_message, create_streaming_assistant_placeholder,
finalize_assistant_message, create_regenerate_attempt) against the fake
connection, the same way test_cases_api.py seeds rows via
upsert_case_record directly rather than through an API.
"""

from fastapi.testclient import TestClient

from app.conversations_queries import (
    create_regenerate_attempt,
    create_streaming_assistant_placeholder,
    finalize_assistant_message,
    insert_user_message,
)
from app.db import get_db_dependency
from app.main import app
from tests.fakes import FakeConversationsConnection

client = TestClient(app)


def _use_fake_connection(conn: FakeConversationsConnection) -> None:
    def _override():
        yield conn

    app.dependency_overrides[get_db_dependency] = _override


def _clear_override():
    app.dependency_overrides.pop(get_db_dependency, None)


# ---------------------------------------------------------------------------
# POST /conversations
# ---------------------------------------------------------------------------


def test_post_conversation_creates_with_role_mode():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        response = client.post("/conversations", json={"role_mode": "engineer"})
    finally:
        _clear_override()

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 1
    assert body["role_mode"] == "engineer"
    assert body["title"] is None
    assert "created_at" in body
    assert "updated_at" in body


def test_post_conversation_without_role_mode_defaults_to_null():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        response = client.post("/conversations", json={})
    finally:
        _clear_override()

    assert response.status_code == 201
    assert response.json()["role_mode"] is None


def test_post_conversation_rejects_invalid_role_mode():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        response = client.post("/conversations", json={"role_mode": "not-a-real-mode"})
    finally:
        _clear_override()

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /conversations
# ---------------------------------------------------------------------------


def test_get_conversations_normal_list():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        create_conversation_response_1 = client.post("/conversations", json={"role_mode": "operator"})
        create_conversation_response_2 = client.post("/conversations", json={"role_mode": "engineer"})
        response = client.get("/conversations")
    finally:
        _clear_override()

    assert create_conversation_response_1.status_code == 201
    assert create_conversation_response_2.status_code == 201
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_get_conversations_empty_result():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        response = client.get("/conversations")
    finally:
        _clear_override()

    assert response.status_code == 200
    assert response.json() == {"total": 0, "limit": 100, "offset": 0, "items": []}


def test_get_conversations_respects_limit_and_offset():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        for _ in range(5):
            client.post("/conversations", json={})
        response = client.get("/conversations", params={"limit": 2, "offset": 0})
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2


def test_get_conversations_rejects_out_of_range_limit():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        response = client.get("/conversations", params={"limit": 0})
    finally:
        _clear_override()

    assert response.status_code == 422


def test_get_conversations_excludes_archived():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        client.post("/conversations", json={})
        client.delete("/conversations/1")
        response = client.get("/conversations")
    finally:
        _clear_override()

    assert response.status_code == 200
    assert response.json()["total"] == 0


# ---------------------------------------------------------------------------
# GET /conversations/{id}
# ---------------------------------------------------------------------------


def test_get_conversation_detail_normal():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        client.post("/conversations", json={"role_mode": "operator"})
        response = client.get("/conversations/1")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["conversation"]["id"] == 1
    assert body["conversation"]["role_mode"] == "operator"
    assert body["messages"] == []


def test_get_conversation_detail_404_when_absent():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        response = client.get("/conversations/999")
    finally:
        _clear_override()

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /conversations/{id}
# ---------------------------------------------------------------------------


def test_patch_conversation_updates_title_and_role_mode():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        client.post("/conversations", json={"role_mode": "operator"})
        response = client.patch("/conversations/1", json={"title": "renamed", "role_mode": "executive"})
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "renamed"
    assert body["role_mode"] == "executive"


def test_patch_conversation_partial_update_leaves_other_field_unchanged():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        client.post("/conversations", json={"role_mode": "operator"})
        response = client.patch("/conversations/1", json={"title": "only title changed"})
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "only title changed"
    assert body["role_mode"] == "operator"


def test_patch_conversation_404_when_absent():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        response = client.patch("/conversations/999", json={"title": "x"})
    finally:
        _clear_override()

    assert response.status_code == 404


def test_patch_conversation_rejects_invalid_role_mode():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        client.post("/conversations", json={})
        response = client.patch("/conversations/1", json={"role_mode": "not-a-real-mode"})
    finally:
        _clear_override()

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /conversations/{id}
# ---------------------------------------------------------------------------


def test_delete_conversation_archives():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        client.post("/conversations", json={})
        response = client.delete("/conversations/1")
        get_after = client.get("/conversations/1")
    finally:
        _clear_override()

    assert response.status_code == 200
    assert response.json() == {"archived": True}
    # archiving does not delete the row -- it remains individually fetchable
    assert get_after.status_code == 200


def test_delete_conversation_404_when_absent():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        response = client.delete("/conversations/999")
    finally:
        _clear_override()

    assert response.status_code == 404


def test_delete_conversation_404_when_already_archived():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        client.post("/conversations", json={})
        client.delete("/conversations/1")
        response = client.delete("/conversations/1")
    finally:
        _clear_override()

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /conversations/{id}/messages
# ---------------------------------------------------------------------------


def test_get_conversation_messages_empty_when_no_messages():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        client.post("/conversations", json={})
        response = client.get("/conversations/1/messages")
    finally:
        _clear_override()

    assert response.status_code == 200
    assert response.json() == []


def test_get_conversation_messages_404_when_conversation_absent():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        response = client.get("/conversations/999/messages")
    finally:
        _clear_override()

    assert response.status_code == 404


def test_get_conversation_messages_ordered_with_role_status_timestamp():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        client.post("/conversations", json={})  # conversation_id = 1
        user_message_id = insert_user_message(conn, 1, "why did battery 12 not discharge?")
        assistant_message_id = create_streaming_assistant_placeholder(
            conn, 1, user_message_id, attempt_number=1, provider="openai", model="gpt-4o-mini",
        )
        finalize_assistant_message(
            conn, assistant_message_id, content="because SOC was already low",
            status="completed", error_message=None, finish_reason="stop", usage=None,
        )
        response = client.get("/conversations/1/messages")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    # ordering: user message (created first) before its assistant reply
    assert body[0]["id"] == user_message_id
    assert body[0]["role"] == "user"
    assert body[0]["status"] == "completed"
    assert "created_at" in body[0]
    assert body[1]["id"] == assistant_message_id
    assert body[1]["role"] == "assistant"
    assert body[1]["status"] == "completed"
    assert body[1]["parent_user_message_id"] == user_message_id
    assert body[1]["provider"] == "openai"
    assert body[1]["model"] == "gpt-4o-mini"
    assert body[1]["finish_reason"] == "stop"
    assert body[1]["completed_at"] is not None


def test_get_conversation_messages_excludes_superseded_regenerate_attempts():
    conn = FakeConversationsConnection()
    _use_fake_connection(conn)
    try:
        client.post("/conversations", json={})  # conversation_id = 1
        user_message_id = insert_user_message(conn, 1, "question")
        first_attempt_id = create_streaming_assistant_placeholder(
            conn, 1, user_message_id, attempt_number=1, provider="openai", model="gpt-4o-mini",
        )
        finalize_assistant_message(
            conn, first_attempt_id, content="first answer",
            status="completed", error_message=None, finish_reason="stop", usage=None,
        )
        second_attempt_id = create_regenerate_attempt(conn, 1, user_message_id, provider="openai", model="gpt-4o-mini")
        finalize_assistant_message(
            conn, second_attempt_id, content="second answer",
            status="completed", error_message=None, finish_reason="stop", usage=None,
        )
        response = client.get("/conversations/1/messages")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    ids = [m["id"] for m in body]
    # only the currently-active attempt is returned -- the superseded first
    # attempt is excluded (is_active=false), matching GET /conversations/{id}
    assert first_attempt_id not in ids
    assert second_attempt_id in ids
    assert len(body) == 2  # user message + the one active assistant attempt
