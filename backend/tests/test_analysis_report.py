from datetime import datetime, timezone

from app.schemas import (
    AnomalyResult,
    BatteryDischargeAnalysisResult,
    BatteryDischargeEvidence,
    CostAnalysisResult,
    CostSiteResult,
    GreenOpsAnalysisResult,
    GreenOpsComponentScore,
    GreenOpsSiteResult,
    PriceClassificationThreshold,
    PriceThresholdInfo,
    ScheduleAnalysisResult,
    ScheduleRecommendation,
)
from app.services.analysis_report import (
    SECTION_ANOMALY,
    SECTION_COST,
    SECTION_DATASET_OVERVIEW,
    SECTION_GREEN_OPS,
    SECTION_SCHEDULE,
    SECTION_SIMILAR_CASES,
    SubAnalysis,
    build_analysis_report,
)

GENERATED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
RUN_AT = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)


def _dataset(dataset_id=1, name="Demo"):
    return {"id": dataset_id, "name": name}


def _summary(row_count=96, site_count=1):
    return {
        "row_count": row_count,
        "site_count": site_count,
        "start_time": datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc),
        "end_time": datetime(2026, 3, 1, 23, 45, tzinfo=timezone.utc),
        "columns": {
            "electricity_price": {"min": 2.0, "mean": 4.5, "max": 8.0},
            "load_kw": {"min": 10.0, "mean": 20.0, "max": 30.0},
            "pv_actual_kw": {"min": 0.0, "mean": 12.0, "max": 40.0},
        },
    }


def _anomaly_sub(flagged=2):
    evidence = BatteryDischargeEvidence(price_threshold_mode="percentile", non_null_price_sample_count=96, distinct_price_count=3)
    anomalies = [
        AnomalyResult(
            anomaly_type="battery_should_discharge_but_did_not",
            severity="high" if i == 0 else "medium",
            timestamp=RUN_AT,
            evidence=evidence,
            suggested_actions=["檢查 BMS 放電授權", "確認 SOC 下限設定"],
        )
        for i in range(flagged)
    ]
    result = BatteryDischargeAnalysisResult(
        rule="battery_should_discharge_but_did_not",
        rule_version="battery_should_discharge_v1",
        price_threshold=PriceThresholdInfo(mode="percentile", non_null_sample_count=96, distinct_price_count=3),
        input_row_count=96,
        evaluated_row_count=96,
        flagged_row_count=flagged,
        anomalies=anomalies,
    )
    return SubAnalysis(run_id=11, created_at=RUN_AT, result=result)


def _schedule_sub():
    recs = (
        [ScheduleRecommendation(timestamp=RUN_AT, action="charge", reason="low price", price_classification="low")]
        + [ScheduleRecommendation(timestamp=RUN_AT, action="hold", reason="n/a", price_classification="neutral") for _ in range(3)]
    )
    result = ScheduleAnalysisResult(
        rule_version="battery_scheduling_v1",
        price_threshold=PriceClassificationThreshold(mode="percentile", non_null_sample_count=96, distinct_price_count=3),
        input_row_count=96,
        evaluated_row_count=96,
        recommendations=recs,
    )
    return SubAnalysis(run_id=12, created_at=RUN_AT, result=result)


def _cost_site(site_id="__dataset__"):
    return CostSiteResult(
        site_id=site_id,
        row_count=96,
        interval_count=95,
        intervals=[],
        total_energy_cost=1234.5,
        total_arbitrage_saving=67.8,
        over_contract_penalty_flags=[],
        warnings=[],
        limitations=[],
    )


def _cost_sub():
    result = CostAnalysisResult(
        rule_version="cost_estimation_v1",
        max_expected_interval_hours=6.0,
        site_count=1,
        per_site=[_cost_site("site_a")],
        dataset_aggregate=_cost_site(),
    )
    return SubAnalysis(run_id=13, created_at=RUN_AT, result=result)


def _green_ops_site(total_score=82.5):
    return GreenOpsSiteResult(
        site_id="__dataset__",
        components=[
            GreenOpsComponentScore(component="pv_utilization", max_score=25.0, score=20.0, status="computed"),
            GreenOpsComponentScore(component="battery_operation", max_score=25.0, score=18.0, status="computed"),
            GreenOpsComponentScore(component="grid_dependency", max_score=20.0, score=None, status="insufficient_data"),
            GreenOpsComponentScore(component="battery_health", max_score=20.0, score=19.0, status="computed"),
        ],
        second_life_bonus=5.0,
        total_score=total_score,
        warnings=[],
    )


