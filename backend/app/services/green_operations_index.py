from collections import defaultdict
from typing import Optional

import pandas as pd

from app.schemas import (
    AnalysisNote,
    GreenOpsAnalysisResult,
    GreenOpsComponentScore,
    GreenOpsSiteResult,
    PriceClassificationThreshold,
)
from app.services.cost_intervals import compute_valid_intervals
from app.services.price_classification import compute_price_threshold
from app.services.scoring_signals import (
    SignalMask,
    evaluate_battery_health_risk_mask,
    evaluate_green_energy_waste_mask,
    evaluate_low_soc_risk_mask,
    evaluate_over_contract_risk_mask,
    evaluate_peak_period_abnormal_charging_mask,
)

RULE_VERSION = "green_operations_index_v1"
ANALYSIS_TYPE = "green_operations_index"

AGGREGATE_SITE_ID = "__all__"

COMPONENT_MAX_SCORES: dict[str, float] = {
    "pv_utilization": 25.0,
    "battery_operation": 20.0,
    "grid_dependency": 20.0,
    "battery_health": 25.0,
}

# Columns needed to re-derive eligibility for the reused official
# BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT rule (rule_engine.py) -- this list
# names WHICH columns matter, it does not duplicate the rule's actual
# threshold/branching logic, which stays solely in rule_engine.py.
_BSD_ELIGIBILITY_COLUMNS = (
    "electricity_price",
    "grid_import_kw",
    "contract_capacity_kw",
    "battery_soc",
    "battery_power_kw",
)


def evaluate_green_operations_index(rows: list[dict], max_expected_interval_hours: float) -> GreenOpsAnalysisResult:
    """Evaluate docs/MVP1_RULES.md 7 (Green Operations Index) for one
    dataset, per docs/step13_rules_and_api_design.md 5. Pure function, no
    DB access. Groups by site_id first, same as cost_estimation.py.

    Price threshold (docs/step13_rules_and_api_design.md 2.1) is computed
    ONCE across every row in the dataset -- not per site -- so
    peak_period_abnormal_charging classifies "high price" identically for
    every site, regardless of that site's own local price distribution."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row.get("site_id") or ""].append(row)

    all_rows_df = pd.DataFrame(rows) if rows else pd.DataFrame()
    dataset_price_threshold = (
        compute_price_threshold(all_rows_df["electricity_price"])
        if "electricity_price" in all_rows_df.columns
        else compute_price_threshold(pd.Series([], dtype=float))
    )

    per_site = [
        _evaluate_site(site_id, site_rows, max_expected_interval_hours, dataset_price_threshold)
        for site_id, site_rows in grouped.items()
    ]

    return GreenOpsAnalysisResult(
        rule_version=RULE_VERSION,
        max_expected_interval_hours=max_expected_interval_hours,
        site_count=len(per_site),
        per_site=per_site,
        dataset_aggregate=_aggregate_sites(per_site),
    )


def _evaluate_site(
    site_id: str,
    site_rows: list[dict],
    max_expected_interval_hours: float,
    price_threshold: PriceClassificationThreshold,
) -> GreenOpsSiteResult:
    intervals, notes = compute_valid_intervals(site_rows, max_expected_interval_hours)
    warnings = [n for n in notes if n.type != "last_row_excluded"]

    if not intervals:
        components = [
            GreenOpsComponentScore(component=name, max_score=max_score, status="insufficient_data")
            for name, max_score in COMPONENT_MAX_SCORES.items()
        ]
        return GreenOpsSiteResult(
            site_id=site_id, components=components, second_life_bonus=None, total_score=None, warnings=warnings
        )

    start_rows = [interval.start_row for interval in intervals]
    df = pd.DataFrame(start_rows)
    durations = pd.Series([interval.duration_hours for interval in intervals], index=df.index)

    pv_signals = [("green_energy_waste", evaluate_green_energy_waste_mask(df))]
    battery_operation_signals = [
        ("peak_period_abnormal_charging", evaluate_peak_period_abnormal_charging_mask(df, price_threshold)),
        ("battery_should_discharge_but_did_not", _battery_should_discharge_signal_mask(df, start_rows)),
    ]
    grid_dependency_signals = [("over_contract_risk", evaluate_over_contract_risk_mask(df))]
    battery_health_signals = [
        ("battery_health_risk", evaluate_battery_health_risk_mask(df)),
        ("low_soc_risk", evaluate_low_soc_risk_mask(df)),
    ]

    components = [
        _score_component("pv_utilization", COMPONENT_MAX_SCORES["pv_utilization"], pv_signals, durations),
        _score_component(
            "battery_operation", COMPONENT_MAX_SCORES["battery_operation"], battery_operation_signals, durations
        ),
        _score_component(
            "grid_dependency", COMPONENT_MAX_SCORES["grid_dependency"], grid_dependency_signals, durations
        ),
        _score_component(
            "battery_health", COMPONENT_MAX_SCORES["battery_health"], battery_health_signals, durations
        ),
    ]

    second_life_bonus = _compute_second_life_bonus(df)
    total_score = _sum_total_score(components, second_life_bonus)

    return GreenOpsSiteResult(
        site_id=site_id,
        components=components,
        second_life_bonus=second_life_bonus,
        total_score=total_score,
        warnings=warnings,
    )


def _battery_should_discharge_signal_mask(df: pd.DataFrame, start_rows: list[dict]) -> SignalMask:
    """Reuses the existing, official rule_engine.evaluate_battery_should_discharge_but_did_not
    verbatim (docs/step13_rules_and_api_design.md 2.2) -- this function only
    determines which rows are eligible to be scored and maps the reused
    rule's flagged timestamps back onto this dataframe's rows. It never
    reimplements the rule's own threshold/branching logic."""
    from app.services.rule_engine import evaluate_battery_should_discharge_but_did_not

    if not all(col in df.columns for col in _BSD_ELIGIBILITY_COLUMNS):
        empty = pd.Series(False, index=df.index)
        return SignalMask(eligible=empty, flagged=empty)

    eligible = (
        df["electricity_price"].notna()
        & df["grid_import_kw"].notna()
        & df["contract_capacity_kw"].notna()
        & (df["contract_capacity_kw"] > 0)
        & df["battery_soc"].notna()
        & df["battery_power_kw"].notna()
    )

    result = evaluate_battery_should_discharge_but_did_not(start_rows)
    flagged_timestamps = {a.timestamp for a in result.anomalies if a.timestamp is not None}
    if "timestamp" in df.columns:
        flagged = eligible & df["timestamp"].isin(flagged_timestamps)
    else:
        flagged = pd.Series(False, index=df.index)
    return SignalMask(eligible=eligible, flagged=flagged)


