"""Step 11 Sub-step 2B: seed pipeline for data/sample_case_records.json.

Split into small, independently testable functions -- the CLI `main()` only
wires them together, it is not where any of the logic lives.

Case embedding ("search") text intentionally includes only fields a real
similarity SEARCH query could plausibly know about: event_type, symptoms,
tags, severity. It must NEVER include the answer-shaped fields (root_cause,
operator_action, resolution_result) -- see app/services/case_similarity.py's
module docstring for why (the search itself must not leak the answer into
what a query gets matched against).

Dry-run mode makes zero DB connections and zero embedding-provider calls --
it only loads+validates the sample file and reports what a real run would
process. Normal mode requires DATABASE_URL and a real embedding provider
(reuses app.services.embedding_provider.OpenAIEmbeddingProvider -- no second
OpenAI client is built here).

run_seed is idempotent at the embedding-cost level, not just the row level:
re-running it with unchanged sample data makes zero embedding API calls
(compares each case's embedding_content_hash against what's already stored),
only re-embedding cases that are new, never got an embedding written, or
whose search text actually changed. See _needs_embedding below.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLE_PATH = REPO_ROOT / "data" / "sample_case_records.json"

# This script lives at the repo root (scripts/), a sibling of backend/, but
# imports app.* (backend/app/). Running it directly as `python
# scripts/seed_case_records.py` only puts scripts/ itself on sys.path, not
# backend/ -- unlike backend/scripts/run_retrieval_benchmark.py (Step 10),
# which is invoked as `cd backend && python -m scripts...` and relies on
# that cwd-based insertion. Bootstrapping backend/ here means this script
# just works with a plain `python scripts/seed_case_records.py` invocation,
# with no special PYTHONPATH/cwd requirement to remember.
_BACKEND_DIR = REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.case_records_queries import get_cases_by_case_ids, upsert_case_record  # noqa: E402
from app.services.embedding_provider import EmbeddingProvider  # noqa: E402
from app.services.hashing import compute_embedding_content_hash  # noqa: E402

REQUIRED_CASE_FIELDS = (
    "case_id",
    "site_id",
    "event_time",
    "event_type",
    "symptoms",
    "root_cause",
    "operator_action",
    "resolution_result",
    "severity",
    "tags",
    "related_dataset_id",
    "related_time_range",
)

DEFAULT_EMBED_BATCH_SIZE = 96


class SampleDataError(ValueError):
    """Raised when data/sample_case_records.json is malformed. The whole
    seed run must fail before writing anything -- validation (load_sample_cases)
    always runs to completion, checking every case, before run_seed ever
    touches the database, so a bad file can never result in a partial write.
    """


def load_sample_cases(path: Path = DEFAULT_SAMPLE_PATH) -> list[dict]:
    """Load and validate every case in the sample file. Raises
    SampleDataError (without writing anything) if the file itself, or any
    single case within it, is malformed -- this function has no DB or API
    side effects, so callers can safely retry after fixing the file.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise SampleDataError(f"{path} has no non-empty 'cases' list")

    for case in cases:
        missing = set(REQUIRED_CASE_FIELDS) - set(case.keys())
        if missing:
            raise SampleDataError(f"case {case.get('case_id', '?')!r} missing required fields: {sorted(missing)}")

    return cases


def build_case_search_text(case: dict) -> str:
    """Text to embed for similarity search.

    Deliberately excludes root_cause / operator_action / resolution_result
    (answer-shaped fields) -- see module docstring.
    """
    parts = [
        case.get("event_type") or "",
        case.get("symptoms") or "",
        case.get("tags") or "",
        case.get("severity") or "",
    ]
    return "\n".join(p for p in parts if p)


@dataclass
class SeedPlanItem:
    case_id: str
    search_text: str


def plan_seed(cases: list[dict]) -> list[SeedPlanItem]:
    return [SeedPlanItem(case_id=case["case_id"], search_text=build_case_search_text(case)) for case in cases]


@dataclass
class SeedResult:
    case_id: str
    id: int
    was_embedded: bool = False


def _needs_embedding(case: dict, content_hash: str, existing_by_case_id: dict[str, dict]) -> bool:
    """A case needs a fresh embedding call if it's new, if a prior run never
    got as far as writing an embedding for it (e.g. a crash mid-run), or if
    its search text actually changed since the stored embedding_content_hash
    was written. Deliberately NOT just "does a row already exist" -- that
    alone would silently skip re-embedding a case whose symptoms/event_type/
    tags/severity text was edited after the first seed.
    """
    existing = existing_by_case_id.get(case["case_id"])
    if existing is None:
        return True
    if existing.get("embedding") is None:
        return True
    return existing.get("embedding_content_hash") != content_hash