def _green_ops_sub(total_score=82.5):
    result = GreenOpsAnalysisResult(
        rule_version="green_operations_index_v1",
        max_expected_interval_hours=6.0,
        site_count=1,
        per_site=[_green_ops_site(total_score)],
        dataset_aggregate=_green_ops_site(total_score),
    )
    return SubAnalysis(run_id=14, created_at=RUN_AT, result=result)


def _sections_by_key(report):
    return {s.key: s for s in report.sections}


def test_all_sub_analyses_present_all_sections_included():
    report = build_analysis_report(
        dataset=_dataset(),
        summary=_summary(),
        generated_at=GENERATED_AT,
        anomaly=_anomaly_sub(),
        schedule=_schedule_sub(),
        cost=_cost_sub(),
        green_ops=_green_ops_sub(),
    )
    sections = _sections_by_key(report)
    assert sections[SECTION_DATASET_OVERVIEW].status == "included"
    for key in (SECTION_ANOMALY, SECTION_SCHEDULE, SECTION_COST, SECTION_GREEN_OPS):
        assert sections[key].status == "included", key
        assert sections[key].source_analysis_run_id is not None
        assert sections[key].source_created_at == RUN_AT
    assert sections[SECTION_SIMILAR_CASES].status == "manual_lookup"
    assert report.key_findings  # non-empty
    # no section_not_run limitations for the four analyses, only the fixed
    # similar-cases + snapshot-staleness entries
    not_run = [l for l in report.limitations if l.kind == "section_not_run"]
    assert all("相似案件" in l.detail for l in not_run)


def test_no_sub_analyses_only_overview_included_rest_not_run():
    report = build_analysis_report(
        dataset=_dataset(),
        summary=_summary(),
        generated_at=GENERATED_AT,
    )
    sections = _sections_by_key(report)
    assert sections[SECTION_DATASET_OVERVIEW].status == "included"
    for key in (SECTION_ANOMALY, SECTION_SCHEDULE, SECTION_COST, SECTION_GREEN_OPS):
        assert sections[key].status == "not_run"
        assert sections[key].note
    assert sections[SECTION_SIMILAR_CASES].status == "manual_lookup"
    # every not-run analysis surfaces a suggested action to run it
    joined = " ".join(report.suggested_actions)
    for title in ("異常診斷", "儲能排程建議", "成本估算", "綠能營運指數"):
        assert f"執行「{title}」" in joined
    kinds = {l.kind for l in report.limitations}
    assert "section_not_run" in kinds
    assert "snapshot_staleness" in kinds


def test_partial_only_anomaly_present():
    report = build_analysis_report(
        dataset=_dataset(),
        summary=_summary(),
        generated_at=GENERATED_AT,
        anomaly=_anomaly_sub(flagged=2),
    )
    sections = _sections_by_key(report)
    assert sections[SECTION_ANOMALY].status == "included"
    assert sections[SECTION_SCHEDULE].status == "not_run"
    assert sections[SECTION_COST].status == "not_run"
    assert sections[SECTION_GREEN_OPS].status == "not_run"
    # anomaly suggested_actions bubble up into the report's suggested_actions
    assert "檢查 BMS 放電授權" in report.suggested_actions


def test_anomaly_with_zero_flagged_rows_reads_as_no_anomaly():
    report = build_analysis_report(
        dataset=_dataset(),
        summary=_summary(),
        generated_at=GENERATED_AT,
        anomaly=_anomaly_sub(flagged=0),
    )
    section = _sections_by_key(report)[SECTION_ANOMALY]
    assert section.status == "included"
    assert any("未偵測到" in p for p in section.summary_points)


def test_green_ops_total_score_none_reads_as_insufficient_data():
    report = build_analysis_report(
        dataset=_dataset(),
        summary=_summary(),
        generated_at=GENERATED_AT,
        green_ops=_green_ops_sub(total_score=None),
    )
    section = _sections_by_key(report)[SECTION_GREEN_OPS]
    assert section.status == "included"
    assert any("資料不足" in p for p in section.summary_points)


def test_empty_dataset_does_not_raise_and_reports_zero_rows():
    report = build_analysis_report(
        dataset=_dataset(),
        summary=_summary(row_count=0, site_count=0),
        generated_at=GENERATED_AT,
    )
    assert report.row_count == 0
    assert report.site_count == 0
    overview = _sections_by_key(report)[SECTION_DATASET_OVERVIEW]
    assert overview.status == "included"
    assert any("0 筆" in p for p in overview.summary_points)


def test_similar_cases_note_includes_anomaly_type_hint_when_available():
    report = build_analysis_report(
        dataset=_dataset(),
        summary=_summary(),
        generated_at=GENERATED_AT,
        anomaly=_anomaly_sub(flagged=1),
    )
    section = _sections_by_key(report)[SECTION_SIMILAR_CASES]
    assert "battery_should_discharge_but_did_not" in (section.note or "")
