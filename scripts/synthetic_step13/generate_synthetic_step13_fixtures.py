"""Synthetic-only CSV fixtures for Step 13 ingestion/API/dashboard/edge-case
testing. NOT Step 13.7 real-world validation data -- see fixtures/README.md.

Deterministic: fixed random seed (SEED). Re-running this script regenerates
byte-identical CSVs.

Usage (from repo root, AI_Copilot conda env):
    python scripts/synthetic_step13/generate_synthetic_step13_fixtures.py
"""

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 13
OUT_DIR = Path(__file__).parent / "fixtures"
BASE_TS = datetime(2026, 3, 1, 0, 0, 0)
INTERVAL_MINUTES = 15
ROWS_PER_DAY = 24 * 60 // INTERVAL_MINUTES  # 96


def _timestamps(n=ROWS_PER_DAY, start=BASE_TS):
    return [start + timedelta(minutes=INTERVAL_MINUTES * i) for i in range(n)]


def _pv_curve(hour_frac):
    """Bell-shaped daylight PV curve, 0 outside 06:00-18:00, peak ~12:00."""
    x = (hour_frac - 12.0) / 6.0
    curve = np.clip(1 - x**2, 0, None)
    return np.where((hour_frac >= 6) & (hour_frac <= 18), curve, 0.0)


def _price_tou(hour_frac, rng):
    """3-tier TOU with small jitter: off-peak / mid / peak."""
    price = np.where(
        (hour_frac < 8) | (hour_frac >= 22),
        3.0,
        np.where(hour_frac < 16, 5.0, 8.0),
    )
    jitter = rng.uniform(-0.3, 0.3, size=len(price))
    return np.round(price + jitter, 2)


def _simulate_site(site_id, contract_capacity_kw, rng, second_life=False, n=ROWS_PER_DAY, pv_scale=60.0):
    ts = _timestamps(n)
    hour_frac = np.array([t.hour + t.minute / 60.0 for t in ts])

    pv_actual = np.round(_pv_curve(hour_frac) * pv_scale * (0.9 + 0.2 * rng.random(n)), 2)
    pv_forecast = np.round(pv_actual * (1.0 + rng.uniform(-0.15, 0.2, n)), 2)
    load = np.round(35 + 15 * np.sin((hour_frac - 8) / 24 * 2 * np.pi) + rng.uniform(-3, 3, n), 2)
    load = np.clip(load, 10, None)
    price = _price_tou(hour_frac, rng)

    soc = np.zeros(n)
    power = np.zeros(n)
    temp = np.zeros(n)
    soc[0] = 50.0
    capacity_kwh = 50.0
    dt_h = INTERVAL_MINUTES / 60.0

    for i in range(n):
        is_peak = price[i] >= 7.0
        is_offpeak = price[i] <= 3.5
        surplus = pv_actual[i] > load[i]

        if is_peak and soc[i] > 30:
            power[i] = min(20.0, (soc[i] - 25) / 100 * capacity_kwh / dt_h)  # discharge, >0
        elif is_offpeak and soc[i] < 80:
            power[i] = -min(20.0, (80 - soc[i]) / 100 * capacity_kwh / dt_h)  # charge, <0
        elif surplus and soc[i] < 90:
            power[i] = -min(pv_actual[i] - load[i], 15.0)  # charge from PV surplus, <0
        else:
            power[i] = 0.0

        temp[i] = round(25 + 6 * abs(power[i]) / 20 + rng.uniform(-1, 1), 1)

        if i + 1 < n:
            delta_soc = -power[i] * dt_h / capacity_kwh * 100  # charge(<0 power) -> +soc
            soc[i + 1] = float(np.clip(soc[i] + delta_soc, 18, 92))

    power = np.round(power, 2)
    soc = np.round(soc, 2)

    net_load = load - pv_actual - power
    grid_import = np.round(np.clip(net_load, 0, None), 2)
    grid_export = np.round(np.clip(-net_load, 0, None), 2)

    df = pd.DataFrame(
        {
            "timestamp": [t.strftime("%Y-%m-%d %H:%M:%S") for t in ts],
            "site_id": site_id,
            "pv_forecast_kw": pv_forecast,
            "pv_actual_kw": pv_actual,
            "load_kw": load,
            "load_forecast_kw": np.round(load * (1 + rng.uniform(-0.05, 0.05, n)), 2),
            "battery_soc": soc,
            "battery_power_kw": power,
            "battery_temperature": temp,
            "electricity_price": price,
            "contract_capacity_kw": contract_capacity_kw,
            "grid_import_kw": grid_import,
            "grid_export_kw": grid_export,
            "weather_condition": np.where(pv_actual > pv_scale * 0.4, "sunny", "cloudy"),
            "ghi": np.round(_pv_curve(hour_frac) * 900, 1),
            "temperature": np.round(22 + 6 * _pv_curve(hour_frac) + rng.uniform(-1, 1, n), 1),
            "humidity": np.round(55 + rng.uniform(-10, 10, n), 1),
            "ems_mode": "auto",
            "equipment_status": "normal",
            "battery_soh": np.round(93 + rng.uniform(-0.5, 0.5, n), 2),
            "battery_cycle_count": 120,
            "battery_equivalent_cycle": np.round(118 + np.arange(n) * 0.01, 2),
            "battery_health_status": "normal",
            "battery_is_second_life": second_life,
            "battery_rated_capacity_kwh": capacity_kwh,
            "battery_available_capacity_kwh": np.round(capacity_kwh * 0.9, 2),
        }
    )
    return df


