import io

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ["timestamp", "site_id"]

# at least one column from any of these groups must be present in the CSV
BASIC_COLUMN_GROUPS = [
    ["pv_forecast_kw", "pv_actual_kw"],
    ["load_kw", "load_forecast_kw"],
    ["battery_soc", "battery_power_kw"],
    ["electricity_price"],
]

NUMERIC_FLOAT_COLUMNS = [
    "pv_forecast_kw",
    "pv_actual_kw",
    "load_kw",
    "load_forecast_kw",
    "battery_soc",
    "battery_power_kw",
    "battery_temperature",
    "electricity_price",
    "contract_capacity_kw",
    "grid_import_kw",
    "grid_export_kw",
    "ghi",
    "temperature",
    "humidity",
    "battery_soh",
    "battery_equivalent_cycle",
    "battery_rated_capacity_kwh",
    "battery_available_capacity_kwh",
]

NUMERIC_INT_COLUMNS = ["battery_cycle_count"]

STRING_COLUMNS = ["site_id", "weather_condition", "ems_mode", "equipment_status"]

PERCENT_RANGE_COLUMNS = ["battery_soc", "battery_soh"]

BATTERY_HEALTH_STATUS_VALUES = {"normal", "warning", "critical", "unknown"}

# canonical allowed values per docs/DATA_SCHEMA.md section 3 / section 7 rules 11-12
EMS_MODE_VALUES = {
    "auto",
    "manual",
    "schedule",
    "tou_arbitrage",
    "peak_shaving",
    "self_consumption",
    "idle",
    "fallback",
    "error",
    "unknown",
}

EQUIPMENT_STATUS_VALUES = {
    "normal",
    "warning",
    "fault",
    "error",
    "offline",
    "maintenance",
    "unknown",
}

ALL_ENERGY_TIMESERIES_COLUMNS = [
    "timestamp",
    "site_id",
    "pv_forecast_kw",
    "pv_actual_kw",
    "load_kw",
    "load_forecast_kw",
    "battery_soc",
    "battery_power_kw",
    "battery_temperature",
    "electricity_price",
    "contract_capacity_kw",
    "grid_import_kw",
    "grid_export_kw",
    "weather_condition",
    "ghi",
    "temperature",
    "humidity",
    "ems_mode",
    "equipment_status",
    "battery_soh",
    "battery_cycle_count",
    "battery_equivalent_cycle",
    "battery_health_status",
    "battery_is_second_life",
    "battery_rated_capacity_kwh",
    "battery_available_capacity_kwh",
]


class IngestionError(Exception):
    pass


