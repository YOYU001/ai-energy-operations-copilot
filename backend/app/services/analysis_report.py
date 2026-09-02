"""Step 14 -- Analysis Report.

Composes a single human-readable snapshot report out of the sub-analyses
that already ran for a dataset (Step 5 summary, Step 9 anomaly diagnosis,
Step 13 battery scheduling / cost / green operations index) plus a manual
pointer for similar cases (Step 11).

This module is pure: no DB, no IO. It takes already-validated result models
(or None where a sub-analysis has not been run) and returns an
AnalysisReportResult. The endpoint in app/main.py does the persistence,
reusing analysis_runs / get_analysis_run / insert_analysis_run unchanged
(analysis_type='analysis_report'), so no schema migration is needed.

The report is a snapshot on purpose: it embeds each sub-analysis's key
outputs at generation time rather than recomputing on read, matching how
every other analysis_runs row behaves. If a sub-analysis is re-run later,
the report does NOT auto-update -- POST again with refresh=true to rebuild.
That staleness is always spelled out in `limitations`.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.schemas import (
    AnalysisReportResult,
    BatteryDischargeAnalysisResult,
    CostAnalysisResult,
    GreenOpsAnalysisResult,
    ReportLimitation,
    ReportSection,
    ScheduleAnalysisResult,
)

RULE_VERSION = "analysis_report_v1"
ANALYSIS_TYPE = "analysis_report"

# Section keys, in the order the report presents them. Mirrors
# docs/DEVELOPMENT_WORKFLOW.md section 6 / docs/MVP_V1_SPEC.md 4.10.
SECTION_DATASET_OVERVIEW = "dataset_overview"
SECTION_ANOMALY = "anomaly_diagnosis"
SECTION_SCHEDULE = "battery_schedule"
SECTION_SIMILAR_CASES = "similar_cases"
SECTION_COST = "cost_estimate"
SECTION_GREEN_OPS = "green_operations_index"

_SECTION_TITLES = {
    SECTION_DATASET_OVERVIEW: "資料集概況",
    SECTION_ANOMALY: "異常診斷",
    SECTION_SCHEDULE: "儲能排程建議",
    SECTION_SIMILAR_CASES: "相似案件",
    SECTION_COST: "成本估算",
    SECTION_GREEN_OPS: "綠能營運指數",
}

# GreenOps component -> Traditional Chinese label (matches the frontend
# GreenOpsChart labels so the report reads consistently with the dashboard).
_GREEN_OPS_COMPONENT_LABELS = {
    "pv_utilization": "PV 使用率",
    "battery_operation": "電池運轉",
    "grid_dependency": "電網依賴",
    "battery_health": "電池健康",
}

_SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}
_SCHEDULE_ACTION_LABELS = {
    "charge": "充電",
    "discharge": "放電",
    "idle": "待機",
    "hold": "保持",
}
_MAX_SUGGESTED_ACTIONS = 12


@dataclass(frozen=True)
class SubAnalysis:
    """One already-run sub-analysis: its analysis_runs row id + created_at
    for provenance, plus the validated result model. Passed in by the
    endpoint so this module never touches a DB row shape directly."""

    run_id: int
    created_at: datetime
    result: object


def _fmt_number(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "資料不足"
    return f"{value:,.{digits}f}"


def _dataset_overview_section(dataset: dict, summary: dict) -> ReportSection:
    row_count = summary.get("row_count") or 0
    site_count = summary.get("site_count") or 0
    points = [
        f"資料筆數：{row_count:,} 筆",
        f"場域數：{site_count} 個",
    ]
    start_time = summary.get("start_time")
    end_time = summary.get("end_time")
    if start_time is not None and end_time is not None:
        points.append(f"時間範圍：{start_time:%Y-%m-%d %H:%M} ~ {end_time:%Y-%m-%d %H:%M}")
    columns = summary.get("columns") or {}
    for col, label in (
        ("electricity_price", "電價"),
        ("load_kw", "負載 (kW)"),
        ("pv_actual_kw", "實際 PV (kW)"),
    ):
        stats = columns.get(col)
        if stats and stats.get("mean") is not None:
            points.append(f"{label} 平均：{_fmt_number(stats['mean'])}")
    return ReportSection(
        key=SECTION_DATASET_OVERVIEW,
        title=_SECTION_TITLES[SECTION_DATASET_OVERVIEW],
        status="included",
        summary_points=points,
    )


def _not_run_section(key: str, run_hint: str) -> ReportSection:
    return ReportSection(
        key=key,
        title=_SECTION_TITLES[key],
        status="not_run",
        note=f"尚未執行{_SECTION_TITLES[key]}，{run_hint}",
    )


def _anomaly_section(sub: Optional[SubAnalysis]) -> ReportSection:
    if sub is None:
        return _not_run_section(SECTION_ANOMALY, "請至資料集分析頁執行異常診斷後重新產生報告。")
    result: BatteryDischargeAnalysisResult = sub.result
    points = [
        f"評估筆數：{result.evaluated_row_count:,} / 輸入 {result.input_row_count:,} 筆",
    ]
    if result.flagged_row_count == 0:
        points.append("未偵測到符合規則的異常")
    else:
        points.append(f"偵測到 {result.flagged_row_count:,} 筆異常")
        top = max(result.anomalies, key=lambda a: _SEVERITY_RANK.get(a.severity, 0), default=None)
        if top is not None:
            points.append(f"最高嚴重度：{top.severity}")
        types = sorted({a.anomaly_type for a in result.anomalies})
        if types:
            points.append("異常類型：" + "、".join(types))
    return ReportSection(
        key=SECTION_ANOMALY,
        title=_SECTION_TITLES[SECTION_ANOMALY],
        status="included",
        source_analysis_run_id=sub.run_id,
        source_created_at=sub.created_at,
        summary_points=points,
    )


def _schedule_section(sub: Optional[SubAnalysis]) -> ReportSection:
    if sub is None:
        return _not_run_section(SECTION_SCHEDULE, "請至資料集圖表頁的 Battery Scheduling 區塊執行後重新產生報告。")
    result: ScheduleAnalysisResult = sub.result
    counts: dict[str, int] = {}
    for rec in result.recommendations:
        counts[rec.action] = counts.get(rec.action, 0) + 1
    action_summary = "、".join(
        f"{_SCHEDULE_ACTION_LABELS.get(action, action)} {counts[action]} 次"
        for action in ("charge", "discharge", "idle", "hold")
        if counts.get(action)
    )
    points = [
        f"評估筆數：{result.evaluated_row_count:,} / 輸入 {result.input_row_count:,} 筆",
        f"建議動作分布：{action_summary}" if action_summary else "無可用的排程建議",
        f"電價分類模式：{result.price_threshold.mode}",
    ]
    return ReportSection(
        key=SECTION_SCHEDULE,
        title=_SECTION_TITLES[SECTION_SCHEDULE],
        status="included",
        source_analysis_run_id=sub.run_id,
        source_created_at=sub.created_at,
        summary_points=points,
    )


def _similar_cases_section(anomaly: Optional[SubAnalysis]) -> ReportSection:
    note = (
        "本報告不含即時相似案件比對。請至「Case Similarity」頁面，"
        "以事件症狀描述查詢歷史案件。"
    )
    if anomaly is not None and anomaly.result.anomalies:
        types = sorted({a.anomaly_type for a in anomaly.result.anomalies})
        note += f"（可用的查詢關鍵字：{'、'.join(types)}）"
    return ReportSection(
        key=SECTION_SIMILAR_CASES,
        title=_SECTION_TITLES[SECTION_SIMILAR_CASES],
        status="manual_lookup",
        note=note,
    )


def _cost_section(sub: Optional[SubAnalysis]) -> ReportSection:
    if sub is None:
        return _not_run_section(SECTION_COST, "請至資料集圖表頁的 Cost Comparison 區塊執行後重新產生報告。")
    result: CostAnalysisResult = sub.result
    agg = result.dataset_aggregate
    points = [
        f"最大預期間隔參數：{_fmt_number(result.max_expected_interval_hours)} 小時",
        f"整體預估電費：{_fmt_number(agg.total_energy_cost)}",
        f"整體套利節省：{_fmt_number(agg.total_arbitrage_saving)}",
    ]
    if agg.over_contract_penalty_flags:
        points.append(f"超約風險標記：{len(agg.over_contract_penalty_flags)} 段")
    return ReportSection(
        key=SECTION_COST,
        title=_SECTION_TITLES[SECTION_COST],
        status="included",
        source_analysis_run_id=sub.run_id,
        source_created_at=sub.created_at,
        summary_points=points,
    )


def _green_ops_section(sub: Optional[SubAnalysis]) -> ReportSection:
    if sub is None:
        return _not_run_section(SECTION_GREEN_OPS, "請至資料集圖表頁的 Green Operations Index 區塊執行後重新產生報告。")
    result: GreenOpsAnalysisResult = sub.result
    agg = result.dataset_aggregate
    points = [
        f"整體綠能營運指數："
        + ("資料不足" if agg.total_score is None else f"{_fmt_number(agg.total_score)} / 100"),
    ]
    for component in agg.components:
        label = _GREEN_OPS_COMPONENT_LABELS.get(component.component, component.component)
        if component.status == "insufficient_data" or component.score is None:
            points.append(f"{label}：資料不足")
        else:
            points.append(f"{label}：{_fmt_number(component.score)} / {_fmt_number(component.max_score, 0)}")
    if agg.second_life_bonus:
        points.append(f"二次利用加分：{_fmt_number(agg.second_life_bonus)}")
    return ReportSection(
        key=SECTION_GREEN_OPS,
        title=_SECTION_TITLES[SECTION_GREEN_OPS],
        status="included",
        source_analysis_run_id=sub.run_id,
        source_created_at=sub.created_at,
        summary_points=points,
    )


def _key_findings(sections: list[ReportSection]) -> list[str]:
    by_key = {s.key: s for s in sections}
    findings: list[str] = []

    overview = by_key[SECTION_DATASET_OVERVIEW]
    findings.append("；".join(overview.summary_points[:3]))

    anomaly = by_key[SECTION_ANOMALY]
    if anomaly.status == "included":
        findings.append("異常診斷：" + "；".join(anomaly.summary_points[1:]))

    schedule = by_key[SECTION_SCHEDULE]
    if schedule.status == "included" and len(schedule.summary_points) > 1:
        findings.append("排程建議：" + schedule.summary_points[1])

    cost = by_key[SECTION_COST]
    if cost.status == "included":
        findings.append("成本估算：" + "；".join(cost.summary_points[1:3]))

    green_ops = by_key[SECTION_GREEN_OPS]
    if green_ops.status == "included" and green_ops.summary_points:
        findings.append(green_ops.summary_points[0])

    return findings


def _suggested_actions(sections: list[ReportSection], anomaly: Optional[SubAnalysis]) -> list[str]:
    actions: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        if text not in seen and len(actions) < _MAX_SUGGESTED_ACTIONS:
            seen.add(text)
            actions.append(text)

    if anomaly is not None:
        for a in anomaly.result.anomalies:
            for step in a.suggested_actions:
                add(step)

    for section in sections:
        if section.status == "not_run":
            add(f"執行「{section.title}」以補完報告內容")

    add("相似案件請至 Case Similarity 頁面以症狀描述查詢")
    return actions


def _limitations(sections: list[ReportSection], generated_at: datetime, cost: Optional[SubAnalysis], green_ops: Optional[SubAnalysis]) -> list[ReportLimitation]:
    limitations: list[ReportLimitation] = []
    for section in sections:
        if section.status == "not_run":
            limitations.append(
                ReportLimitation(
                    kind="section_not_run",
                    detail=f"「{section.title}」尚未執行，本報告該段落無內容。",
                )
            )
    limitations.append(
        ReportLimitation(
            kind="section_not_run",
            detail="「相似案件」在 MVP 版本為手動查詢，本報告僅提供指引，不含即時比對結果。",
        )
    )
    limitations.append(
        ReportLimitation(
            kind="snapshot_staleness",
            detail=(
                f"本報告為 {generated_at:%Y-%m-%d %H:%M} 的快照。"
                "若之後重新執行任何子分析，需重新產生報告才會反映；各段落的資料來源時間如各段所示。"
            ),
        )
    )
    for sub, name in ((cost, "成本估算"), (green_ops, "綠能營運指數")):
        if sub is None:
            continue
        notes = list(getattr(sub.result.dataset_aggregate, "warnings", []) or [])
        notes += list(getattr(sub.result.dataset_aggregate, "limitations", []) or [])
        for note in notes:
            limitations.append(
                ReportLimitation(
                    kind="data_quality",
                    detail=f"{name}：{note.type}（{note.count} 筆）",
                )
            )
    return limitations


def build_analysis_report(
    *,
    dataset: dict,
    summary: dict,
    generated_at: datetime,
    anomaly: Optional[SubAnalysis] = None,
    schedule: Optional[SubAnalysis] = None,
    cost: Optional[SubAnalysis] = None,
    green_ops: Optional[SubAnalysis] = None,
) -> AnalysisReportResult:
    sections = [
        _dataset_overview_section(dataset, summary),
        _anomaly_section(anomaly),
        _schedule_section(schedule),
        _similar_cases_section(anomaly),
        _cost_section(cost),
        _green_ops_section(green_ops),
    ]
    return AnalysisReportResult(
        rule=ANALYSIS_TYPE,
        rule_version=RULE_VERSION,
        dataset_id=dataset["id"],
        dataset_name=dataset.get("name"),
        generated_at=generated_at,
        row_count=summary.get("row_count") or 0,
        site_count=summary.get("site_count") or 0,
        start_time=summary.get("start_time"),
        end_time=summary.get("end_time"),
        key_findings=_key_findings(sections),
        sections=sections,
        suggested_actions=_suggested_actions(sections, anomaly),
        limitations=_limitations(sections, generated_at, cost, green_ops),
    )
