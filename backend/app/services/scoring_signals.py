from typing import NamedTuple

import pandas as pd

from app.schemas import PriceClassificationThreshold
from app.services.price_classification import classify_price_series

# The 5 internal scoring signals reused by cost_estimation.py and
# green_operations_index.py (docs/step13_rules_and_api_design.md 2.2).
# These are NOT exposed as anomaly diagnosis results: no anomaly_type,
# no new endpoint, no claim that the remaining 7 anomaly rules
# (PROGRESS.md Known Issues) are implemented. Every threshold below is
# taken verbatim from docs/MVP1_RULES.md -- nothing invented here.

OVER_CONTRACT_RATIO = 0.90
LOW_SOC_THRESHOLD = 20
GREEN_ENERGY_WASTE_SOC_THRESHOLD = 90
BATTERY_HEALTH_TEMP_THRESHOLD = 40
BATTERY_HEALTH_SOH_THRESHOLD = 80
BATTERY_HEALTH_STATUS_FLAGS = ("warning", "critical")


class SignalMask(NamedTuple):
    """`eligible`: this row has enough data to evaluate the signal at all.
    `flagged`: eligible AND the rule's condition is true. Never flagged
    without eligible (flagged implies eligible)."""

    eligible: pd.Series
    flagged: pd.Series


def _empty_mask(df: pd.DataFrame) -> SignalMask:
    empty = pd.Series(False, index=df.index)
    return SignalMask(eligible=empty, flagged=empty)


def evaluate_over_contract_risk_mask(df: pd.DataFrame) -> SignalMask:
    """docs/MVP1_RULES.md 4.2: grid_import_kw >= 0.90 * contract_capacity_kw."""
    required = ("grid_import_kw", "contract_capacity_kw")
    if not all(col in df.columns for col in required):
        return _empty_mask(df)

    eligible = (
        df["grid_import_kw"].notna()
        & df["contract_capacity_kw"].notna()
        & (df["contract_capacity_kw"] > 0)
    )
    flagged = eligible & (df["grid_import_kw"] >= OVER_CONTRACT_RATIO * df["contract_capacity_kw"])
    return SignalMask(eligible=eligible, flagged=flagged)


def evaluate_battery_health_risk_mask(df: pd.DataFrame) -> SignalMask:
    """docs/MVP1_RULES.md 4.4: OR of three independent triggers
    (temperature / soh / health_status). An OR rule's negative
    determination ("not flagged") requires ALL THREE columns to rule each
    trigger out -- a missing column could still have been the one that
    triggers, so partial-but-clean data is NOT the same as confirmed-safe:

    1. any known column already triggers -> eligible=True, flagged=True,
       regardless of what the other (possibly missing) columns say.
    2. all three columns present and none trigger -> eligible=True,
       flagged=False (only now is "not flagged" actually confirmed).
    3. some columns missing and none of the present ones trigger ->
       eligible=False (unknown -- the missing column(s) could still flip
       this to True; must not be counted as a confirmed-safe interval).
    """
    temp = df["battery_temperature"] if "battery_temperature" in df.columns else pd.Series(pd.NA, index=df.index)
    soh = df["battery_soh"] if "battery_soh" in df.columns else pd.Series(pd.NA, index=df.index)
    status = (
        df["battery_health_status"]
        if "battery_health_status" in df.columns
        else pd.Series(pd.NA, index=df.index)
    )

    any_triggered = (
        (temp.notna() & (temp >= BATTERY_HEALTH_TEMP_THRESHOLD))
        | (soh.notna() & (soh < BATTERY_HEALTH_SOH_THRESHOLD))
        | (status.notna() & status.isin(BATTERY_HEALTH_STATUS_FLAGS))
    )
    all_known = temp.notna() & soh.notna() & status.notna()

    eligible = any_triggered | all_known
    flagged = any_triggered
    return SignalMask(eligible=eligible, flagged=flagged)


def evaluate_low_soc_risk_mask(df: pd.DataFrame) -> SignalMask:
    """docs/MVP1_RULES.md 4.3: battery_soc < 20."""
    if "battery_soc" not in df.columns:
        return _empty_mask(df)

    eligible = df["battery_soc"].notna()
    flagged = eligible & (df["battery_soc"] < LOW_SOC_THRESHOLD)
    return SignalMask(eligible=eligible, flagged=flagged)


def evaluate_green_energy_waste_mask(df: pd.DataFrame) -> SignalMask:
    """docs/MVP1_RULES.md 4.7: grid_export_kw > 0 AND battery_soc < 90 AND battery_power_kw >= 0."""
    required = ("grid_export_kw", "battery_soc", "battery_power_kw")
    if not all(col in df.columns for col in required):
        return _empty_mask(df)

    eligible = df["grid_export_kw"].notna() & df["battery_soc"].notna() & df["battery_power_kw"].notna()
    flagged = (
        eligible
        & (df["grid_export_kw"] > 0)
        & (df["battery_soc"] < GREEN_ENERGY_WASTE_SOC_THRESHOLD)
        & (df["battery_power_kw"] >= 0)
    )
    return SignalMask(eligible=eligible, flagged=flagged)


def evaluate_peak_period_abnormal_charging_mask(
    df: pd.DataFrame, price_threshold: PriceClassificationThreshold
) -> SignalMask:
    """docs/MVP1_RULES.md 4.5: price is "high" (2.1's dataset-relative
    classification, not a separate absolute threshold) AND battery_power_kw < 0."""
    required = ("electricity_price", "battery_power_kw")
    if not all(col in df.columns for col in required):
        return _empty_mask(df)

    threshold_usable = price_threshold.mode not in ("insufficient_data", "no_distinguishable_peak")
    eligible = df["electricity_price"].notna() & df["battery_power_kw"].notna()
    if not threshold_usable:
        return SignalMask(eligible=pd.Series(False, index=df.index), flagged=pd.Series(False, index=df.index))

    price_class = classify_price_series(df["electricity_price"], price_threshold)
    flagged = eligible & (price_class == "high") & (df["battery_power_kw"] < 0)
    return SignalMask(eligible=eligible, flagged=flagged)
