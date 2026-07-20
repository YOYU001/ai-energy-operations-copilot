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

    def execute(self, statement, params=None):
        self.executed.append((statement, params))
        if self._responses is not None:
            rows = self._responses.pop(0)
        else:
            rows = self._rows
        return FakeResult(rows)