def _score_component(
    name: str,
    max_score: float,
    signals: list[tuple[str, SignalMask]],
    durations: pd.Series,
) -> GreenOpsComponentScore:
    """docs/step13_rules_and_api_design.md 5.2: penalty_ratio =
    flagged_duration_hours / eligible_duration_hours; multiple signals in
    the same component are unioned so one interval is never double-penalized."""
    index = durations.index
    eligible = pd.Series(False, index=index)
    flagged = pd.Series(False, index=index)
    for _, mask in signals:
        eligible = eligible | mask.eligible.reindex(index, fill_value=False)
        flagged = flagged | mask.flagged.reindex(index, fill_value=False)

    eligible_duration = float(durations[eligible].sum())
    flagged_duration = float(durations[flagged].sum())

    if eligible_duration == 0:
        return GreenOpsComponentScore(
            component=name,
            max_score=max_score,
            score=None,
            status="insufficient_data",
            eligible_duration_hours=0.0,
            flagged_duration_hours=0.0,
            penalty_reasons=[],
        )

    penalty_ratio = flagged_duration / eligible_duration
    score = max(0.0, min(max_score, max_score * (1 - penalty_ratio)))
    penalty_reasons = [signal_name for signal_name, mask in signals if bool(mask.flagged.any())]

    return GreenOpsComponentScore(
        component=name,
        max_score=max_score,
        score=round(score, 2),
        status="computed",
        eligible_duration_hours=round(eligible_duration, 2),
        flagged_duration_hours=round(flagged_duration, 2),
        penalty_reasons=penalty_reasons,
    )