def _to_python(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _normalize_health_status(value):
    if pd.isna(value):
        return None
    return str(value).strip().lower()


def _normalize_enum_value(value):
    if pd.isna(value):
        return None
    return str(value).strip().lower()


def _normalize_bool(value):
    if pd.isna(value):
        return None, False
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True, False
    if text in ("false", "0", "no"):
        return False, False
    return None, True


def parse_and_validate_csv(file_bytes: bytes):
    """Parse a CSV file into rows ready for energy_timeseries insertion.

    Returns (rows, warnings) where rows is a list of dicts keyed by
    ALL_ENERGY_TIMESERIES_COLUMNS. Raises IngestionError for CSV-level
    problems that reject the whole upload.
    """
    warnings = []

    try:
        df = pd.read_csv(io.BytesIO(file_bytes))
    except Exception as e:
        raise IngestionError(f"failed to parse CSV: {e}")

    df.columns = [str(c).strip() for c in df.columns]

    missing_required = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_required:
        raise IngestionError(f"missing required columns: {missing_required}")

    if not any(any(c in df.columns for c in group) for group in BASIC_COLUMN_GROUPS):
        raise IngestionError(
            "CSV must contain at least one basic column from PV, Load, Battery, or Price"
        )

    for col in ALL_ENERGY_TIMESERIES_COLUMNS:
        if col not in df.columns:
            df[col] = None
            warnings.append(
                {
                    "row": None,
                    "column": col,
                    "issue": "column missing in CSV",
                    "action": "stored as NULL for all rows",
                }
            )

    # timestamp: rows that fail to parse are dropped
    parsed_timestamp = pd.to_datetime(df["timestamp"], errors="coerce")
    invalid_timestamp_mask = parsed_timestamp.isna()
    for idx in df.index[invalid_timestamp_mask]:
        warnings.append(
            {
                "row": int(idx) + 2,
                "column": "timestamp",
                "issue": f"could not parse timestamp value '{df.at[idx, 'timestamp']}'",
                "action": "row skipped",
            }
        )
    df["timestamp"] = parsed_timestamp
    df = df[~invalid_timestamp_mask].copy()

    # numeric float columns: failed conversions become NULL, row is kept
    for col in NUMERIC_FLOAT_COLUMNS:
        original = df[col]
        converted = pd.to_numeric(original, errors="coerce")
        bad_mask = converted.isna() & original.notna()
        for idx in df.index[bad_mask]:
            warnings.append(
                {
                    "row": int(idx) + 2,
                    "column": col,
                    "issue": f"could not convert value '{original.at[idx]}' to numeric",
                    "action": "stored as NULL",
                }
            )
        df[col] = converted

    # numeric int columns: same rule, rounded before casting
    for col in NUMERIC_INT_COLUMNS:
        original = df[col]
        converted = pd.to_numeric(original, errors="coerce")
        bad_mask = converted.isna() & original.notna()
        for idx in df.index[bad_mask]:
            warnings.append(
                {
                    "row": int(idx) + 2,
                    "column": col,
                    "issue": f"could not convert value '{original.at[idx]}' to numeric",
                    "action": "stored as NULL",
                }
            )
        df[col] = converted.round()

    # battery_soc / battery_soh expected range 0-100 (kept as-is, only warned)
    for col in PERCENT_RANGE_COLUMNS:
        out_of_range_mask = df[col].notna() & ((df[col] < 0) | (df[col] > 100))
        for idx in df.index[out_of_range_mask]:
            warnings.append(
                {
                    "row": int(idx) + 2,
                    "column": col,
                    "issue": f"value {df.at[idx, col]} out of expected range 0-100",
                    "action": "kept as-is",
                }
            )

    # battery_health_status enum
    df["battery_health_status"] = df["battery_health_status"].apply(_normalize_health_status)
    invalid_health_mask = df["battery_health_status"].notna() & ~df["battery_health_status"].isin(
        BATTERY_HEALTH_STATUS_VALUES
    )
    for idx in df.index[invalid_health_mask]:
        warnings.append(
            {
                "row": int(idx) + 2,
                "column": "battery_health_status",
                "issue": (
                    f"invalid value '{df.at[idx, 'battery_health_status']}', "
                    f"expected one of {sorted(BATTERY_HEALTH_STATUS_VALUES)}"
                ),
                "action": "stored as 'unknown'",
            }
        )
    df.loc[invalid_health_mask, "battery_health_status"] = "unknown"

    # ems_mode / equipment_status canonical enums (docs/DATA_SCHEMA.md section 7, rules 11-12)
    enum_columns = [
        ("ems_mode", EMS_MODE_VALUES),
        ("equipment_status", EQUIPMENT_STATUS_VALUES),
    ]
    for col, allowed_values in enum_columns:
        df[col] = df[col].apply(_normalize_enum_value)
        invalid_mask = df[col].notna() & ~df[col].isin(allowed_values)
        for idx in df.index[invalid_mask]:
            warnings.append(
                {
                    "row": int(idx) + 2,
                    "column": col,
                    "issue": (
                        f"invalid value '{df.at[idx, col]}', "
                        f"expected one of {sorted(allowed_values)}"
                    ),
                    "action": "stored as 'unknown'",
                }
            )
        df.loc[invalid_mask, col] = "unknown"

    # battery_is_second_life boolean
    normalized_bool = df["battery_is_second_life"].apply(_normalize_bool)
    df["battery_is_second_life"] = normalized_bool.apply(lambda pair: pair[0])
    invalid_bool_mask = normalized_bool.apply(lambda pair: pair[1])
    for idx in df.index[invalid_bool_mask]:
        warnings.append(
            {
                "row": int(idx) + 2,
                "column": "battery_is_second_life",
                "issue": "invalid boolean value, expected true or false",
                "action": "stored as NULL",
            }
        )

    # string columns: strip whitespace
    for col in STRING_COLUMNS:
        df[col] = df[col].apply(lambda v: str(v).strip() if pd.notna(v) else None)

    records = df[ALL_ENERGY_TIMESERIES_COLUMNS].to_dict(orient="records")
    rows = [{k: _to_python(v) for k, v in record.items()} for record in records]

    return rows, warnings
