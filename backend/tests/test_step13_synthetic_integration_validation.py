"""Step 13.7 Track A: synthetic-fixture end-to-end validation against real
PostgreSQL.

THIS IS SYNTHETIC VALIDATION, NOT REAL-WORLD VALIDATION. Every row in every
fixture used here comes from scripts/synthetic_step13/generate_synthetic_step13_fixtures.py
(fixed seed=13, see scripts/synthetic_step13/README.md) -- no real EMS/BMS
data is used, downloaded, or reconstructed.

Distinct from test_step13_integration.py: that file exercises the rule/API
layer with hand-built row dicts inserted directly via SQL. This file instead
walks the CSV bytes through the actual upload endpoint
(POST /datasets/upload -> parse_and_validate_csv -> energy_timeseries),
so the ingestion contract itself (structural/row-level warnings, NULL
coercion, enum normalization) is exercised too, not just the rule engines.

Isolation: every dataset created here is uploaded with a uuid4-suffixed
`name` so it can never collide with a pre-existing or another test's
dataset. The fixture records exactly which dataset_id(s) it created and the
finalizer deletes only those precise IDs (never a LIKE-prefix sweep), then
asserts zero residual rows for exactly those IDs -- same pattern as
test_step13_integration.py's real_pg fixture.
"""

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import get_connection, get_db_dependency
from app.main import app

client = TestClient(app)

FIXTURES_DIR = Path(__file__).parent.parent / "scripts" / "synthetic_step13" / "fixtures"
if not FIXTURES_DIR.exists():
    FIXTURES_DIR = Path(__file__).parent.parent.parent / "scripts" / "synthetic_step13" / "fixtures"


@pytest.fixture(scope="module", autouse=True)
def _verify_pre_existing_datasets_untouched():
    """Same guard as test_step13_integration.py: snapshot every dataset
    that existed before this module ran and assert it is unchanged after."""
    with get_connection() as conn:
        baseline = {
            row["id"]: row["row_count"]
            for row in conn.execute(text("SELECT id, row_count FROM datasets")).mappings().all()
        }
    yield
    with get_connection() as conn:
        after = {
            row["id"]: row["row_count"]
            for row in conn.execute(text("SELECT id, row_count FROM datasets")).mappings().all()
        }
    for dataset_id, row_count in baseline.items():
        assert after.get(dataset_id) == row_count, f"pre-existing dataset {dataset_id} was modified or deleted"


