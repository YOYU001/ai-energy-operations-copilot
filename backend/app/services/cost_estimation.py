from collections import defaultdict

import pandas as pd

from app.schemas import (
    AnalysisNote,
    CostAnalysisResult,
    CostInterval,
    CostSiteResult,
    ScoringSignalFlag,
)
from app.services.cost_intervals import compute_valid_intervals
from app.services.scoring_signals import evaluate_over_contract_risk_mask

RULE_VERSION = "cost_estimation_v1"
ANALYSIS_TYPE = "cost_estimation"

AGGREGATE_SITE_ID = "__all__"


def evaluate_cost_estimation(rows: list[dict], max_expected_interval_hours: float) -> CostAnalysisResult:
    """Evaluate docs/MVP1_RULES.md 6 (Cost Estimation) for one dataset, per
    docs/step13_rules_and_api_design.md 4. Pure function, no DB access.
    Groups by site_id first (4.3) -- compute_valid_intervals itself refuses
    to run across multiple sites, so grouping here is not optional."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row.get("site_id") or ""].append(row)

    per_site = [
        _evaluate_site(site_id, site_rows, max_expected_interval_hours)
        for site_id, site_rows in grouped.items()
    ]

    return CostAnalysisResult(
        rule_version=RULE_VERSION,
        max_expected_interval_hours=max_expected_interval_hours,
        site_count=len(per_site),
        per_site=per_site,
        dataset_aggregate=_aggregate_sites(per_site),
    )


def _evaluate_site(site_id: str, site_rows: list[dict], max_expected_interval_hours: float) -> CostSiteResult:
    intervals, notes = compute_valid_intervals(site_rows, max_expected_interval_hours)

    df = pd.DataFrame([interval.start_row for interval in intervals]) if intervals else pd.DataFrame()
    over_contract_flagged = evaluate_over_contract_risk_mask(df).flagged if not df.empty else []

    cost_intervals: list[CostInterval] = []
    penalty_flags: list[ScoringSignalFlag] = []
    total_energy_cost = 0.0
    total_arbitrage_saving = 0.0

    for position, interval in enumerate(intervals):
        grid_import_kw = interval.start_row.get("grid_import_kw")
        price = interval.start_row.get("electricity_price")
        battery_power_kw = interval.start_row.get("battery_power_kw")

        energy_kwh = 0.0
        estimated_cost = 0.0
        if grid_import_kw is not None and price is not None:
            energy_kwh = grid_import_kw * interval.duration_hours
            estimated_cost = energy_kwh * price
            total_energy_cost += estimated_cost

        arbitrage = None
        if battery_power_kw is not None and price is not None:
            if battery_power_kw > 0:  # discharging -> saving
                arbitrage = battery_power_kw * interval.duration_hours * price
            elif battery_power_kw < 0:  # charging -> cost, recorded as negative arbitrage
                arbitrage = -(abs(battery_power_kw) * interval.duration_hours * price)
            if arbitrage is not None:
                total_arbitrage_saving += arbitrage

        cost_intervals.append(
            CostInterval(
                site_id=site_id,
                interval_start=interval.interval_start,
                interval_end=interval.interval_end,
                duration_hours=interval.duration_hours,
                energy_kwh=energy_kwh,
                estimated_cost=estimated_cost,
                battery_arbitrage=arbitrage,
            )
        )

        if len(over_contract_flagged) > position and bool(over_contract_flagged.iloc[position]):
            penalty_flags.append(
                ScoringSignalFlag(
                    signal="over_contract_risk",
                    interval_start=interval.interval_start,
                    interval_end=interval.interval_end,
                )
            )

    limitations = [n for n in notes if n.type == "last_row_excluded"]
    warnings = [n for n in notes if n.type != "last_row_excluded"]

    return CostSiteResult(
        site_id=site_id,
        row_count=len(site_rows),
        interval_count=len(cost_intervals),
        intervals=cost_intervals,
        total_energy_cost=total_energy_cost,
        total_arbitrage_saving=total_arbitrage_saving,
        over_contract_penalty_flags=penalty_flags,
        warnings=warnings,
        limitations=limitations,
    )


def _stamp_site_id(notes: list[AnalysisNote], site_id: str) -> list[AnalysisNote]:
    return [note.model_copy(update={"site_id": site_id}) for note in notes]


def _aggregate_sites(per_site: list[CostSiteResult]) -> CostSiteResult:
    """docs/step13_rules_and_api_design.md 4.3: dataset_aggregate is a
    direct sum across sites -- not a duration-weighted average like Green
    Operations Index (cost is additive, not a bounded score)."""
    intervals: list[CostInterval] = []
    penalty_flags: list[ScoringSignalFlag] = []
    warnings: list[AnalysisNote] = []
    limitations: list[AnalysisNote] = []

    for site in per_site:
        intervals.extend(site.intervals)
        penalty_flags.extend(site.over_contract_penalty_flags)
        warnings.extend(_stamp_site_id(site.warnings, site.site_id))
        limitations.extend(_stamp_site_id(site.limitations, site.site_id))

    return CostSiteResult(
        site_id=AGGREGATE_SITE_ID,
        row_count=sum(site.row_count for site in per_site),
        interval_count=sum(site.interval_count for site in per_site),
        intervals=intervals,
        total_energy_cost=sum(site.total_energy_cost for site in per_site),
        total_arbitrage_saving=sum(site.total_arbitrage_saving for site in per_site),
        over_contract_penalty_flags=penalty_flags,
        warnings=warnings,
        limitations=limitations,
    )
