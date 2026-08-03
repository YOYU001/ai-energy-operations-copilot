"""Step 12 Sub-step 3A slice 2: Conversation CRUD API route tests.

Uses FakeConversationsConnection (no real DB) via app.dependency_overrides,
exactly like test_cases_api.py uses FakeCaseRecordsConnection. This slice
covers only the 5 CRUD endpoints -- POST /conversations/{id}/messages, SSE,
and ChatProvider wiring are later slices (docs/step12_substep3a_plan.md).
"""

from fastapi.testclient import TestClient

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
