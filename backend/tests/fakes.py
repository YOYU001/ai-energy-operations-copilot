import json
import math
from datetime import datetime, timezone


def _parse_vector(value):
    """Inverse of str(list[float]) -- case_records_queries.py stores/queries
    embeddings as str(vector) (see upsert_case_record/fetch_candidate_cases),
    so the fake must parse that same text format back into floats to compute
    a real cosine distance for test candidates."""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    return [float(x) for x in value.strip("[]").split(",") if x.strip()]


def _cosine_distance(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 1.0
    return 1.0 - dot / (norm_a * norm_b)


class FakeResult:
    """Mimics the subset of SQLAlchemy's CursorResult used by our query functions."""

    def __init__(self, rows, rowcount=None):
        self._rows = rows
        # Defaults to len(rows) -- fine for the common RETURNING/SELECT
        # cases; callers asserting a specific UPDATE/DELETE rowcount
        # distinct from returned row count can pass it explicitly.
        self.rowcount = len(rows) if rowcount is None else rowcount

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one(self):
        # First column of the first row -- e.g. a `RETURNING id` query's result.
        return next(iter(self._rows[0].values()))


class FakeConnection:
    """Stand-in for a SQLAlchemy Connection, used via dependency override in tests.

    Records every execute() call so tests can assert on the SQL that was run,
    and returns pre-canned rows instead of touching a real database.

    Most endpoints only run one query per request, so passing `rows` (a
    single result set reused for every execute() call) is enough. Endpoints
    that run more than one query per request (e.g. an existence check
    followed by an aggregate query) should pass `responses`: a list of
    result sets consumed in order, one per execute() call.
    """

    def __init__(self, rows=None, responses=None):
        self._rows = rows if rows is not None else []
        self._responses = list(responses) if responses is not None else None
        self.executed = []
        self.committed = False
        self.rolled_back = False

    def execute(self, statement, params=None):
        self.executed.append((statement, params))
        if self._responses is not None:
            rows = self._responses.pop(0)
        else:
            rows = self._rows
        return FakeResult(rows)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class FakeExecResult:
    """Like FakeResult, but also supports scalar_one()/rowcount for the
    document_chunks_queries.py functions that need them (RETURNING id,
    UPDATE ... rowcount)."""

    def __init__(self, rows=None, scalar=None, rowcount=0):
        self._rows = rows or []
        self._scalar = scalar
        self.rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one(self):
        return self._scalar


class FakeRagConnection:
    """In-memory stand-in for the subset of a SQLAlchemy Connection used by
    document_chunks_queries.py / ingestion_rag.py.

    Dispatches on literal substrings of the real SQL text in
    document_chunks_queries.py, so it must be kept in sync with that file's
    queries. Ported from spike/tests/test_chunk_lifecycle.py's
    FakeLifecycleConnection, adapted to the production documents/
    document_chunks column names and to this module's actual SQL (e.g.
    is_active is not a bound parameter on insert here -- new chunks are
    always inserted false).

    Has a real transactional undo log so commit()/rollback() behave like a
    real single-connection transaction: writes are visible to subsequent
    reads immediately, but only made permanent on commit() and reverted on
    rollback().
    """

    def __init__(self):
        self.documents: dict[int, dict] = {}
        self.chunks: dict[str, dict] = {}
        self._next_doc_id = 1
        self._undo_log: list = []
        self.raise_on_deactivate = False  # test hook for simulating cutover failure

    def _stage(self, undo_fn):
        self._undo_log.append(undo_fn)

    def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}

        if "document_content_hash = :hash" in sql:
            for doc in self.documents.values():
                if doc["document_content_hash"] == params["hash"]:
                    return FakeExecResult(rows=[dict(doc)])
            return FakeExecResult(rows=[])

        if "SELECT DISTINCT d.id" in sql:
            for doc_id, doc in self.documents.items():
                if doc["file_name"] == params["file_name"] and any(
                    c["document_id"] == doc_id and c["is_active"] for c in self.chunks.values()
                ):
                    return FakeExecResult(rows=[{"id": doc_id}])
            return FakeExecResult(rows=[])

        if "INSERT INTO documents" in sql:
            doc_id = self._next_doc_id
            self._next_doc_id += 1
            self.documents[doc_id] = {
                "id": doc_id,
                "file_name": params["file_name"],
                "document_content_hash": params["hash"],
                "total_pages": params["total_pages"],
                "supersedes_document_id": params["supersedes"],
                "status": "processing",
                "title": params.get("title"),
                "file_type": params.get("file_type"),
                "source_type": params.get("source_type"),
            }
            self._stage(lambda d=doc_id: self.documents.pop(d, None))
            return FakeExecResult(scalar=doc_id)

        if "SELECT id, title, file_name, file_type, source_type, uploaded_at" in sql:
            rows = sorted(self.documents.values(), key=lambda d: d["id"], reverse=True)
            return FakeExecResult(rows=[dict(d) for d in rows])

        if "SELECT chunk_id, strategy_name, chunk_type, content" in sql:
            doc_id = params["document_id"]
            rows = [dict(c) for c in self.chunks.values() if c["document_id"] == doc_id and c["is_active"]]
            rows.sort(key=lambda c: (c["page_index_start"], c["chunk_id"]))
            return FakeExecResult(rows=rows)

        if "SET status = :status" in sql:
            doc_id = params["id"]
            old_status = self.documents[doc_id]["status"]
            self.documents[doc_id]["status"] = params["status"]
            self._stage(lambda d=doc_id, s=old_status: self.documents[d].__setitem__("status", s))
            return FakeExecResult()

        if "SET total_pages = :total_pages" in sql:
            doc_id = params["id"]
            old_total = self.documents[doc_id]["total_pages"]
            self.documents[doc_id]["total_pages"] = params["total_pages"]
            self._stage(lambda d=doc_id, v=old_total: self.documents[d].__setitem__("total_pages", v))
            return FakeExecResult()

        if "FROM documents WHERE id = :id" in sql:
            doc = self.documents.get(params["id"])
            return FakeExecResult(rows=[dict(doc)] if doc else [])

        if "chunk_id = ANY(:ids)" in sql:
            ids = params["ids"]
            rows = [
                {"chunk_id": cid, "chunk_metadata_hash": self.chunks[cid]["chunk_metadata_hash"]}
                for cid in ids
                if cid in self.chunks
            ]
            return FakeExecResult(rows=rows)

        if "INSERT INTO document_chunks" in sql:
            cid = params["chunk_id"]
            if cid in self.chunks:
                return FakeExecResult(rows=[])  # ON CONFLICT DO NOTHING -> no row returned
            self.chunks[cid] = {
                "chunk_id": cid,
                "document_id": params["document_id"],
                "strategy_name": params["strategy_name"],
                "chunk_type": params["chunk_type"],
                "content": params["content"],
                "embedding_content_hash": params["embedding_content_hash"],
                "chunk_metadata_hash": params["chunk_metadata_hash"],
                "page_index_start": params["page_index_start"],
                "page_index_end": params["page_index_end"],
                "pdf_page_number_start": params["pdf_page_number_start"],
                "pdf_page_number_end": params["pdf_page_number_end"],
                "printed_page_number_map": params["printed_page_number_map"],
                "section_title": params["section_title"],
                "table_title": params["table_title"],
                "embedding": params["embedding"],
                "embedding_provider": params["embedding_provider"],
                "embedding_model": params["embedding_model"],
                "embedding_dimensions": params["embedding_dimensions"],
                "embedding_model_version": params["embedding_model_version"],
                "is_active": False,
            }
            self._stage(lambda c=cid: self.chunks.pop(c, None))
            return FakeExecResult(rows=[{"chunk_id": cid}])

        if "SET chunk_metadata_hash" in sql:
            cid = params["chunk_id"]
            if cid in self.chunks:
                old = {
                    k: self.chunks[cid][k]
                    for k in ("chunk_metadata_hash", "section_title", "table_title", "printed_page_number_map")
                }
                self.chunks[cid]["chunk_metadata_hash"] = params["chunk_metadata_hash"]
                self.chunks[cid]["section_title"] = params["section_title"]
                self.chunks[cid]["table_title"] = params["table_title"]
                self.chunks[cid]["printed_page_number_map"] = params["printed_page_number_map"]
                self._stage(lambda c=cid, o=old: self.chunks[c].update(o))
            return FakeExecResult()

        if "COUNT(*) AS total" in sql:
            doc_id = params["document_id"]
            total = active = inactive = 0
            for c in self.chunks.values():
                if c["document_id"] == doc_id:
                    total += 1
                    active += 1 if c["is_active"] else 0
                    inactive += 1 if not c["is_active"] else 0
            return FakeExecResult(rows=[{"total": total, "active": active, "inactive": inactive}])

        if "new_id" in params:
            new_id = params["new_id"]
            count = 0
            for c in self.chunks.values():
                if c["document_id"] == new_id and not c["is_active"]:
                    c["is_active"] = True
                    count += 1
                    self._stage(lambda cc=c: cc.__setitem__("is_active", False))
            return FakeExecResult(rowcount=count)

        if "old_id" in params:
            if self.raise_on_deactivate:
                raise RuntimeError("simulated cutover failure")
            old_id = params["old_id"]
            for c in self.chunks.values():
                if c["document_id"] == old_id and c["is_active"]:
                    c["is_active"] = False
                    self._stage(lambda cc=c: cc.__setitem__("is_active", True))
            return FakeExecResult()

        if "document_id" in params and "is_active = true" in sql:
            doc_id = params["document_id"]
            strategy = params.get("strategy_name")
            rows = [
                dict(c)
                for c in self.chunks.values()
                if c["document_id"] == doc_id and c["is_active"] and (strategy is None or c["strategy_name"] == strategy)
            ]
            return FakeExecResult(rows=rows)

        raise AssertionError(f"FakeRagConnection: unrecognized SQL: {sql}")

    def commit(self):
        self._undo_log.clear()

    def rollback(self):
        while self._undo_log:
            self._undo_log.pop()()


