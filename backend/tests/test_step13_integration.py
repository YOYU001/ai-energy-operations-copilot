"""Step 13 Sub-step 13.4: real-PostgreSQL integration validation for
Battery Scheduling / Cost Estimation / Green Operations Index.

Scope, deliberately distinct from what 13.2/13.3 already proved with pure
functions and FakeConnection:
  - real psycopg2 NUMERIC -> decimal.Decimal type coercion actually gets
    normalized correctly through the full query -> service -> persistence
    -> API response pipeline (the bug this sub-step's planning discovered)
  - the real analysis_runs UNIQUE(dataset_id, analysis_type, rule_version)
    constraint actually deduplicates/differentiates runs the way the
    canonicalized identity design intends
  - full POST -> persisted row -> GET -> response consistency against a
    real database, not a scripted fake

This is REAL POSTGRESQL INTEGRATION VALIDATION using controlled synthetic
rows -- it is NOT real dataset validation (no representative real-world
energy timeseries dataset exists yet; see docs/step13_rules_and_api_design.md
and PROGRESS.md Known Issues). Real dataset validation remains pending
because no suitable real-world timeseries dataset currently exists, and is
deferred to its own future sub-step.

Isolation: every dataset this file creates gets a unique uuid4-suffixed
name; each fixture records the exact dataset_id(s) it created and the
finalizer deletes only those precise IDs (never a LIKE-prefix sweep), then
asserts zero residual rows for exactly those IDs. A module-scoped fixture
separately snapshots every pre-existing dataset's (id, row_count) before
any test runs and asserts it is byte-for-byte unchanged after the whole
module finishes, independent of test execution order.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import get_connection, get_db_dependency
from app.main import _cost_rule_version, _green_ops_rule_version, app
from app.services.battery_scheduling import ANALYSIS_TYPE as SCHEDULE_TYPE
from app.services.battery_scheduling import RULE_VERSION as SCHEDULE_VERSION
from app.services.cost_estimation import ANALYSIS_TYPE as COST_TYPE
from app.services.green_operations_index import ANALYSIS_TYPE as GREEN_OPS_TYPE
from app.services.rule_engine import ANALYSIS_TYPE as STEP9_TYPE
from app.services.rule_engine import RULE_VERSION as STEP9_VERSION

client = TestClient(app)

BASE_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _hour(h):
    return BASE_TS + timedelta(hours=h)


class _DatasetFactory:
    def __init__(self, conn):
        self._conn = conn
        self.created_dataset_ids: list[int] = []

    def create_dataset(self, rows: list[dict], name_hint: str = "case") -> int:
        unique_name = f"step13_pg_integration_{uuid.uuid4().hex}_{name_hint}"
        dataset_id = self._conn.execute(
            text(
                """
                INSERT INTO datasets (name, file_name, description, row_count, created_at)
                VALUES (:name, :name, 'step13 real-postgres integration validation (not real-world data)',
                        :row_count, :created_at)
                RETURNING id
                """
            ),
            {"name": unique_name, "row_count": len(rows), "created_at": datetime.now(timezone.utc)},
        ).scalar_one()
        self.created_dataset_ids.append(dataset_id)

        for row in rows:
            payload = dict(row)
            payload["dataset_id"] = dataset_id
            columns = ", ".join(payload.keys())
            placeholders = ", ".join(f":{k}" for k in payload.keys())
            self._conn.execute(text(f"INSERT INTO energy_timeseries ({columns}) VALUES ({placeholders})"), payload)

        self._conn.commit()
        return dataset_id


@pytest.fixture(scope="module", autouse=True)
def _verify_pre_existing_datasets_untouched():
    """Snapshots every dataset that existed before this module ran and
    asserts it is unchanged (by id and row_count) after every test in this
    module -- and its own per-test cleanup -- has finished, regardless of
    execution order."""
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
def real_pg():
    with get_connection() as setup_conn:
        factory = _DatasetFactory(setup_conn)

        def _override():
            with get_connection() as conn:
                yield conn

        app.dependency_overrides[get_db_dependency] = _override
        try:
            yield factory
        finally:
            app.dependency_overrides.pop(get_db_dependency, None)
            for dataset_id in factory.created_dataset_ids:
                setup_conn.execute(text("DELETE FROM analysis_runs WHERE dataset_id = :id"), {"id": dataset_id})
                setup_conn.execute(text("DELETE FROM energy_timeseries WHERE dataset_id = :id"), {"id": dataset_id})
                setup_conn.execute(text("DELETE FROM datasets WHERE id = :id"), {"id": dataset_id})
            setup_conn.commit()

            for dataset_id in factory.created_dataset_ids:
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


def _row(h, site="site_a", **overrides):
    base = {
        "timestamp": _hour(h),
        "site_id": site,
        "electricity_price": 5.0,
        "grid_import_kw": 10.0,
        "grid_export_kw": 0.0,
        "contract_capacity_kw": 100.0,
        "battery_soc": 50.0,
        "battery_soh": 90.0,
        "battery_power_kw": 0.0,
        "battery_temperature": 25.0,
        "battery_health_status": "normal",
        "battery_is_second_life": False,
        "pv_actual_kw": 5.0,
        "load_kw": 10.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Step 9 regression: the Decimal fix must not have been a Step-13-only fix
# ---------------------------------------------------------------------------


def test_step9_analysis_endpoint_against_real_postgres_with_numeric_columns(real_pg):
    rows = [_row(h, electricity_price=p) for h, p in enumerate([3.0, 3.0, 3.0, 7.0, 7.0, 7.0])]
    dataset_id = real_pg.create_dataset(rows, "step9-regression")

    response = client.post(f"/datasets/{dataset_id}/analysis")

    assert response.status_code == 200
    body = response.json()
    assert body["analysis_type"] == STEP9_TYPE
    assert body["rule_version"] == STEP9_VERSION
    assert isinstance(body["result"]["flagged_row_count"], int)


# ---------------------------------------------------------------------------
# Full roundtrip: POST -> persisted row -> GET -> consistency
# ---------------------------------------------------------------------------


def test_schedule_full_roundtrip_against_real_postgres(real_pg):
    rows = [_row(h) for h in range(6)]
    dataset_id = real_pg.create_dataset(rows, "schedule-roundtrip")

    post_response = client.post(f"/datasets/{dataset_id}/schedule")
    assert post_response.status_code == 200
    post_body = post_response.json()

    with get_connection() as conn:
        persisted = conn.execute(
            text("SELECT * FROM analysis_runs WHERE dataset_id = :id AND analysis_type = :t"),
            {"id": dataset_id, "t": SCHEDULE_TYPE},
        ).mappings().first()
    assert persisted is not None
    assert persisted["rule_version"] == SCHEDULE_VERSION
    assert persisted["id"] == post_body["analysis_run_id"]

    get_response = client.get(f"/datasets/{dataset_id}/schedule")
    assert get_response.status_code == 200
    assert get_response.json() == post_body


def test_cost_full_roundtrip_against_real_postgres(real_pg):
    """Multi-site: also covers per-site / dataset_aggregate correctness in
    one pass (docs/step13_rules_and_api_design.md 4.2 formula, verified by
    direct execution during planning: site_a=30.0, site_b=760.0, aggregate=790.0)."""
    rows = [
        _row(0, site="site_a", electricity_price=3.0, grid_import_kw=10.0),
        _row(1, site="site_a", electricity_price=3.0, grid_import_kw=10.0),
        _row(0, site="site_b", electricity_price=8.0, grid_import_kw=95.0),
        _row(1, site="site_b", electricity_price=8.0, grid_import_kw=95.0),
    ]
    dataset_id = real_pg.create_dataset(rows, "cost-roundtrip")

    post_response = client.post(f"/datasets/{dataset_id}/cost", params={"max_expected_interval_hours": 6.0})
    assert post_response.status_code == 200
    post_body = post_response.json()

    site_a = next(s for s in post_body["result"]["per_site"] if s["site_id"] == "site_a")
    site_b = next(s for s in post_body["result"]["per_site"] if s["site_id"] == "site_b")
    assert site_a["total_energy_cost"] == 30.0
    assert site_b["total_energy_cost"] == 760.0
    assert post_body["result"]["dataset_aggregate"]["total_energy_cost"] == 790.0
    assert post_body["result"]["max_expected_interval_hours"] == 6.0

    with get_connection() as conn:
        persisted = conn.execute(
            text("SELECT * FROM analysis_runs WHERE dataset_id = :id AND analysis_type = :t"),
            {"id": dataset_id, "t": COST_TYPE},
        ).mappings().first()
    assert persisted is not None
    assert persisted["rule_version"] == _cost_rule_version(6.0)
    assert persisted["id"] == post_body["analysis_run_id"]

    get_response = client.get(f"/datasets/{dataset_id}/cost", params={"max_expected_interval_hours": 6.0})
    assert get_response.status_code == 200
    assert get_response.json() == post_body


def test_green_operations_index_full_roundtrip_against_real_postgres(real_pg):
    """Same multi-site data as the cost roundtrip; verified by direct
    execution during planning: site_a grid_dependency=20.0,
    site_b grid_dependency=0.0, dataset_aggregate=10.0 (duration-weighted
    average, both sites have 1.0h equal eligible duration)."""
    rows = [
        _row(0, site="site_a", electricity_price=3.0, grid_import_kw=10.0),
        _row(1, site="site_a", electricity_price=3.0, grid_import_kw=10.0),
        _row(0, site="site_b", electricity_price=8.0, grid_import_kw=95.0),
        _row(1, site="site_b", electricity_price=8.0, grid_import_kw=95.0),
    ]
    dataset_id = real_pg.create_dataset(rows, "greenops-roundtrip")

    post_response = client.post(
        f"/datasets/{dataset_id}/green-operations-index", params={"max_expected_interval_hours": 6.0}
    )
    assert post_response.status_code == 200
    post_body = post_response.json()

    def _grid_dependency(site_result):
        return next(c for c in site_result["components"] if c["component"] == "grid_dependency")

    site_a = next(s for s in post_body["result"]["per_site"] if s["site_id"] == "site_a")
    site_b = next(s for s in post_body["result"]["per_site"] if s["site_id"] == "site_b")
    assert _grid_dependency(site_a)["score"] == 20.0
    assert _grid_dependency(site_b)["score"] == 0.0
    assert _grid_dependency(post_body["result"]["dataset_aggregate"])["score"] == 10.0

    with get_connection() as conn:
        persisted = conn.execute(
            text("SELECT * FROM analysis_runs WHERE dataset_id = :id AND analysis_type = :t"),
            {"id": dataset_id, "t": GREEN_OPS_TYPE},
        ).mappings().first()
    assert persisted is not None
    assert persisted["rule_version"] == _green_ops_rule_version(6.0)

    get_response = client.get(
        f"/datasets/{dataset_id}/green-operations-index", params={"max_expected_interval_hours": 6.0}
    )
    assert get_response.status_code == 200
    assert get_response.json() == post_body


# ---------------------------------------------------------------------------
# Parameterized-identity validation against the real UNIQUE constraint
# ---------------------------------------------------------------------------

_PARAM_ENDPOINTS = [
    ("cost", COST_TYPE, _cost_rule_version),
    ("green-operations-index", GREEN_OPS_TYPE, _green_ops_rule_version),
]


@pytest.mark.parametrize("path, analysis_type, rule_version_fn", _PARAM_ENDPOINTS)
def test_identity_6_6point0_6e0_hit_same_real_run(real_pg, path, analysis_type, rule_version_fn):
    rows = [_row(0), _row(1)]
    dataset_id = real_pg.create_dataset(rows, f"{path}-identity-same")

    run_ids = set()
    for literal in ("6", "6.0", "6e0"):
        response = client.post(f"/datasets/{dataset_id}/{path}", params={"max_expected_interval_hours": literal})
        assert response.status_code == 200
        run_ids.add(response.json()["analysis_run_id"])

    assert len(run_ids) == 1

    with get_connection() as conn:
        row_count = conn.execute(
            text("SELECT COUNT(*) FROM analysis_runs WHERE dataset_id = :id AND analysis_type = :t"),
            {"id": dataset_id, "t": analysis_type},
        ).scalar_one()
        stored_rule_version = conn.execute(
            text("SELECT rule_version FROM analysis_runs WHERE dataset_id = :id AND analysis_type = :t"),
            {"id": dataset_id, "t": analysis_type},
        ).scalar_one()
    assert row_count == 1
    assert stored_rule_version == rule_version_fn(6.0)


@pytest.mark.parametrize("path, analysis_type, rule_version_fn", _PARAM_ENDPOINTS)
def test_identity_different_params_create_different_real_runs(real_pg, path, analysis_type, rule_version_fn):
    rows = [_row(0), _row(1)]
    dataset_id = real_pg.create_dataset(rows, f"{path}-identity-diff")

    response_a = client.post(f"/datasets/{dataset_id}/{path}", params={"max_expected_interval_hours": 6})
    response_b = client.post(f"/datasets/{dataset_id}/{path}", params={"max_expected_interval_hours": 2})
    assert response_a.status_code == 200
    assert response_b.status_code == 200
    assert response_a.json()["analysis_run_id"] != response_b.json()["analysis_run_id"]

    with get_connection() as conn:
        row_count = conn.execute(
            text("SELECT COUNT(*) FROM analysis_runs WHERE dataset_id = :id AND analysis_type = :t"),
            {"id": dataset_id, "t": analysis_type},
        ).scalar_one()
        stored_versions = {
            r["rule_version"]
            for r in conn.execute(
                text("SELECT rule_version FROM analysis_runs WHERE dataset_id = :id AND analysis_type = :t"),
                {"id": dataset_id, "t": analysis_type},
            ).mappings().all()
        }
    assert row_count == 2
    assert stored_versions == {rule_version_fn(6.0), rule_version_fn(2.0)}


@pytest.mark.parametrize("path", ["cost", "green-operations-index"])
def test_get_404_for_unused_parameter_value(real_pg, path):
    rows = [_row(0), _row(1)]
    dataset_id = real_pg.create_dataset(rows, f"{path}-get-404")

    post_response = client.post(f"/datasets/{dataset_id}/{path}", params={"max_expected_interval_hours": 6})
    assert post_response.status_code == 200

    get_response = client.get(f"/datasets/{dataset_id}/{path}", params={"max_expected_interval_hours": 3})
    assert get_response.status_code == 404


# ---------------------------------------------------------------------------
# Null-value scenarios (see docs terminology fix: all_null / partial_null /
# insufficient_data are three distinct things, never conflated)
# ---------------------------------------------------------------------------


def test_all_null_step13_columns_returns_200_with_hold_or_insufficient_data(real_pg):
    null_columns = {
        "electricity_price": None,
        "grid_import_kw": None,
        "grid_export_kw": None,
        "contract_capacity_kw": None,
        "battery_soc": None,
        "battery_soh": None,
        "battery_power_kw": None,
        "battery_temperature": None,
        "battery_health_status": None,
        "battery_is_second_life": None,
        "pv_actual_kw": None,
        "load_kw": None,
    }
    rows = [_row(h, **null_columns) for h in range(3)]
    dataset_id = real_pg.create_dataset(rows, "all-null")

    schedule = client.post(f"/datasets/{dataset_id}/schedule").json()
    assert all(r["action"] == "hold" for r in schedule["result"]["recommendations"])
    assert all("insufficient_row_data" in r["warnings"] for r in schedule["result"]["recommendations"])

    cost = client.post(f"/datasets/{dataset_id}/cost", params={"max_expected_interval_hours": 6}).json()
    assert cost["result"]["dataset_aggregate"]["total_energy_cost"] == 0.0

    green_ops = client.post(
        f"/datasets/{dataset_id}/green-operations-index", params={"max_expected_interval_hours": 6}
    ).json()
    assert all(c["status"] == "insufficient_data" and c["score"] is None for c in green_ops["result"]["dataset_aggregate"]["components"])
    assert green_ops["result"]["dataset_aggregate"]["total_score"] is None


def test_partial_null_step13_columns_respects_three_state_eligibility(real_pg):
    """docs/step13_rules_and_api_design.md's battery_health_risk fix: a row
    with ONLY temperature present and triggering must still be eligible+
    flagged; a row with ONLY temperature present and NOT triggering (soh/
    health_status missing) must be ineligible, not silently counted as safe."""
    # battery_health component eligibility is the UNION of battery_health_risk
    # and low_soc_risk (both feed this component); battery_soc must also be
    # nulled on the "should be ineligible" row, or low_soc_risk alone (soc
    # present and safe) would make the interval eligible via that signal.
    rows = [
        _row(0, battery_temperature=45.0, battery_soh=None, battery_health_status=None),  # triggers -> eligible+flagged
        _row(1, battery_temperature=20.0, battery_soh=90.0, battery_health_status="normal"),  # all known, safe -> eligible, not flagged
        _row(2, battery_temperature=20.0, battery_soh=None, battery_health_status=None, battery_soc=None),  # partial, not triggered, low_soc_risk also unavailable -> ineligible
        _row(3),  # last row, excluded
    ]
    dataset_id = real_pg.create_dataset(rows, "partial-null")

    response = client.post(
        f"/datasets/{dataset_id}/green-operations-index", params={"max_expected_interval_hours": 6}
    )
    assert response.status_code == 200
    health = next(
        c
        for c in response.json()["result"]["dataset_aggregate"]["components"]
        if c["component"] == "battery_health"
    )
    assert health["eligible_duration_hours"] == 2.0  # interval 1 + interval 2 only; interval 3 is ineligible/unknown
    assert health["flagged_duration_hours"] == 1.0  # interval 1 only
    assert health["score"] == 12.5  # 25 * (1 - 1/2)


def test_empty_dataset_zero_rows_returns_200_and_is_persisted(real_pg):
    dataset_id = real_pg.create_dataset([], "empty")

    response = client.post(f"/datasets/{dataset_id}/cost", params={"max_expected_interval_hours": 6})

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["site_count"] == 0

    with get_connection() as conn:
        persisted_count = conn.execute(
            text("SELECT COUNT(*) FROM analysis_runs WHERE dataset_id = :id"), {"id": dataset_id}
        ).scalar_one()
    assert persisted_count == 1


# ---------------------------------------------------------------------------
# Second-life battery scenarios (controlled synthetic rows, real Postgres)
# ---------------------------------------------------------------------------


def test_second_life_battery_safe_scenario_against_real_postgres(real_pg):
    rows = [_row(h, battery_is_second_life=True) for h in range(6)]
    dataset_id = real_pg.create_dataset(rows, "second-life-safe")

    response = client.post(
        f"/datasets/{dataset_id}/green-operations-index", params={"max_expected_interval_hours": 6}
    )

    assert response.status_code == 200
    assert response.json()["result"]["dataset_aggregate"]["second_life_bonus"] == 10.0


def test_second_life_battery_unsafe_scenario_against_real_postgres(real_pg):
    rows = [_row(h, battery_is_second_life=True) for h in range(6)]
    rows[4] = _row(4, battery_is_second_life=True, battery_temperature=45.0)
    dataset_id = real_pg.create_dataset(rows, "second-life-unsafe")

    response = client.post(
        f"/datasets/{dataset_id}/green-operations-index", params={"max_expected_interval_hours": 6}
    )

    assert response.status_code == 200
    assert response.json()["result"]["dataset_aggregate"]["second_life_bonus"] == 0.0