def build_happy_path_multisite():
    rng = np.random.default_rng(SEED)
    site_a = _simulate_site("site_001", 100.0, rng, pv_scale=60.0)
    rng2 = np.random.default_rng(SEED + 1)
    site_b = _simulate_site("site_002", 150.0, rng2, pv_scale=90.0)
    return pd.concat([site_a, site_b], ignore_index=True)


def build_battery_second_life():
    rng = np.random.default_rng(SEED + 2)
    df = _simulate_site("site_sl01", 80.0, rng, second_life=True, pv_scale=40.0)
    # Confirmed-safe path for _compute_second_life_bonus: keep temperature well
    # under BATTERY_HEALTH_TEMP_THRESHOLD (40) and health_status fully "normal".
    df["battery_temperature"] = np.clip(df["battery_temperature"], 20, 34)
    df["battery_health_status"] = "normal"
    return df


def build_missing_optional_fields():
    """Only the 4 required-group columns + timestamp/site_id in the header --
    battery_soc, battery_temperature, battery_health_status, battery_soh,
    contract_capacity_kw, grid_export_kw are entirely absent (structural
    missing, not just row-level null)."""
    rng = np.random.default_rng(SEED + 3)
    n = ROWS_PER_DAY
    ts = _timestamps(n)
    hour_frac = np.array([t.hour + t.minute / 60.0 for t in ts])
    pv_actual = np.round(_pv_curve(hour_frac) * 50 * (0.9 + 0.2 * rng.random(n)), 2)
    load = np.round(30 + 10 * np.sin((hour_frac - 8) / 24 * 2 * np.pi) + rng.uniform(-2, 2, n), 2)
    price = _price_tou(hour_frac, rng)
    # simple decision pattern not tied to SOC (SOC is absent from this fixture)
    power = np.where(price >= 7.0, 8.0, np.where(price <= 3.5, -8.0, 0.0))
    power = np.round(power + rng.uniform(-0.5, 0.5, n), 2)

    return pd.DataFrame(
        {
            "timestamp": [t.strftime("%Y-%m-%d %H:%M:%S") for t in ts],
            "site_id": "site_partial01",
            "pv_actual_kw": pv_actual,
            "load_kw": load,
            "battery_power_kw": power,
            "electricity_price": price,
        }
    )


def build_timestamp_edge_cases_partial():
    rng = np.random.default_rng(SEED + 4)
    n = 30
    base = _simulate_site("site_tsedge01", 100.0, rng, n=n, pv_scale=50.0)
    invalid_positions = [3, 8, 14, 19, 23, 27]
    invalid_values = [
        "not-a-date",
        "",
        "32/13/2026",
        "2026-99-99",
        "N/A",
        "2026-03-01 25:70:00",
    ]
    ts_col = base["timestamp"].tolist()
    for pos, bad in zip(invalid_positions, invalid_values):
        ts_col[pos] = bad
    base["timestamp"] = ts_col
    return base


def build_timestamp_edge_cases_all_invalid():
    rng = np.random.default_rng(SEED + 5)
    n = 10
    base = _simulate_site("site_tsedge02", 100.0, rng, n=n, pv_scale=50.0)
    base["timestamp"] = [f"invalid-timestamp-{i}" for i in range(n)]
    return base


def build_invalid_enum_and_sign_cases():
    rng = np.random.default_rng(SEED + 6)
    n = 20
    df = _simulate_site("site_enumsign01", 100.0, rng, n=n, pv_scale=55.0)

    # Explicit sign-convention documentation pairs: force clean charge/discharge
    # rows whose SOC delta matches the documented sign (battery_power_kw>0 =
    # discharge -> SOC should fall; <0 = charge -> SOC should rise). These are
    # deterministic overrides on top of the base simulation, not evidence for
    # real-world sign-convention validation (README makes this explicit).
    df.loc[0, ["battery_soc", "battery_power_kw"]] = [70.0, 10.0]   # discharge
    df.loc[1, ["battery_soc", "battery_power_kw"]] = [60.0, 10.0]   # SOC fell 10 after row 0's discharge
    df.loc[2, ["battery_soc", "battery_power_kw"]] = [60.0, -10.0]  # charge
    df.loc[3, ["battery_soc", "battery_power_kw"]] = [70.0, -10.0]  # SOC rose 10 after row 2's charge

    # Invalid enum / boolean cases -- ingestion.py must coerce these to
    # "unknown" / NULL with warnings, not crash or reject the whole upload.
    df["battery_is_second_life"] = df["battery_is_second_life"].astype(object)
    df.loc[5, "battery_health_status"] = "totally_bogus"
    df.loc[6, "ems_mode"] = "not_a_real_mode"
    df.loc[7, "equipment_status"] = "???"
    df.loc[8, "battery_is_second_life"] = "maybe"

    return df


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fixtures = {
        "happy_path_multisite.csv": build_happy_path_multisite(),
        "battery_second_life.csv": build_battery_second_life(),
        "missing_optional_fields.csv": build_missing_optional_fields(),
        "timestamp_edge_cases_partial.csv": build_timestamp_edge_cases_partial(),
        "timestamp_edge_cases_all_invalid.csv": build_timestamp_edge_cases_all_invalid(),
        "invalid_enum_and_sign_cases.csv": build_invalid_enum_and_sign_cases(),
    }
    for filename, df in fixtures.items():
        path = OUT_DIR / filename
        df.to_csv(path, index=False)
        print(f"wrote {path} ({len(df)} rows)")


if __name__ == "__main__":
    main()
