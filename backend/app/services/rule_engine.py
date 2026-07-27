import pandas as pd

from app.schemas import (
    AnomalyResult,
    BatteryDischargeAnalysisResult,
    BatteryDischargeEvidence,
    PriceThresholdInfo,
)

MINIMUM_PRICE_SAMPLES = 5
DISCRETE_TOU_MAX_DISTINCT_VALUES = 3
HIGH_PRICE_PERCENTILE = 0.75
RULE_VERSION = "battery_should_discharge_v1"
ANALYSIS_TYPE = "battery_should_discharge_but_did_not"

# columns that must exist on the input DataFrame so downstream column access
# never raises KeyError, even when the caller's rows are missing a key entirely
_REQUIRED_COLUMNS = [
    "timestamp",
    "electricity_price",
    "grid_import_kw",
    "contract_capacity_kw",
    "battery_soc",
    "battery_power_kw",
]

# fixed, non-LLM-generated suggested actions per docs/MVP1_RULES.md 4.6
SUGGESTED_ACTIONS = [
    "recommend battery discharge",
    "check EMS mode",
    "check equipment status",
    "check whether battery protection mode is active",
]


def _to_optional_float(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return float(value)


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


def _compute_price_threshold(prices: pd.Series) -> PriceThresholdInfo:
    """Decide how to define "electricity_price is high" for this dataset.

    Dataset-relative on purpose: electricity_price is a simplified TOU price
    (docs/DATA_SCHEMA.md), so its scale is arbitrary per dataset/site — there
    is no universal absolute number to hardcode, unlike e.g. battery_soc.
    """
    non_null = prices.dropna()
    sample_count = int(len(non_null))
    distinct_count = int(non_null.nunique())

    if sample_count < MINIMUM_PRICE_SAMPLES:
        return PriceThresholdInfo(
            mode="insufficient_data",
            threshold=None,
            non_null_sample_count=sample_count,
            distinct_price_count=distinct_count,
            reason=(
                f"non-null electricity_price sample count ({sample_count}) is "
                f"below the minimum required ({MINIMUM_PRICE_SAMPLES})"
            ),
        )

    if distinct_count < 2:
        return PriceThresholdInfo(
            mode="no_distinguishable_peak",
            threshold=None,
            non_null_sample_count=sample_count,
            distinct_price_count=distinct_count,
            reason="electricity_price does not vary in this dataset; no peak price period can be identified",
        )

    if distinct_count <= DISCRETE_TOU_MAX_DISTINCT_VALUES:
        return PriceThresholdInfo(
            mode="discrete_tou_max",
            threshold=float(non_null.max()),
            non_null_sample_count=sample_count,
            distinct_price_count=distinct_count,
        )

    return PriceThresholdInfo(
        mode="percentile",
        threshold=float(non_null.quantile(HIGH_PRICE_PERCENTILE, interpolation="linear")),
        non_null_sample_count=sample_count,
        distinct_price_count=distinct_count,
    )


def evaluate_battery_should_discharge_but_did_not(rows: list[dict]) -> BatteryDischargeAnalysisResult:
    """Evaluate docs/MVP1_RULES.md 4.6 (BATTERY_SHOULD_DISCHARGE_BUT_DID_NOT) for one dataset.

    Pure function, no DB access: rows is already-fetched energy_timeseries data
    for a single dataset. Anomalies are returned in the same order as rows.
    """
    input_row_count = len(rows)

    df = pd.DataFrame(rows)
    for col in _REQUIRED_COLUMNS:
        if col not in df.columns:
            df[col] = None

    price_threshold = _compute_price_threshold(df["electricity_price"])

    if price_threshold.threshold is None:
        price_high_mask = pd.Series(False, index=df.index)
    else:
        price_high_mask = df["electricity_price"].notna() & (
            df["electricity_price"] >= price_threshold.threshold
        )

    evaluable_mask = (
        df["electricity_price"].notna()
        & df["grid_import_kw"].notna()
        & df["contract_capacity_kw"].notna()
        & (df["contract_capacity_kw"] > 0)
        & df["battery_soc"].notna()
        & df["battery_power_kw"].notna()
    )
    evaluated_row_count = int(evaluable_mask.sum())

    grid_ratio_mask = evaluable_mask & (df["grid_import_kw"] >= 0.90 * df["contract_capacity_kw"])
    soc_mask = evaluable_mask & (df["battery_soc"] > 30)
    power_mask = evaluable_mask & (df["battery_power_kw"] <= 0)

    flagged_mask = evaluable_mask & price_high_mask & grid_ratio_mask & soc_mask & power_mask

    anomalies: list[AnomalyResult] = []
    for idx in df.index[flagged_mask]:
        row = df.loc[idx]
        grid_import_kw = _to_optional_float(row["grid_import_kw"])
        contract_capacity_kw = _to_optional_float(row["contract_capacity_kw"])
        evidence = BatteryDischargeEvidence(
            electricity_price=_to_optional_float(row["electricity_price"]),
            high_price_threshold=price_threshold.threshold,
            price_threshold_mode=price_threshold.mode,
            grid_import_kw=grid_import_kw,
            contract_capacity_kw=contract_capacity_kw,
            contract_capacity_ratio=grid_import_kw / contract_capacity_kw,
            battery_soc=_to_optional_float(row["battery_soc"]),
            battery_power_kw=_to_optional_float(row["battery_power_kw"]),
            non_null_price_sample_count=price_threshold.non_null_sample_count,
            distinct_price_count=price_threshold.distinct_price_count,
        )
        anomalies.append(
            AnomalyResult(
                anomaly_type=ANALYSIS_TYPE.upper(),
                severity="warning",
                timestamp=_to_optional_timestamp(row.get("timestamp")),
                evidence=evidence,
                suggested_actions=list(SUGGESTED_ACTIONS),
            )
        )

    return BatteryDischargeAnalysisResult(
        rule=ANALYSIS_TYPE,
        rule_version=RULE_VERSION,
        price_threshold=price_threshold,
        input_row_count=input_row_count,
        evaluated_row_count=evaluated_row_count,
        flagged_row_count=len(anomalies),
        anomalies=anomalies,
    )
