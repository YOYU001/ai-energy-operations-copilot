class FakeResult:
    """Mimics the subset of SQLAlchemy's CursorResult used by our query functions."""

    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


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
