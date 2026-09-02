from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.datasets_queries import SUMMARY_NUMERIC_COLUMNS
from app.db import get_db_dependency
from app.main import app
from app.services import analysis_report, battery_scheduling, cost_estimation, green_operations_index
from app.services.rule_engine import ANALYSIS_TYPE as ANOMALY_ANALYSIS_TYPE, RULE_VERSION as ANOMALY_RULE_VERSION
from tests.fakes import FakeConnection

RUN_AT = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)


def _dataset_row(dataset_id=1, row_count=96):
    return {
        "id": dataset_id,
        "name": "Demo",
        "file_name": "demo.csv",
        "description": None,
        "row_count": row_count,
        "start_time": None,
        "end_time": None,
        "created_at": None,
    }


def _summary_row(row_count=96, site_count=1):
    row = {
        "row_count": row_count,
        "site_count": site_count,
        "start_time": datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc),
        "end_time": datetime(2026, 3, 1, 23, 45, tzinfo=timezone.utc),
    }
    for col in SUMMARY_NUMERIC_COLUMNS:
        row[f"{col}_min"] = 1.0
        row[f"{col}_mean"] = 2.0
        row[f"{col}_max"] = 3.0
    return row


def _anomaly_run_row(run_id=11):
    result = {
        "rule": "battery_should_discharge_but_did_not",
        "rule_version": ANOMALY_RULE_VERSION,
        "price_threshold": {
            "mode": "percentile",
            "threshold": None,
            "non_null_sample_count": 96,
            "distinct_price_count": 3,
            "reason": None,
        },
        "input_row_count": 96,
        "evaluated_row_count": 96,
        "flagged_row_count": 1,
        "anomalies": [
            {
                "anomaly_type": "battery_should_discharge_but_did_not",
                "severity": "high",
                "timestamp": RUN_AT.isoformat(),
                "evidence": {
                    "electricity_price": None,
                    "high_price_threshold": None,
                    "price_threshold_mode": "percentile",
                    "grid_import_kw": None,
                    "contract_capacity_kw": None,
                    "contract_capacity_ratio": None,
                    "battery_soc": None,
                    "battery_power_kw": None,
                    "non_null_price_sample_count": 96,
                    "distinct_price_count": 3,
                },
                "suggested_actions": ["檢查 BMS 放電授權"],
            }
        ],
    }
    return {
        "id": run_id,
        "dataset_id": 1,
        "analysis_type": ANOMALY_ANALYSIS_TYPE,
        "rule_version": ANOMALY_RULE_VERSION,
        "result_json": result,
        "created_at": RUN_AT,
    }


def _schedule_run_row(run_id=12):
    result = {
        "rule": "battery_scheduling",
        "rule_version": battery_scheduling.RULE_VERSION,
        "price_threshold": {
            "mode": "percentile",
            "low_threshold": 2.0,
            "high_threshold": 8.0,
            "non_null_sample_count": 96,
            "distinct_price_count": 3,
            "reason": None,
        },
        "input_row_count": 96,
        "evaluated_row_count": 96,
        "recommendations": [
            {"timestamp": RUN_AT.isoformat(), "action": "charge", "reason": "low", "price_classification": "low", "warnings": []},
            {"timestamp": RUN_AT.isoformat(), "action": "hold", "reason": "n/a", "price_classification": "neutral", "warnings": []},
        ],
    }
    return {
        "id": run_id,
        "dataset_id": 1,
        "analysis_type": battery_scheduling.ANALYSIS_TYPE,
        "rule_version": battery_scheduling.RULE_VERSION,
        "result_json": result,
        "created_at": RUN_AT,
    }


def _cost_run_row(run_id=13):
    agg = {
        "site_id": "__dataset__",
        "row_count": 96,
        "interval_count": 95,
        "intervals": [],
        "total_energy_cost": 1234.5,
        "total_arbitrage_saving": 67.8,
        "over_contract_penalty_flags": [],
        "warnings": [],
        "limitations": [],
    }
    result = {
        "rule": "cost_estimation",
        "rule_version": f"{cost_estimation.RULE_VERSION}+max_gap_hours=6.0",
        "max_expected_interval_hours": 6.0,
        "site_count": 1,
        "per_site": [dict(agg, site_id="site_a")],
        "dataset_aggregate": agg,
    }
    return {
        "id": run_id,
        "dataset_id": 1,
        "analysis_type": cost_estimation.ANALYSIS_TYPE,
        "rule_version": result["rule_version"],
        "result_json": result,
        "created_at": RUN_AT,
    }


