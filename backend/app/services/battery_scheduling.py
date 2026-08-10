from typing import Optional

import pandas as pd

from app.schemas import ScheduleAnalysisResult, ScheduleRecommendation
from app.services.price_classification import classify_price_series, compute_price_threshold

RULE_VERSION = "battery_scheduling_v1"
ANALYSIS_TYPE = "battery_scheduling"

# See docs/step13_rules_and_api_design.md 3.2 for the full precedence
# derivation (user-decided 2026-08-05) that this module implements.
CHARGE_PRICE_SOC_MAX = 80
CHARGE_PV_SOC_MAX = 90
DISCHARGE_SOC_MIN = 30
DISCHARGE_GRID_RATIO = 0.80
SOC_SAFETY_THRESHOLD = 20
SOH_VETO_THRESHOLD = 80
TEMPERATURE_SAFETY_THRESHOLD = 40

_REQUIRED_COLUMNS = [
    "timestamp",
    "battery_temperature",
    "battery_health_status",
    "battery_soc",
    "battery_soh",
    "electricity_price",
    "pv_actual_kw",
    "load_kw",
    "grid_import_kw",
    "contract_capacity_kw",
    "battery_power_kw",
]


def _to_optional_timestamp(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return value


def evaluate_battery_scheduling(rows: list[dict]) -> ScheduleAnalysisResult:
    """Evaluate docs/MVP1_RULES.md 5 (Battery Scheduling Suggestion) for one
    dataset, per docs/step13_rules_and_api_design.md 3. Pure function, no DB
    access. One recommendation per row, evaluated independently (no
    dependency on neighboring rows, unlike cost/green-ops which need
    row-to-row duration)."""
    input_row_count = len(rows)

    df = pd.DataFrame(rows)
    for col in _REQUIRED_COLUMNS:
        if col not in df.columns:
            df[col] = None

    price_threshold = compute_price_threshold(df["electricity_price"])
    price_class = classify_price_series(df["electricity_price"], price_threshold)

    temp_ok = df["battery_temperature"].notna()
    soh_ok = df["battery_soh"].notna()
    soc_ok = df["battery_soc"].notna()
    health_ok = df["battery_health_status"].notna()
    pv_load_ok = df["pv_actual_kw"].notna() & df["load_kw"].notna()
    grid_ok = (
        df["grid_import_kw"].notna()
        & df["contract_capacity_kw"].notna()
        & (df["contract_capacity_kw"] > 0)
    )

    temp_critical = temp_ok & (df["battery_temperature"] >= TEMPERATURE_SAFETY_THRESHOLD)
    health_critical = health_ok & (df["battery_health_status"] == "critical")
    soc_low = soc_ok & (df["battery_soc"] <= SOC_SAFETY_THRESHOLD)
    soh_low = soh_ok & (df["battery_soh"] < SOH_VETO_THRESHOLD)

    charge_price_branch = (price_class == "low") & soc_ok & (df["battery_soc"] < CHARGE_PRICE_SOC_MAX)
    charge_pv_branch = (
        pv_load_ok & soc_ok & (df["battery_soc"] < CHARGE_PV_SOC_MAX) & (df["pv_actual_kw"] > df["load_kw"])
    )
    charge_condition = charge_price_branch | charge_pv_branch

    discharge_condition = (
        (price_class == "high")
        & soc_ok
        & (df["battery_soc"] > DISCHARGE_SOC_MIN)
        & grid_ok
        & (df["grid_import_kw"] >= DISCHARGE_GRID_RATIO * df["contract_capacity_kw"])
    )

    evaluated_mask = temp_ok | health_ok | soc_ok | soh_ok | pv_load_ok | grid_ok
    evaluated_row_count = int(evaluated_mask.sum())

    recommendations: list[ScheduleRecommendation] = [
        _build_recommendation(
            timestamp=_to_optional_timestamp(df.at[idx, "timestamp"]),
            price_label=price_class.at[idx],
            temp_critical=bool(temp_critical.at[idx]),
            health_critical=bool(health_critical.at[idx]),
            soc_low=bool(soc_low.at[idx]) if soc_ok.at[idx] else None,
            soh_low=bool(soh_low.at[idx]) if soh_ok.at[idx] else None,
            charge_condition=bool(charge_condition.at[idx]),
            discharge_condition=bool(discharge_condition.at[idx]),
            any_column_present=bool(evaluated_mask.at[idx]),
        )
        for idx in df.index
    ]

    return ScheduleAnalysisResult(
        rule_version=RULE_VERSION,
        price_threshold=price_threshold,
        input_row_count=input_row_count,
        evaluated_row_count=evaluated_row_count,
        recommendations=recommendations,
    )


def _build_recommendation(
    timestamp,
    price_label: str,
    temp_critical: bool,
    health_critical: bool,
    soc_low: Optional[bool],
    soh_low: Optional[bool],
    charge_condition: bool,
    discharge_condition: bool,
    any_column_present: bool,
) -> ScheduleRecommendation:
    if not any_column_present:
        return ScheduleRecommendation(
            timestamp=timestamp,
            action="hold",
            reason="insufficient data to evaluate any scheduling condition for this row",
            price_classification=price_label,
            warnings=["insufficient_row_data"],
        )

    # Step 1: temperature safety override -- blanket idle, never discharge.
    if temp_critical:
        return ScheduleRecommendation(
            timestamp=timestamp,
            action="idle",
            reason="battery_temperature >= 40 -- safety override, discharge not permitted",
            price_classification=price_label,
        )

    # Step 2: health-critical safety override -- blanket idle, never discharge.
    if health_critical:
        return ScheduleRecommendation(
            timestamp=timestamp,
            action="idle",
            reason='battery_health_status == "critical" -- safety override, discharge not permitted',
            price_classification=price_label,
        )

    # Step 3: low-SOC protection -- charge if the low-price/PV-surplus
    # condition is met, otherwise idle; never discharge.
    if soc_low:
        if charge_condition:
            return ScheduleRecommendation(
                timestamp=timestamp,
                action="charge",
                reason="battery_soc <= 20 and a charge condition is met -- protect remaining capacity by charging",
                price_classification=price_label,
            )
        return ScheduleRecommendation(
            timestamp=timestamp,
            action="idle",
            reason="battery_soc <= 20 and no charge condition met -- preserve remaining charge, discharge not permitted",
            price_classification=price_label,
        )

    # Step 4: SOH veto -- discharge is not permitted, but charging still is.
    if soh_low:
        if charge_condition:
            return ScheduleRecommendation(
                timestamp=timestamp,
                action="charge",
                reason="battery_soh < 80 vetoes discharge; a charge condition is met",
                price_classification=price_label,
            )
        return ScheduleRecommendation(
            timestamp=timestamp,
            action="hold",
            reason="battery_soh < 80 vetoes discharge; no charge condition met",
            price_classification=price_label,
        )

    # Step 5: general charge/discharge evaluation. Discharge wins ties
    # (docs/step13_rules_and_api_design.md tie-break decision, 2026-08-05):
    # high-price/high-grid-dependency discharge is a more urgent peak-shaving
    # and cost-risk signal than an available-but-not-yet-used PV surplus.
    if discharge_condition:
        warnings = ["conflicting_energy_flow_signals"] if charge_condition else []
        return ScheduleRecommendation(
            timestamp=timestamp,
            action="discharge",
            reason="price is high and grid_import_kw >= 0.80 * contract_capacity_kw",
            price_classification=price_label,
            warnings=warnings,
        )

    if charge_condition:
        return ScheduleRecommendation(
            timestamp=timestamp,
            action="charge",
            reason="price is low with headroom, or PV output exceeds load with headroom",
            price_classification=price_label,
        )

    return ScheduleRecommendation(
        timestamp=timestamp,
        action="hold",
        reason="no charge, discharge, or safety condition is met",
        price_classification=price_label,
    )
