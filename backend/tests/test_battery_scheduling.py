from datetime import datetime, timedelta

from app.services.battery_scheduling import evaluate_battery_scheduling

# Background rows all share electricity_price=2.0 (low tier); the target
# row under test uses whatever price is passed via overrides -- with only
# 2 distinct prices in the dataset, price classification lands in
# deterministic discrete_tou_max mode (low=2.0, high=8.0), avoiding any
# percentile-edge-case noise in these scheduling tests.
BASE_TS = datetime(2026, 1, 1)
BACKGROUND_PRICE = 2.0


def _background_row(hour: int) -> dict:
    # Alternate between the two price tiers so both "low" (2.0) and "high"
    # (8.0) are always represented in the dataset regardless of which tier
    # the target row under test uses -- otherwise a target-only price would
    # leave only 1 distinct value and collapse into no_distinguishable_peak.
    price = BACKGROUND_PRICE if hour % 2 == 0 else 8.0
    return {
        "timestamp": BASE_TS + timedelta(hours=hour),
        "electricity_price": price,
        "battery_temperature": 25.0,
        "battery_health_status": "normal",
        "battery_soc": 50.0,
        "battery_soh": 90.0,
        "pv_actual_kw": 5.0,
        "load_kw": 10.0,
        "grid_import_kw": 10.0,
        "contract_capacity_kw": 100.0,
        "battery_power_kw": 0.0,
    }


def _rows_with_target(overrides: dict, n_background: int = 5):
    rows = [_background_row(h) for h in range(n_background)]
    target = _background_row(n_background)
    target.update(overrides)
    rows.append(target)
    return rows, n_background  # target is always the last row


def _target_recommendation(overrides: dict, n_background: int = 5):
    rows, target_idx = _rows_with_target(overrides, n_background)
    result = evaluate_battery_scheduling(rows)
    return result.recommendations[target_idx], result


def test_temperature_critical_is_blanket_idle_even_with_discharge_conditions():
    rec, _ = _target_recommendation(
        {
            "electricity_price": 8.0,
            "battery_temperature": 45.0,
            "battery_soc": 50.0,
            "grid_import_kw": 90.0,
            "contract_capacity_kw": 100.0,
        }
    )
    assert rec.action == "idle"
    assert "temperature" in rec.reason


def test_health_critical_is_blanket_idle_even_with_discharge_conditions():
    rec, _ = _target_recommendation(
        {
            "electricity_price": 8.0,
            "battery_health_status": "critical",
            "battery_soc": 50.0,
            "grid_import_kw": 90.0,
            "contract_capacity_kw": 100.0,
        }
    )
    assert rec.action == "idle"
    assert "critical" in rec.reason


def test_low_soc_with_charge_condition_charges():
    rec, _ = _target_recommendation(
        {
            "electricity_price": BACKGROUND_PRICE,  # low
            "battery_soc": 15.0,
        }
    )
    assert rec.action == "charge"
    assert "soc <= 20" in rec.reason


def test_low_soc_without_charge_condition_is_idle_not_discharge():
    rec, _ = _target_recommendation(
        {
            "electricity_price": 8.0,  # high, not low
            "battery_soc": 15.0,
            "pv_actual_kw": 1.0,
            "load_kw": 10.0,  # PV does not exceed load
        }
    )
    assert rec.action == "idle"


def test_soh_low_with_charge_condition_charges():
    rec, _ = _target_recommendation(
        {
            "electricity_price": BACKGROUND_PRICE,  # low
            "battery_soh": 70.0,
            "battery_soc": 50.0,
        }
    )
    assert rec.action == "charge"


def test_soh_low_without_charge_condition_holds_never_discharges():
    rec, _ = _target_recommendation(
        {
            "electricity_price": 8.0,  # high
            "battery_soh": 70.0,
            "battery_soc": 50.0,
            "pv_actual_kw": 1.0,
            "load_kw": 10.0,
            "grid_import_kw": 90.0,  # discharge conditions would otherwise hold
            "contract_capacity_kw": 100.0,
        }
    )
    assert rec.action == "hold"


def test_tie_break_discharge_wins_with_conflicting_signal_warning():
    rec, _ = _target_recommendation(
        {
            "electricity_price": 8.0,  # high -> discharge price condition
            "battery_soc": 50.0,  # >30 and <90 -> satisfies both branches
            "grid_import_kw": 90.0,
            "contract_capacity_kw": 100.0,  # ratio 0.9 >= 0.80
            "pv_actual_kw": 20.0,
            "load_kw": 10.0,  # PV > load -> charge PV branch also true
        }
    )
    assert rec.action == "discharge"
    assert "conflicting_energy_flow_signals" in rec.warnings


def test_discharge_only_no_conflict_warning():
    rec, _ = _target_recommendation(
        {
            "electricity_price": 8.0,
            "battery_soc": 50.0,
            "grid_import_kw": 90.0,
            "contract_capacity_kw": 100.0,
            "pv_actual_kw": 1.0,
            "load_kw": 10.0,  # PV does not exceed load -> no charge condition
        }
    )
    assert rec.action == "discharge"
    assert rec.warnings == []


def test_charge_only_low_price():
    rec, _ = _target_recommendation(
        {
            "electricity_price": BACKGROUND_PRICE,
            "battery_soc": 50.0,
        }
    )
    assert rec.action == "charge"
    assert rec.warnings == []


def test_hold_when_nothing_applies():
    rec, _ = _target_recommendation(
        {
            "electricity_price": 8.0,  # high, but soc not >30 so discharge fails
            "battery_soc": 25.0,
            "pv_actual_kw": 1.0,
            "load_kw": 10.0,
        }
    )
    assert rec.action == "hold"


def test_insufficient_row_data_when_all_target_columns_missing():
    rows, target_idx = _rows_with_target(
        {
            "battery_temperature": None,
            "battery_health_status": None,
            "battery_soc": None,
            "battery_soh": None,
            "pv_actual_kw": None,
            "load_kw": None,
            "grid_import_kw": None,
            "contract_capacity_kw": None,
        }
    )
    result = evaluate_battery_scheduling(rows)
    rec = result.recommendations[target_idx]

    assert rec.action == "hold"
    assert "insufficient_row_data" in rec.warnings
    assert result.evaluated_row_count == len(rows) - 1


def test_price_threshold_and_classification_are_discrete_tou_two_tier():
    rows, target_idx = _rows_with_target({"electricity_price": 8.0})
    result = evaluate_battery_scheduling(rows)

    assert result.price_threshold.mode == "discrete_tou_max"
    assert result.price_threshold.low_threshold == BACKGROUND_PRICE
    assert result.price_threshold.high_threshold == 8.0
    assert result.recommendations[target_idx].price_classification == "high"
    assert result.recommendations[0].price_classification == "low"