def _green_ops_run_row(run_id=14):
    site = {
        "site_id": "__dataset__",
        "components": [
            {"component": "pv_utilization", "max_score": 25.0, "score": 20.0, "status": "computed", "eligible_duration_hours": None, "flagged_duration_hours": None, "penalty_reasons": []},
        ],
        "second_life_bonus": 5.0,
        "total_score": 82.5,
        "warnings": [],
    }
    result = {
        "rule": "green_operations_index",
        "rule_version": f"{green_operations_index.RULE_VERSION}+max_gap_hours=6.0",
        "max_expected_interval_hours": 6.0,
        "site_count": 1,
        "per_site": [site],
        "dataset_aggregate": site,
    }
    return {
        "id": run_id,
        "dataset_id": 1,
        "analysis_type": green_operations_index.ANALYSIS_TYPE,
        "rule_version": result["rule_version"],
        "result_json": result,
        "created_at": RUN_AT,
    }


_BASE_SUMMARY = {
    "row_count": 96,
    "site_count": 1,
    "start_time": datetime(2026, 3, 1, tzinfo=timezone.utc),
    "end_time": datetime(2026, 3, 1, 23, 45, tzinfo=timezone.utc),
    "columns": {},
}


def _report_run_row(run_id=99, **subs):
    """Build a stored report row by actually running build_analysis_report,
    so the shape always matches what _report_run_to_response validates. The
    FakeConnection returns this canned row from the INSERT ... RETURNING, so
    its embedded report must reflect the same sub-analyses the endpoint was
    handed for the assertion on section statuses to be meaningful."""
    result = analysis_report.build_analysis_report(
        dataset={"id": 1, "name": "Demo"},
        summary=_BASE_SUMMARY,
        generated_at=RUN_AT,
        **subs,
    )
    return {
        "id": run_id,
        "dataset_id": 1,
        "analysis_type": analysis_report.ANALYSIS_TYPE,
        "rule_version": analysis_report.RULE_VERSION,
        "result_json": result.model_dump(mode="json"),
        "created_at": RUN_AT,
    }


def _all_subs():
    from app.schemas import (
        BatteryDischargeAnalysisResult,
        CostAnalysisResult,
        GreenOpsAnalysisResult,
        ScheduleAnalysisResult,
    )

    return {
        "anomaly": analysis_report.SubAnalysis(11, RUN_AT, BatteryDischargeAnalysisResult.model_validate(_anomaly_run_row()["result_json"])),
        "schedule": analysis_report.SubAnalysis(12, RUN_AT, ScheduleAnalysisResult.model_validate(_schedule_run_row()["result_json"])),
        "cost": analysis_report.SubAnalysis(13, RUN_AT, CostAnalysisResult.model_validate(_cost_run_row()["result_json"])),
        "green_ops": analysis_report.SubAnalysis(14, RUN_AT, GreenOpsAnalysisResult.model_validate(_green_ops_run_row()["result_json"])),
    }


def _use(responses):
    def _fake():
        yield FakeConnection(responses=responses)

    app.dependency_overrides[get_db_dependency] = _fake


def _use_conn(conn):
    def _fake():
        yield conn

    app.dependency_overrides[get_db_dependency] = _fake


def _clear():
    app.dependency_overrides.pop(get_db_dependency, None)


def test_get_report_404_when_dataset_not_found():
    _use([[]])
    try:
        r = TestClient(app).get("/datasets/999/report")
    finally:
        _clear()
    assert r.status_code == 404


def test_get_report_404_when_not_yet_generated():
    _use([[_dataset_row()], []])
    try:
        r = TestClient(app).get("/datasets/1/report")
    finally:
        _clear()
    assert r.status_code == 404


def test_get_report_returns_existing():
    _use([[_dataset_row()], [_report_run_row()]])
    try:
        r = TestClient(app).get("/datasets/1/report")
    finally:
        _clear()
    assert r.status_code == 200
    body = r.json()
    assert body["analysis_type"] == analysis_report.ANALYSIS_TYPE
    assert body["result"]["sections"][0]["key"] == "dataset_overview"