def _compute_second_life_bonus(df: pd.DataFrame) -> Optional[float]:
    """docs/MVP1_RULES.md 7.7. Not time-weighted (boolean, per
    docs/step13_rules_and_api_design.md 5.2). Conservative reduction across
    a site's rows, mirroring evaluate_battery_health_risk_mask's OR-rule
    fix: one *confirmed* unsafe reading disqualifies the bonus outright
    (missing data on other rows cannot rescue it), but missing data alone
    -- with no confirmed-unsafe reading anywhere -- must report unavailable
    (None), never silently default to 0.

    1. at least one second-life row has confirmed-unsafe health_status or
       temperature -> 0.0 (disqualified, regardless of other missing data).
    2. every second-life row has complete health_status + temperature data
       and none are unsafe -> 10.0 (confirmed safe).
    3. some second-life rows have incomplete data and none are confirmed
       unsafe -> None (cannot confirm safety either way).
    """
    required = ("battery_is_second_life", "battery_health_status", "battery_temperature")
    if not all(col in df.columns for col in required):
        return None

    is_second_life = df["battery_is_second_life"]
    known_second_life = is_second_life.notna()
    if not known_second_life.any():
        return None

    second_life_rows = df[known_second_life & (is_second_life == True)]  # noqa: E712
    if second_life_rows.empty:
        return 0.0  # dataset genuinely has no second-life battery rows -- not a missing-data case

    health = second_life_rows["battery_health_status"]
    temp = second_life_rows["battery_temperature"]

    confirmed_unsafe = (health.notna() & ~health.isin(["normal", "warning"])) | (temp.notna() & (temp >= 40))
    if bool(confirmed_unsafe.any()):
        return 0.0

    fully_known = health.notna() & temp.notna()
    if bool(fully_known.all()):
        return 10.0

    return None


def _sum_total_score(components: list[GreenOpsComponentScore], second_life_bonus: Optional[float]) -> Optional[float]:
    scores = [c.score for c in components]
    if any(s is None for s in scores):
        return None
    return round(sum(scores) + (second_life_bonus or 0.0), 2)


def _aggregate_sites(per_site: list[GreenOpsSiteResult]) -> GreenOpsSiteResult:
    """docs/step13_rules_and_api_design.md 5.3: each component is a
    duration-weighted average across sites that have a non-null score for
    it; a component is null in the aggregate only if every site is null for
    it. second_life_bonus and total_score follow the same
    all-non-null-required rule as the single-site case."""
    aggregate_components = [
        _aggregate_component(name, max_score, per_site) for name, max_score in COMPONENT_MAX_SCORES.items()
    ]
    aggregate_bonus = _aggregate_second_life_bonus(per_site)
    aggregate_total = _sum_total_score(aggregate_components, aggregate_bonus)

    warnings: list[AnalysisNote] = []
    for site in per_site:
        warnings.extend(note.model_copy(update={"site_id": site.site_id}) for note in site.warnings)

    return GreenOpsSiteResult(
        site_id=AGGREGATE_SITE_ID,
        components=aggregate_components,
        second_life_bonus=aggregate_bonus,
        total_score=aggregate_total,
        warnings=warnings,
    )


def _aggregate_component(name: str, max_score: float, per_site: list[GreenOpsSiteResult]) -> GreenOpsComponentScore:
    site_components = [next(c for c in site.components if c.component == name) for site in per_site]
    computed = [c for c in site_components if c.score is not None]

    total_eligible = sum(c.eligible_duration_hours or 0.0 for c in site_components)
    total_flagged = sum(c.flagged_duration_hours or 0.0 for c in site_components)
    penalty_reasons = sorted({reason for c in site_components for reason in c.penalty_reasons})

    if not computed:
        return GreenOpsComponentScore(
            component=name,
            max_score=max_score,
            score=None,
            status="insufficient_data",
            eligible_duration_hours=round(total_eligible, 2),
            flagged_duration_hours=round(total_flagged, 2),
            penalty_reasons=penalty_reasons,
        )

    weighted_sum = sum(c.score * (c.eligible_duration_hours or 0.0) for c in computed)
    weight_total = sum(c.eligible_duration_hours or 0.0 for c in computed)
    aggregate_score = weighted_sum / weight_total if weight_total > 0 else sum(c.score for c in computed) / len(computed)

    return GreenOpsComponentScore(
        component=name,
        max_score=max_score,
        score=round(aggregate_score, 2),
        status="computed",
        eligible_duration_hours=round(total_eligible, 2),
        flagged_duration_hours=round(total_flagged, 2),
        penalty_reasons=penalty_reasons,
    )


def _aggregate_second_life_bonus(per_site: list[GreenOpsSiteResult]) -> Optional[float]:
    """Same all-non-null-required rule as _sum_total_score -- if ANY
    participating site's second-life bonus is unavailable (None), the
    aggregate must not silently average over only the known sites, which
    would present an unverified dataset-wide bonus. Only when every site's
    bonus is known can the aggregate be computed."""
    if not per_site:
        return None
    bonuses = [site.second_life_bonus for site in per_site]
    if any(bonus is None for bonus in bonuses):
        return None
    return 10.0 if all(bonus == 10.0 for bonus in bonuses) else 0.0
