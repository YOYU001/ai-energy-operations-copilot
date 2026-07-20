"""db-bootstrap: start Docker Postgres+pgvector, apply database/schema.sql, and
actually verify the extension and expected tables exist -- never assume
success just because a command returned exit code 0.

Run from the project root:
    python .claude/skills/db-bootstrap/scripts/bootstrap.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCHEMA_PATH = ROOT / "database" / "schema.sql"
ENV_PATH = ROOT / ".env"

EXPECTED_TABLES = [
    "documents",
    "document_chunks",
    "datasets",
    "energy_timeseries",
    "case_records",
    "analysis_runs",
    "chat_messages",
]

DB_READY_TIMEOUT_SECONDS = 30


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kwargs)


def _wait_for_db_ready() -> bool:
    deadline = time.time() + DB_READY_TIMEOUT_SECONDS
    while time.time() < deadline:
        result = _run(["docker", "compose", "exec", "-T", "db", "pg_isready"])
        if result.returncode == 0:
            return True
        time.sleep(2)
    return False


def _apply_schema() -> tuple[bool, str]:
    if not SCHEMA_PATH.exists():
        return False, f"schema file not found: {SCHEMA_PATH}"
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "ai_copilot", "-d", "ai_copilot", "-v", "ON_ERROR_STOP=1"],
        cwd=ROOT,
        input=schema_sql,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, result.stderr.strip()
    return True, result.stdout.strip()


def _verify() -> dict:
    from dotenv import load_dotenv

    load_dotenv(ENV_PATH)
    import os

    from sqlalchemy import create_engine, text as sql_text

    engine = create_engine(os.environ["DATABASE_URL"])
    report: dict = {"extension_vector": False, "tables": {}}
    with engine.connect() as conn:
        ext_row = conn.execute(sql_text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).fetchone()
        report["extension_vector"] = ext_row is not None

        existing = {
            row[0]
            for row in conn.execute(
                sql_text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
            ).fetchall()
        }
        for table in EXPECTED_TABLES:
            report["tables"][table] = table in existing
    return report


def main() -> int:
    if not ENV_PATH.exists():
        print(f"[db-bootstrap] .env not found at {ENV_PATH} -- copy .env.example to .env and fill it in first.")
        return 1

    print("[db-bootstrap] starting docker compose up -d ...")
    up_result = _run(["docker", "compose", "up", "-d"])
    if up_result.returncode != 0:
        print(f"[db-bootstrap] FAILED to start containers:\n{up_result.stderr}")
        return 1

    print("[db-bootstrap] waiting for database to be ready ...")
    if not _wait_for_db_ready():
        print(f"[db-bootstrap] FAILED: database did not become ready within {DB_READY_TIMEOUT_SECONDS}s")
        return 1

    print("[db-bootstrap] applying database/schema.sql ...")
    applied, detail = _apply_schema()
    if not applied:
        print(f"[db-bootstrap] FAILED to apply schema:\n{detail}")
        return 1
    print(f"[db-bootstrap] schema apply output:\n{detail}")

    print("[db-bootstrap] verifying extension and tables ...")
    report = _verify()

    print(f"\n[db-bootstrap] pgvector extension present: {report['extension_vector']}")
    missing = [t for t, present in report["tables"].items() for t in [t] if not present]
    for table, present in report["tables"].items():
        status = "OK" if present else "MISSING"
        print(f"  - {table}: {status}")

    if not report["extension_vector"] or missing:
        print("\n[db-bootstrap] VERIFICATION FAILED -- schema did not fully apply. See missing items above.")
        return 1

    print("\n[db-bootstrap] SUCCESS -- extension and all 7 tables confirmed present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