def run_seed(
    conn,
    cases: list[dict],
    embedding_provider: EmbeddingProvider,
    embed_batch_size: int = DEFAULT_EMBED_BATCH_SIZE,
) -> list[SeedResult]:
    """Embed and upsert every case, skipping the embedding API call for any
    case whose search text is unchanged and already has a stored embedding
    (fix: avoid redundant case embedding requests -- mirrors document_chunks'
    embedding_content_hash precedent, see app/services/hashing.py). Batches
    embedding calls (same batching convention as app/services/ingestion_rag.py);
    commits once at the end since seeding writes plain rows with no
    blue-green lifecycle/cutover concerns (case_records has no is_active
    column).
    """
    content_hash_by_case_id = {case["case_id"]: compute_embedding_content_hash(build_case_search_text(case)) for case in cases}
    existing_by_case_id = get_cases_by_case_ids(conn, list(content_hash_by_case_id.keys()))

    to_embed = [case for case in cases if _needs_embedding(case, content_hash_by_case_id[case["case_id"]], existing_by_case_id)]

    embedded_by_case_id = {}
    for i in range(0, len(to_embed), embed_batch_size):
        batch_cases = to_embed[i : i + embed_batch_size]
        texts = [build_case_search_text(case) for case in batch_cases]
        batch_result = embedding_provider.embed_batch(texts)
        for case, embedded in zip(batch_cases, batch_result.results):
            embedded_by_case_id[case["case_id"]] = embedded

    results: list[SeedResult] = []
    for case in cases:
        embedded = embedded_by_case_id.get(case["case_id"])
        row_id = upsert_case_record(
            conn,
            case_id=case["case_id"],
            site_id=case.get("site_id"),
            event_time=case.get("event_time"),
            event_type=case.get("event_type"),
            symptoms=case.get("symptoms"),
            root_cause=case.get("root_cause"),
            operator_action=case.get("operator_action"),
            resolution_result=case.get("resolution_result"),
            severity=case.get("severity"),
            tags=case.get("tags"),
            related_dataset_id=case.get("related_dataset_id"),
            related_time_range=case.get("related_time_range"),
            embedding=embedded.vector if embedded else None,
            embedding_provider=embedded.provider if embedded else None,
            embedding_model=embedded.model if embedded else None,
            embedding_dimensions=embedded.dimensions if embedded else None,
            embedding_model_version=embedded.model_version if embedded else None,
            embedding_content_hash=content_hash_by_case_id[case["case_id"]] if embedded else None,
        )
        results.append(SeedResult(case_id=case["case_id"], id=row_id, was_embedded=embedded is not None))

    conn.commit()
    return results


def dry_run(sample_path: Path = DEFAULT_SAMPLE_PATH) -> list[SeedPlanItem]:
    """No DB connection, no embedding provider call -- load+validate the
    sample file and report what a real run would process."""
    cases = load_sample_cases(sample_path)
    return plan_seed(cases)


def print_dry_run_summary(items: list[SeedPlanItem]) -> None:
    print(f"[dry-run] {len(items)} case(s) would be seeded:")
    for item in items:
        print(f"  - {item.case_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed data/sample_case_records.json into case_records.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load and validate only -- no DB connection, no embedding API calls, no writes.",
    )
    parser.add_argument("--sample-path", type=Path, default=DEFAULT_SAMPLE_PATH)
    args = parser.parse_args()

    if args.dry_run:
        items = dry_run(args.sample_path)
        print_dry_run_summary(items)
        return

    # Normal mode: real DB + real embedding provider. Imports are local so
    # `--dry-run` never needs OPENAI_API_KEY or DATABASE_URL to be set.
    from app.db import get_connection
    from app.services.embedding_provider import OpenAIEmbeddingProvider

    cases = load_sample_cases(args.sample_path)
    with get_connection() as conn:
        results = run_seed(conn, cases, OpenAIEmbeddingProvider())
    embedded_count = sum(1 for r in results if r.was_embedded)
    skipped_count = len(results) - embedded_count
    print(f"Seeded {len(results)} case(s): {embedded_count} embedded, {skipped_count} skipped (unchanged).")


if __name__ == "__main__":
    main()
