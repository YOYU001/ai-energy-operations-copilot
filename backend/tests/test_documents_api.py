"""Step 10 Sub-step 4: Documents backend API endpoint tests.

Uses FakeRagConnection (no real DB) via app.dependency_overrides, exactly
like test_datasets_api.py / test_analysis_endpoint.py. The background
ingestion task does not go through FastAPI's DI system (BackgroundTasks
calls plain functions), so app.main.get_connection is monkeypatched to hand
the SAME FakeRagConnection instance to the background task as the one
wired into the request-scoped dependency override -- this lets a test set
up state via the request and observe what the background task subsequently
wrote, without touching a real database.

Starlette's TestClient runs background tasks synchronously (as part of the
same call) before returning the response, so no polling/waiting is needed
here to observe post-ingestion state.

No real OpenAI API calls: app.main._build_embedding_provider is
monkeypatched to return DeterministicFakeEmbeddingProvider.
"""

import contextlib

from fastapi.testclient import TestClient

import app.main as main_module
from app.db import get_db_dependency
from app.main import app
from tests.fakes import FakeRagConnection
from tests.pdf_fixtures import DeterministicFakeEmbeddingProvider, build_fixture_pdf

client = TestClient(app)


def _use_fake_connection(monkeypatch, conn: FakeRagConnection) -> None:
    def _override():
        yield conn

    app.dependency_overrides[get_db_dependency] = _override

    @contextlib.contextmanager
    def _fake_get_connection():
        yield conn

    monkeypatch.setattr(main_module, "get_connection", _fake_get_connection)


def _use_provider(monkeypatch, provider) -> None:
    monkeypatch.setattr(main_module, "_build_embedding_provider", lambda: provider)


def _clear_override():
    app.dependency_overrides.pop(get_db_dependency, None)


def _pdf_bytes(tmp_path, page_texts, name="fixture.pdf") -> bytes:
    path = tmp_path / name
    build_fixture_pdf(path, page_texts)
    return path.read_bytes()


_PAGES_A = [
    "Documents API test fixture, page 1.\n"
    "Filler sentence filler sentence filler sentence filler sentence.\n"
    "Filler sentence filler sentence filler sentence filler sentence.",
    "Documents API test fixture, page 2.\n"
    "Filler sentence filler sentence filler sentence filler sentence.\n"
    "Filler sentence filler sentence filler sentence filler sentence.",
]

_PAGES_B = [
    "Documents API test fixture, DIFFERENT content, page 1.\n"
    "Different filler different filler different filler different filler.\n"
    "Different filler different filler different filler different filler.",
]


# ---------------------------------------------------------------------------
# POST /documents/upload
# ---------------------------------------------------------------------------


def test_upload_valid_pdf_returns_processing_quickly(tmp_path, monkeypatch):
    conn = FakeRagConnection()
    _use_fake_connection(monkeypatch, conn)
    _use_provider(monkeypatch, DeterministicFakeEmbeddingProvider())
    try:
        response = client.post(
            "/documents/upload",
            files={"file": ("a.pdf", _pdf_bytes(tmp_path, _PAGES_A), "application/pdf")},
        )
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in ("processing", "already_ingested")
    assert body["file_name"] == "a.pdf"
    assert isinstance(body["document_id"], int)
    # by the time TestClient returns, the background task already ran (sync in tests)
    assert conn.documents[body["document_id"]]["status"] == "ready"


def test_upload_unsupported_extension_is_rejected(monkeypatch):
    conn = FakeRagConnection()
    _use_fake_connection(monkeypatch, conn)
    try:
        response = client.post(
            "/documents/upload",
            files={"file": ("notes.txt", b"hello world", "text/plain")},
        )
    finally:
        _clear_override()

    assert 400 <= response.status_code < 500
    assert conn.documents == {}  # rejected before any row was created