class FakeCaseRecordsConnection:
    """In-memory stand-in for the subset of a SQLAlchemy Connection used by
    case_records_queries.py (Step 11 Sub-step 2A/2B).

    Keyed by case_id, mirroring the real case_records_case_id_key UNIQUE
    constraint (Sub-step 2B) -- upsert_case_record's single `INSERT ... ON
    CONFLICT (case_id) DO UPDATE ...` statement is emulated here as one
    branch that inserts if case_id is new, or updates in place (preserving
    the existing id) if it already exists, matching the real atomic
    upsert's observable behavior for a single fake connection.
    """

    def __init__(self):
        self.rows_by_case_id: dict[str, dict] = {}
        self._next_id = 1
        self.committed = False
        self.rolled_back = False

    def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}

        if "SELECT * FROM case_records WHERE case_id = ANY" in sql:
            wanted = set(params.get("ids", []))
            rows = [dict(r) for cid, r in self.rows_by_case_id.items() if cid in wanted]
            return FakeExecResult(rows=rows)

        if "SELECT * FROM case_records WHERE case_id" in sql:
            row = self.rows_by_case_id.get(params["case_id"])
            return FakeExecResult(rows=[dict(row)] if row else [])

        if "SELECT * FROM case_records WHERE id" in sql:
            row = next((r for r in self.rows_by_case_id.values() if r["id"] == params["id"]), None)
            return FakeExecResult(rows=[dict(row)] if row else [])

        if "INSERT INTO case_records" in sql and "ON CONFLICT (case_id)" in sql:
            case_id = params["case_id"]
            existing = self.rows_by_case_id.get(case_id)
            has_new_embedding = params.get("embedding") is not None

            now = datetime.now(timezone.utc)

            if existing is None:
                new_id = self._next_id
                self._next_id += 1
                row = dict(params)
                row["id"] = new_id
                row["embedded_at"] = now if has_new_embedding else None
                row["created_at"] = now
                row["updated_at"] = now
                self.rows_by_case_id[case_id] = row
                return FakeExecResult(scalar=new_id)

            row = existing
            for key, value in params.items():
                if key == "embedding" and not has_new_embedding:
                    continue  # EXCLUDED.embedding IS NULL -> preserve case_records.embedding
                if key in (
                    "embedding_provider",
                    "embedding_model",
                    "embedding_dimensions",
                    "embedding_model_version",
                    "embedding_content_hash",
                ) and not has_new_embedding:
                    continue
                row[key] = value
            if has_new_embedding:
                row["embedded_at"] = now
            row["updated_at"] = now
            return FakeExecResult(scalar=row["id"])

        if "SELECT COUNT(*) AS total FROM case_records" in sql:
            return FakeExecResult(rows=[{"total": len(self.rows_by_case_id)}])

        if "ORDER BY event_time DESC" in sql:
            rows = sorted(self.rows_by_case_id.values(), key=lambda r: r["id"], reverse=True)
            if "limit" in params:
                offset = params.get("offset", 0)
                rows = rows[offset : offset + params["limit"]]
            return FakeExecResult(rows=[dict(r) for r in rows])

        if "FROM case_records" in sql and "distance" in sql:
            # Candidate similarity query -- real vector math (Step 11
            # Sub-step 3's case_retrieval.py orchestration needs genuine
            # ranking/self-exclusion/top_k behavior to be testable, not just
            # SQL shape).
            query_vector = _parse_vector(params.get("qv"))
            pool_size = params.get("k", 30)
            candidates = []
            for row in self.rows_by_case_id.values():
                if row.get("embedding") is None:
                    continue
                distance = _cosine_distance(query_vector, _parse_vector(row["embedding"]))
                candidates.append({**row, "distance": distance})
            candidates.sort(key=lambda r: r["distance"])
            return FakeExecResult(rows=[dict(c) for c in candidates[:pool_size]])

        raise AssertionError(f"FakeCaseRecordsConnection: unrecognized SQL: {sql}")

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class FakeConversationsConnection:
    """In-memory stand-in for the subset of a SQLAlchemy Connection used by
    conversations_queries.py (Step 12 Sub-step 1).

    Dispatches on literal substrings of the real SQL text, kept in sync
    with conversations_queries.py's actual queries -- same convention as
    FakeCaseRecordsConnection. Branch order matters: more specific
    substrings (e.g. "FOR UPDATE", "regenerated_from_message_id") are
    checked before more general ones that would otherwise match first.

    No real row locking is implemented here -- this fake only proves SQL
    shape and single-connection sequencing, matching the Sub-step 1 plan's
    explicit acceptance criterion that the *concurrency* guarantee itself
    (FOR UPDATE actually serializing two callers) can only be proven
    against a real Postgres integration test, not this fake.
    """

    def __init__(self):
        self.conversations_by_id: dict[int, dict] = {}
        self.messages_by_id: dict[int, dict] = {}
        self._next_conversation_id = 1
        self._next_message_id = 1
        self.committed = False
        self.rolled_back = False

    def _active_messages_for_parent(self, parent_id):
        return [
            m for m in self.messages_by_id.values()
            if m.get("parent_user_message_id") == parent_id and m.get("is_active")
        ]

    def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}

        if "INSERT INTO conversations" in sql:
            new_id = self._next_conversation_id
            self._next_conversation_id += 1
            now = datetime.now(timezone.utc)
            self.conversations_by_id[new_id] = {
                "id": new_id,
                "title": None,
                "role_mode": params.get("role_mode"),
                "created_at": now,
                "updated_at": now,
                "archived_at": None,
            }
            return FakeExecResult(rows=[{"id": new_id}], scalar=new_id)

        if "SELECT COUNT(*) AS total FROM conversations" in sql:
            total = sum(1 for c in self.conversations_by_id.values() if c["archived_at"] is None)
            return FakeExecResult(rows=[{"total": total}])

        if "SELECT * FROM conversations" in sql and "ORDER BY updated_at" in sql:
            rows = [c for c in self.conversations_by_id.values() if c["archived_at"] is None]
            rows.sort(key=lambda c: (c["updated_at"], c["id"]), reverse=True)
            offset = params.get("offset", 0)
            limit = params.get("limit")
            if limit is not None:
                rows = rows[offset : offset + limit]
            return FakeExecResult(rows=[dict(r) for r in rows])

        if "SELECT * FROM conversations WHERE id" in sql:
            row = self.conversations_by_id.get(params.get("id"))
            if row is not None and "archived_at IS NULL" in sql and row["archived_at"] is not None:
                row = None
            return FakeExecResult(rows=[dict(row)] if row else [])

        if "SELECT * FROM chat_messages" in sql and "ORDER BY created_at, id" in sql:
            rows = [
                m for m in self.messages_by_id.values()
                if m.get("conversation_id") == params.get("conversation_id") and m.get("is_active")
            ]
            rows.sort(key=lambda m: (m["created_at"], m["id"]))
            return FakeExecResult(rows=[dict(r) for r in rows])

        if "UPDATE conversations" in sql and "SET title = COALESCE" in sql:
            row = self.conversations_by_id.get(params.get("id"))
            if row is None:
                return FakeExecResult(rows=[])
            if params.get("title") is not None:
                row["title"] = params["title"]
            if params.get("role_mode") is not None:
                row["role_mode"] = params["role_mode"]
            row["updated_at"] = datetime.now(timezone.utc)
            return FakeExecResult(rows=[dict(row)])

        if "UPDATE conversations" in sql and "SET archived_at = now()" in sql:
            row = self.conversations_by_id.get(params.get("id"))
            if row is None or row["archived_at"] is not None:
                return FakeExecResult(rowcount=0)
            row["archived_at"] = datetime.now(timezone.utc)
            row["updated_at"] = row["archived_at"]
            return FakeExecResult(rowcount=1)

        if "INSERT INTO chat_messages" in sql and "'user', :content, 'completed'" in sql:
            new_id = self._next_message_id
            self._next_message_id += 1
            now = datetime.now(timezone.utc)
            self.messages_by_id[new_id] = {
                "id": new_id,
                "conversation_id": params.get("conversation_id"),
                "role": "user",
                "content": params.get("content"),
                "status": "completed",
                "parent_user_message_id": None,
                "attempt_number": 1,
                "is_active": True,
                "regenerated_from_message_id": None,
                "provider": None,
                "model": None,
                "created_at": now,
                "updated_at": now,
            }
            return FakeExecResult(rows=[{"id": new_id}], scalar=new_id)

        if "UPDATE conversations" in sql and "title = left(:content, 40)" in sql:
            row = self.conversations_by_id.get(params.get("conversation_id"))
            if row is None or row["title"] is not None:
                return FakeExecResult(rowcount=0)
            row["title"] = params["content"][:40]
            row["updated_at"] = datetime.now(timezone.utc)
            return FakeExecResult(rowcount=1)

        if "INSERT INTO chat_messages" in sql and "regenerated_from_message_id" in sql:
            new_id = self._next_message_id
            self._next_message_id += 1
            now = datetime.now(timezone.utc)
            self.messages_by_id[new_id] = {
                "id": new_id,
                "conversation_id": params.get("conversation_id"),
                "role": "assistant",
                "content": "",
                "status": "streaming",
                "parent_user_message_id": params.get("parent_user_message_id"),
                "attempt_number": params.get("attempt_number"),
                "is_active": True,
                "regenerated_from_message_id": params.get("old_active_message_id"),
                "provider": params.get("provider"),
                "model": params.get("model"),
                "created_at": now,
                "updated_at": now,
            }
            return FakeExecResult(rows=[{"id": new_id}], scalar=new_id)

        if "INSERT INTO chat_messages" in sql and "attempt_number, is_active" in sql:
            new_id = self._next_message_id
            self._next_message_id += 1
            now = datetime.now(timezone.utc)
            self.messages_by_id[new_id] = {
                "id": new_id,
                "conversation_id": params.get("conversation_id"),
                "role": "assistant",
                "content": "",
                "status": "streaming",
                "parent_user_message_id": params.get("parent_user_message_id"),
                "attempt_number": params.get("attempt_number"),
                "is_active": True,
                "regenerated_from_message_id": None,
                "provider": params.get("provider"),
                "model": params.get("model"),
                "created_at": now,
                "updated_at": now,
            }
            return FakeExecResult(rows=[{"id": new_id}], scalar=new_id)

        if "UPDATE chat_messages" in sql and "SET content = :content" in sql:
            row = self.messages_by_id.get(params.get("message_id"))
            if row is None or row.get("status") != "streaming":
                return FakeExecResult(rowcount=0)
            row["content"] = params.get("content")
            row["status"] = params.get("status")
            row["error_message"] = params.get("error_message")
            row["finish_reason"] = params.get("finish_reason")
            row["usage"] = params.get("usage")
            row["completed_at"] = row.get("completed_at") or datetime.now(timezone.utc)
            row["updated_at"] = datetime.now(timezone.utc)
            return FakeExecResult(rowcount=1)

        if "FOR UPDATE" in sql:
            row = self.messages_by_id.get(params.get("id"))
            return FakeExecResult(rows=[dict(row)] if row else [])

        if "SELECT COALESCE(MAX(attempt_number), 0)" in sql:
            attempts = [
                m["attempt_number"] for m in self.messages_by_id.values()
                if m.get("parent_user_message_id") == params.get("parent_user_message_id")
            ]
            return FakeExecResult(rows=[{"max_attempt": max(attempts) if attempts else 0}])

        if "SELECT id, status FROM chat_messages" in sql and "is_active = true" in sql:
            active = self._active_messages_for_parent(params.get("parent_user_message_id"))
            return FakeExecResult(rows=[{"id": active[0]["id"], "status": active[0]["status"]}] if active else [])

        if "UPDATE chat_messages" in sql and "SET is_active = false" in sql:
            active = self._active_messages_for_parent(params.get("parent_user_message_id"))
            for row in active:
                row["is_active"] = False
                row["updated_at"] = datetime.now(timezone.utc)
            return FakeExecResult(rowcount=len(active))

        if "UPDATE chat_messages" in sql and "SET tool_calls = CAST" in sql:
            row = self.messages_by_id.get(params.get("message_id"))
            if row is None:
                return FakeExecResult(rowcount=0)
            # real JSONB columns round-trip already-deserialized Python
            # objects (SQLAlchemy/psycopg2), not the raw json.dumps() string
            # the caller passed in as a bind parameter -- mirror that here.
            tool_calls_param = params.get("tool_calls")
            citations_param = params.get("citations")
            row["tool_calls"] = json.loads(tool_calls_param) if tool_calls_param is not None else None
            row["citations"] = json.loads(citations_param) if citations_param is not None else None
            row["updated_at"] = datetime.now(timezone.utc)
            return FakeExecResult(rowcount=1)

        if "stale_streaming" in sql:
            cutoff = params.get("stale_before")
            conversation_id = params.get("conversation_id")
            affected = [
                m for m in self.messages_by_id.values()
                if m.get("conversation_id") == conversation_id
                and m.get("status") == "streaming"
                and m.get("created_at") < cutoff
            ]
            for row in affected:
                row["status"] = "failed"
                row["error_message"] = "stale_streaming"
                row["completed_at"] = datetime.now(timezone.utc)
                row["updated_at"] = datetime.now(timezone.utc)
            return FakeExecResult(rowcount=len(affected))

        if "interrupted by server restart" in sql:
            affected = [m for m in self.messages_by_id.values() if m.get("status") == "streaming"]
            for row in affected:
                row["status"] = "failed"
                row["error_message"] = "interrupted by server restart"
                row["completed_at"] = datetime.now(timezone.utc)
                row["updated_at"] = datetime.now(timezone.utc)
            return FakeExecResult(rowcount=len(affected))

        raise AssertionError(f"FakeConversationsConnection: unrecognized SQL: {sql}")

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True
