"""Step 10 Sub-step 4: real dev PostgreSQL API integration test for the
Documents endpoints (POST /documents/upload, GET /documents/{id},
GET /documents/{id}/chunks).

Only _build_embedding_provider is monkeypatched (no real OpenAI calls);
get_db_dependency is left pointed at the real app.db.get_connection(), and
the background task also uses the real get_connection() (unpatched) -- this
is the one test file in this session that exercises the FULL production
wiring end to end against Postgres, not FakeRagConnection.

Note on background-task timing: Starlette's TestClient drives the ASGI app
to completion -- including any scheduled BackgroundTasks -- before
client.post(...) returns. In a real deployed server, ingestion keeps
running strictly after the HTTP response is already sent to the caller;
under TestClient that gap collapses to zero, so this test cannot observe an
intermediate "processing" GET between upload and completion the way a real
client polling the API could. What it CAN and does verify is the real,
unmocked lifecycle end state: real Postgres row creation, background
ingestion completing successfully, and the chunks becoming query-visible --
exactly the persistence behavior a production deployment depends on.

Isolation: rows use file_name starting with INTEGRATION_API_PREFIX; cleanup
runs in fixture teardown regardless of test outcome.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.main as main_module
from app.db import get_connection, get_db_dependency
from app.main import app
from tests.pdf_fixtures import DeterministicFakeEmbeddingProvider, build_fixture_pdf

INTEGRATION_API_PREFIX = "integration_test_documents_api_"

client = TestClient(app)

_PAGES = [
    "Documents API real-DB integration fixture, page 1.\n"
    "Filler sentence filler sentence filler sentence filler sentence.\n"
    "Filler sentence filler sentence filler sentence filler sentence.",
    "Documents API real-DB integration fixture, page 2.\n"
    "Filler sentence filler sentence filler sentence filler sentence.\n"
    "Filler sentence filler sentence filler sentence filler sentence.",
]


@pytest.fixture
def real_db_documents_api(monkeypatch):
    monkeypatch.setattr(main_module, "_build_embedding_provider", lambda: DeterministicFakeEmbeddingProvider())

    def _override():
        with get_connection() as conn:
            yield conn

    app.dependency_overrides[get_db_dependency] = _override
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db_dependency, None)
        with get_connection() as conn:
            conn.execute(
                text(
                    "DELETE FROM document_chunks WHERE document_id IN "
                    "(SELECT id FROM documents WHERE file_name LIKE :prefix)"
                ),
                {"prefix": f"{INTEGRATION_API_PREFIX}%"},
            )
            conn.execute(
                text("DELETE FROM documents WHERE file_name LIKE :prefix AND supersedes_document_id IS NOT NULL"),
                {"prefix": f"{INTEGRATION_API_PREFIX}%"},
            )
            conn.execute(text("DELETE FROM documents WHERE file_name LIKE :prefix"), {"prefix": f"{INTEGRATION_API_PREFIX}%"})
            conn.commit()


def test_full_upload_flow_against_real_postgres(tmp_path, real_db_documents_api):
    path = tmp_path / "fixture.pdf"
    build_fixture_pdf(path, _PAGES)
    content = path.read_bytes()
    file_name = f"{INTEGRATION_API_PREFIX}fixture.pdf"

    upload_response = client.post("/documents/upload", files={"file": (file_name, content, "application/pdf")})
    assert upload_response.status_code == 200
    upload_body = upload_response.json()
    assert upload_body["status"] == "processing"
    document_id = upload_body["document_id"]

    detail_response = client.get(f"/documents/{document_id}")
    assert detail_response.status_code == 200
    detail_body = detail_response.json()
    assert detail_body["status"] == "ready"  # background ingestion completed by the time TestClient returned
    assert detail_body["file_name"] == file_name
    assert detail_body["file_type"] == "pdf"
    assert detail_body["source_type"] == "upload"
    assert detail_body["total_pages"] == 2

    chunks_response = client.get(f"/documents/{document_id}/chunks")
    assert chunks_response.status_code == 200
    chunks_body = chunks_response.json()
    assert len(chunks_body) >= 1
    assert all(c["is_active"] for c in chunks_body)
    assert all("embedding" not in c for c in chunks_body)

    list_response = client.get("/documents")
    assert any(d["id"] == document_id for d in list_response.json())