@pytest.fixture
def real_pg_upload():
    created_dataset_ids: list[int] = []

    def _override():
        with get_connection() as conn:
            yield conn

    app.dependency_overrides[get_db_dependency] = _override

    def _upload(fixture_filename: str) -> dict:
        """Uploads a fixture CSV through the real /datasets/upload endpoint
        (real bytes through real ingestion), with a uuid4-suffixed name so
        it can never collide with existing data. Returns the parsed
        IngestResult body."""
        csv_path = FIXTURES_DIR / fixture_filename
        content = csv_path.read_bytes()
        unique_name = f"step13_7_synthetic_{uuid.uuid4().hex}_{fixture_filename}"
        response = client.post(
            "/datasets/upload",
            files={"file": (fixture_filename, content, "text/csv")},
            data={"name": unique_name},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        if body["dataset_id"] is not None:
            created_dataset_ids.append(body["dataset_id"])
        return body

    try:
        yield _upload
    finally:
        app.dependency_overrides.pop(get_db_dependency, None)
        with get_connection() as setup_conn:
            for dataset_id in created_dataset_ids:
                setup_conn.execute(text("DELETE FROM analysis_runs WHERE dataset_id = :id"), {"id": dataset_id})
                setup_conn.execute(text("DELETE FROM energy_timeseries WHERE dataset_id = :id"), {"id": dataset_id})
                setup_conn.execute(text("DELETE FROM datasets WHERE id = :id"), {"id": dataset_id})
            setup_conn.commit()

            for dataset_id in created_dataset_ids:
                remaining_dataset = setup_conn.execute(
                    text("SELECT COUNT(*) FROM datasets WHERE id = :id"), {"id": dataset_id}
                ).scalar_one()
                remaining_timeseries = setup_conn.execute(
                    text("SELECT COUNT(*) FROM energy_timeseries WHERE dataset_id = :id"), {"id": dataset_id}
                ).scalar_one()
                remaining_runs = setup_conn.execute(
                    text("SELECT COUNT(*) FROM analysis_runs WHERE dataset_id = :id"), {"id": dataset_id}
                ).scalar_one()
                assert (remaining_dataset, remaining_timeseries, remaining_runs) == (0, 0, 0), (
                    f"cleanup left residual rows for dataset_id={dataset_id}"
                )


# ---------------------------------------------------------------------------
# 1. Synthetic CSV ingestion
# ---------------------------------------------------------------------------


def test_happy_path_multisite_ingests_cleanly(real_pg_upload):
    result = real_pg_upload("happy_path_multisite.csv")
    assert result["status"] == "success"
    assert result["row_count"] == 192
    assert result["inserted_count"] == 192
    assert result["warnings"] == []


# ---------------------------------------------------------------------------
# 2. Battery Scheduling -- API-level only (no frontend UI exists for this
#    endpoint; see README.md audit note)
# ---------------------------------------------------------------------------


def test_battery_scheduling_api_on_happy_path(real_pg_upload):
    result = real_pg_upload("happy_path_multisite.csv")
    dataset_id = result["dataset_id"]

    response = client.post(f"/datasets/{dataset_id}/schedule")
    assert response.status_code == 200, response.text
    body = response.json()["result"]
    actions = [r["action"] for r in body["recommendations"]]
    assert len(actions) == 192
    assert actions.count("charge") == 20
    assert actions.count("hold") == 172


# ---------------------------------------------------------------------------
# 3. Cost Estimation -- API level (dashboard rendering covered separately
#    in Track B, not by this automated test)
# ---------------------------------------------------------------------------


def test_cost_estimation_api_on_happy_path(real_pg_upload):
    result = real_pg_upload("happy_path_multisite.csv")
    dataset_id = result["dataset_id"]

    response = client.post(f"/datasets/{dataset_id}/cost", params={"max_expected_interval_hours": 1.0})
    assert response.status_code == 200, response.text
    body = response.json()["result"]
    assert body["site_count"] == 2
    assert round(body["dataset_aggregate"]["total_energy_cost"], 2) == 4064.79


# ---------------------------------------------------------------------------
# 4. Green Operations Index -- API level (dashboard rendering covered
#    separately in Track B, not by this automated test)
# ---------------------------------------------------------------------------


def test_green_operations_index_api_on_happy_path(real_pg_upload):
    result = real_pg_upload("happy_path_multisite.csv")
    dataset_id = result["dataset_id"]

    response = client.post(
        f"/datasets/{dataset_id}/green-operations-index", params={"max_expected_interval_hours": 1.0}
    )
    assert response.status_code == 200, response.text
    body = response.json()["result"]
    assert body["site_count"] == 2
    for site in body["per_site"]:
        statuses = {c["component"]: c["status"] for c in site["components"]}
        assert set(statuses.values()) == {"computed"}


def test_second_life_bonus_confirmed_safe_path(real_pg_upload):
    result = real_pg_upload("battery_second_life.csv")
    dataset_id = result["dataset_id"]

    response = client.post(
        f"/datasets/{dataset_id}/green-operations-index", params={"max_expected_interval_hours": 1.0}
    )
    assert response.status_code == 200, response.text
    body = response.json()["result"]
    assert body["per_site"][0]["second_life_bonus"] == 10.0


# ---------------------------------------------------------------------------
# 5. Warning / insufficient-data path
# ---------------------------------------------------------------------------


def test_missing_optional_fields_produces_warnings_and_insufficient_data(real_pg_upload):
    result = real_pg_upload("missing_optional_fields.csv")
    assert result["status"] == "success_with_warnings"
    assert len(result["warnings"]) == 20
    assert all(w["issue"] == "column missing in CSV" for w in result["warnings"])

    dataset_id = result["dataset_id"]
    response = client.post(
        f"/datasets/{dataset_id}/green-operations-index", params={"max_expected_interval_hours": 1.0}
    )
    assert response.status_code == 200, response.text
    site = response.json()["result"]["per_site"][0]
    statuses = {c["component"]: c["status"] for c in site["components"]}
    assert statuses["pv_utilization"] == "insufficient_data"
    assert statuses["grid_dependency"] == "insufficient_data"
    assert statuses["battery_health"] == "insufficient_data"
    assert statuses["battery_operation"] == "computed"


def test_all_invalid_timestamps_persist_zero_rows_and_all_dimensions_pending(real_pg_upload):
    result = real_pg_upload("timestamp_edge_cases_all_invalid.csv")
    assert result["status"] == "success_with_warnings"
    assert result["row_count"] == 0
    assert len(result["warnings"]) == 10

    dataset_id = result["dataset_id"]
    response = client.post(
        f"/datasets/{dataset_id}/green-operations-index", params={"max_expected_interval_hours": 1.0}
    )
    assert response.status_code == 200, response.text
    assert response.json()["result"]["site_count"] == 0