def test_post_report_first_run_gathers_inserts_and_commits():
    conn = FakeConnection(
        responses=[
            [_dataset_row()],      # get_dataset_by_id
            [],                    # get_analysis_run (no existing report)
            [_summary_row()],      # get_dataset_summary
            [_anomaly_run_row(), _schedule_run_row(), _cost_run_row(), _green_ops_run_row()],  # get_analysis_runs_for_dataset
            [_report_run_row(**_all_subs())],   # insert_analysis_run
        ]
    )
    _use_conn(conn)
    try:
        r = TestClient(app).post("/datasets/1/report")
    finally:
        _clear()
    assert r.status_code == 200
    assert conn.committed is True
    sections = {s["key"]: s for s in r.json()["result"]["sections"]}
    for key in ("anomaly_diagnosis", "battery_schedule", "cost_estimate", "green_operations_index"):
        assert sections[key]["status"] == "included"


def test_post_report_no_sub_analyses_still_succeeds_with_all_not_run():
    conn = FakeConnection(
        responses=[
            [_dataset_row()],
            [],
            [_summary_row()],
            [],                    # no sub-analysis runs at all
            [_report_run_row()],
        ]
    )
    _use_conn(conn)
    try:
        r = TestClient(app).post("/datasets/1/report")
    finally:
        _clear()
    assert r.status_code == 200
    assert conn.committed is True


def test_post_report_partial_sub_analyses_reflects_missing_at_endpoint():
    subs = _all_subs()
    partial = {"anomaly": subs["anomaly"], "cost": subs["cost"]}  # schedule + green ops missing
    conn = FakeConnection(
        responses=[
            [_dataset_row()],                              # get_dataset_by_id
            [],                                            # get_analysis_run (no existing report)
            [_summary_row()],                              # get_dataset_summary
            [_anomaly_run_row(), _cost_run_row()],         # get_analysis_runs_for_dataset (2 of 4)
            [_report_run_row(**partial)],                  # insert_analysis_run
        ]
    )
    _use_conn(conn)
    try:
        r = TestClient(app).post("/datasets/1/report")
    finally:
        _clear()
    assert r.status_code == 200
    assert conn.committed is True
    body = r.json()["result"]
    sections = {s["key"]: s["status"] for s in body["sections"]}
    assert sections["anomaly_diagnosis"] == "included"
    assert sections["cost_estimate"] == "included"
    assert sections["battery_schedule"] == "not_run"
    assert sections["green_operations_index"] == "not_run"
    joined_actions = " ".join(body["suggested_actions"])
    assert "執行「儲能排程建議」" in joined_actions
    assert "執行「綠能營運指數」" in joined_actions
    not_run_limits = [l["detail"] for l in body["limitations"] if l["kind"] == "section_not_run"]
    assert any("儲能排程建議" in d for d in not_run_limits)
    assert any("綠能營運指數" in d for d in not_run_limits)


def test_post_report_repeated_without_refresh_returns_existing_without_reinsert():
    conn = FakeConnection(responses=[[_dataset_row()], [_report_run_row()]])
    _use_conn(conn)
    try:
        r = TestClient(app).post("/datasets/1/report")
    finally:
        _clear()
    assert r.status_code == 200
    assert len(conn.executed) == 2  # dataset check + existing report read only


def test_post_report_refresh_true_deletes_then_reinserts():
    conn = FakeConnection(
        responses=[
            [_dataset_row()],      # get_dataset_by_id
            [_report_run_row(run_id=90)],  # get_analysis_run (existing report)
            [_summary_row()],      # get_dataset_summary
            [],                    # get_analysis_runs_for_dataset
            [],                    # delete_analysis_run (DELETE, no RETURNING)
            [_report_run_row(run_id=91)],  # insert_analysis_run
        ]
    )
    _use_conn(conn)
    try:
        r = TestClient(app).post("/datasets/1/report?refresh=true")
    finally:
        _clear()
    assert r.status_code == 200
    assert conn.committed is True
    executed_sql = " ".join(str(stmt) for stmt, _ in conn.executed)
    assert "DELETE FROM analysis_runs" in executed_sql
    assert "INSERT INTO analysis_runs" in executed_sql

    # the DELETE must target ONLY the report run's identity tuple -- never a
    # source sub-analysis run (anomaly / schedule / cost / green ops)
    delete_calls = [
        params for stmt, params in conn.executed if "DELETE FROM analysis_runs" in str(stmt)
    ]
    assert delete_calls == [
        {
            "dataset_id": 1,
            "analysis_type": analysis_report.ANALYSIS_TYPE,
            "rule_version": analysis_report.RULE_VERSION,
        }
    ]


def test_post_report_404_when_dataset_not_found():
    _use([[]])
    try:
        r = TestClient(app).post("/datasets/999/report")
    finally:
        _clear()
    assert r.status_code == 404