def test_upload_empty_file_is_rejected(monkeypatch):
    conn = FakeRagConnection()
    _use_fake_connection(monkeypatch, conn)
    try:
        response = client.post(
            "/documents/upload",
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
    finally:
        _clear_override()

    assert 400 <= response.status_code < 500
    assert conn.documents == {}


def test_upload_duplicate_ready_document_is_a_no_op(tmp_path, monkeypatch):
    conn = FakeRagConnection()
    _use_fake_connection(monkeypatch, conn)
    _use_provider(monkeypatch, DeterministicFakeEmbeddingProvider())
    pdf_bytes = _pdf_bytes(tmp_path, _PAGES_A)
    try:
        first = client.post("/documents/upload", files={"file": ("a.pdf", pdf_bytes, "application/pdf")})
        assert first.json()["status"] == "processing"
        assert conn.documents[first.json()["document_id"]]["status"] == "ready"

        second = client.post("/documents/upload", files={"file": ("a.pdf", pdf_bytes, "application/pdf")})
    finally:
        _clear_override()

    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "already_ingested"
    assert body["document_id"] == first.json()["document_id"]
    assert len(conn.documents) == 1  # no second row


def test_upload_background_failure_ends_in_failed_status(tmp_path, monkeypatch):
    conn = FakeRagConnection()
    _use_fake_connection(monkeypatch, conn)
    _use_provider(monkeypatch, DeterministicFakeEmbeddingProvider(fail_on_call=1))
    try:
        response = client.post(
            "/documents/upload",
            files={"file": ("a.pdf", _pdf_bytes(tmp_path, _PAGES_A), "application/pdf")},
        )
    finally:
        _clear_override()

    assert response.status_code == 200  # the endpoint itself doesn't wait for ingestion to finish
    document_id = response.json()["document_id"]
    assert conn.documents[document_id]["status"] == "failed"  # never stuck in "processing"


def test_upload_retry_after_failure_can_succeed(tmp_path, monkeypatch):
    conn = FakeRagConnection()
    _use_fake_connection(monkeypatch, conn)
    pdf_bytes = _pdf_bytes(tmp_path, _PAGES_A)

    _use_provider(monkeypatch, DeterministicFakeEmbeddingProvider(fail_on_call=1))
    try:
        first = client.post("/documents/upload", files={"file": ("a.pdf", pdf_bytes, "application/pdf")})
    finally:
        _clear_override()
    document_id = first.json()["document_id"]
    assert conn.documents[document_id]["status"] == "failed"

    _use_fake_connection(monkeypatch, conn)
    _use_provider(monkeypatch, DeterministicFakeEmbeddingProvider())
    try:
        retry = client.post("/documents/upload", files={"file": ("a.pdf", pdf_bytes, "application/pdf")})
    finally:
        _clear_override()

    assert retry.json()["document_id"] == document_id  # same row reused, not a new one
    assert conn.documents[document_id]["status"] == "ready"


# ---------------------------------------------------------------------------
# GET /documents, /documents/{id}, /documents/{id}/chunks
# ---------------------------------------------------------------------------


def test_get_documents_returns_list(tmp_path, monkeypatch):
    conn = FakeRagConnection()
    _use_fake_connection(monkeypatch, conn)
    _use_provider(monkeypatch, DeterministicFakeEmbeddingProvider())
    try:
        client.post("/documents/upload", files={"file": ("a.pdf", _pdf_bytes(tmp_path, _PAGES_A), "application/pdf")})
        response = client.get("/documents")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["file_name"] == "a.pdf"
    assert body[0]["status"] == "ready"
    assert set(body[0].keys()) == {
        "id", "title", "file_name", "file_type", "source_type", "uploaded_at",
        "status", "total_pages", "supersedes_document_id",
    }


def test_get_document_detail_returns_200(tmp_path, monkeypatch):
    conn = FakeRagConnection()
    _use_fake_connection(monkeypatch, conn)
    _use_provider(monkeypatch, DeterministicFakeEmbeddingProvider())
    try:
        upload = client.post("/documents/upload", files={"file": ("a.pdf", _pdf_bytes(tmp_path, _PAGES_A), "application/pdf")})
        document_id = upload.json()["document_id"]
        response = client.get(f"/documents/{document_id}")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == document_id
    assert body["file_type"] == "pdf"
    assert body["source_type"] == "upload"
    assert body["total_pages"] == 2


def test_get_document_404_when_missing(monkeypatch):
    conn = FakeRagConnection()
    _use_fake_connection(monkeypatch, conn)
    try:
        response = client.get("/documents/999999")
    finally:
        _clear_override()

    assert response.status_code == 404


def test_get_document_chunks_returns_only_active_chunks_without_embedding(tmp_path, monkeypatch):
    conn = FakeRagConnection()
    _use_fake_connection(monkeypatch, conn)
    _use_provider(monkeypatch, DeterministicFakeEmbeddingProvider())
    try:
        upload = client.post("/documents/upload", files={"file": ("a.pdf", _pdf_bytes(tmp_path, _PAGES_A), "application/pdf")})
        document_id = upload.json()["document_id"]
        response = client.get(f"/documents/{document_id}/chunks")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert len(body) >= 1
    for chunk in body:
        assert chunk["is_active"] is True
        assert "embedding" not in chunk  # never expose the 1536-dim vector
        assert set(chunk.keys()) == {
            "chunk_id", "strategy_name", "chunk_type", "content",
            "page_index_start", "page_index_end",
            "pdf_page_number_start", "pdf_page_number_end",
            "section_title", "table_title",
            "embedding_provider", "embedding_model", "embedding_dimensions",
            "embedding_model_version", "embedded_at", "is_active",
        }


def test_get_document_chunks_excludes_inactive_superseded_chunks(tmp_path, monkeypatch):
    conn = FakeRagConnection()
    _use_fake_connection(monkeypatch, conn)
    _use_provider(monkeypatch, DeterministicFakeEmbeddingProvider())
    pdf_a = _pdf_bytes(tmp_path, _PAGES_A, name="a.pdf")
    pdf_b = _pdf_bytes(tmp_path, _PAGES_B, name="b.pdf")
    try:
        v1 = client.post("/documents/upload", files={"file": ("same.pdf", pdf_a, "application/pdf")})
        v1_id = v1.json()["document_id"]
        client.post("/documents/upload", files={"file": ("same.pdf", pdf_b, "application/pdf")})

        response = client.get(f"/documents/{v1_id}/chunks")
    finally:
        _clear_override()

    assert response.status_code == 200
    assert response.json() == []  # v1's chunks are now inactive (superseded), not returned
