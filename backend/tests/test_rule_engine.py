from datetime import datetime

from app.services.rule_engine import (
    ANALYSIS_TYPE,
    RULE_VERSION,
    evaluate_battery_should_discharge_but_did_not,
)


def _row(**overrides):
    base = {
        "timestamp": datetime(2026, 1, 1, 0, 0, 0),
        "electricity_price": 5.0,
        "grid_import_kw": 50.0,
        "contract_capacity_kw": 100.0,
        "battery_soc": 50.0,
        "battery_power_kw": 5.0,
    }
    base.update(overrides)
    return base


def test_empty_list_does_not_raise_and_returns_insufficient_data():
    result = evaluate_battery_should_discharge_but_did_not([])

    assert result.input_row_count == 0
    assert result.evaluated_row_count == 0
    assert result.flagged_row_count == 0
    assert result.anomalies == []
    assert result.price_threshold.mode == "insufficient_data"
    assert result.rule == ANALYSIS_TYPE
    assert result.rule_version == RULE_VERSION


def test_missing_required_columns_does_not_raise_keyerror():
    rows = [
        {"timestamp": datetime(2026, 1, 1), "electricity_price": 5.0},
        {"timestamp": datetime(2026, 1, 1, 1), "electricity_price": 6.0},
    ]

    result = evaluate_battery_should_discharge_but_did_not(rows)

    assert result.input_row_count == 2
    assert result.evaluated_row_count == 0
    assert result.flagged_row_count == 0
    assert result.anomalies == []


def test_insufficient_data_below_minimum_samples():
    rows = [_row(electricity_price=p) for p in [1.0, 2.0, 3.0, 4.0]]

    result = evaluate_battery_should_discharge_but_did_not(rows)

    assert result.price_threshold.mode == "insufficient_data"
    assert result.price_threshold.threshold is None
    assert result.price_threshold.non_null_sample_count == 4
    assert result.flagged_row_count == 0


def test_zero_variance_price_is_no_distinguishable_peak():
    rows = [
        _row(electricity_price=5.0, grid_import_kw=95.0, battery_soc=50.0, battery_power_kw=-5.0)
        for _ in range(6)
    ]

    result = evaluate_battery_should_discharge_but_did_not(rows)

    assert result.price_threshold.mode == "no_distinguishable_peak"
    assert result.price_threshold.threshold is None
    assert result.price_threshold.distinct_price_count == 1
    # even though every other condition is satisfied, price can never be "high"
    assert result.flagged_row_count == 0


def test_two_tier_tou_uses_max_as_threshold():
    rows = [_row(electricity_price=p) for p in [3.0, 3.0, 3.0, 7.0, 7.0, 7.0]]

    result = evaluate_battery_should_discharge_but_did_not(rows)

    assert result.price_threshold.mode == "discrete_tou_max"
    assert result.price_threshold.distinct_price_count == 2
    assert result.price_threshold.threshold == 7.0


def test_three_tier_tou_uses_max_as_threshold():
    rows = [_row(electricity_price=p) for p in [3.0, 3.0, 5.0, 5.0, 9.0, 9.0]]

    result = evaluate_battery_should_discharge_but_did_not(rows)

    assert result.price_threshold.mode == "discrete_tou_max"
    assert result.price_threshold.distinct_price_count == 3
    assert result.price_threshold.threshold == 9.0


def test_percentile_mode_used_when_more_than_three_distinct_prices():
    rows = [_row(electricity_price=p) for p in [10.0, 20.0, 30.0, 40.0, 50.0]]

    result = evaluate_battery_should_discharge_but_did_not(rows)

    assert result.price_threshold.mode == "percentile"
    assert result.price_threshold.distinct_price_count == 5
    # 75th percentile, linear interpolation, of [10,20,30,40,50] lands exactly on 40
    assert result.price_threshold.threshold == 40.0


def test_null_prices_excluded_from_threshold_sample_and_never_flagged():
    rows = [_row(electricity_price=p) for p in [10.0, 20.0, 30.0, 40.0, 50.0]]
    rows.append(_row(electricity_price=None, grid_import_kw=95.0, battery_soc=50.0, battery_power_kw=-5.0))
    rows.append(_row(electricity_price=None))

    result = evaluate_battery_should_discharge_but_did_not(rows)

    assert result.price_threshold.non_null_sample_count == 5
    assert result.price_threshold.distinct_price_count == 5
    # null-price rows are never evaluable, regardless of other fields
    assert result.evaluated_row_count == 5


def test_all_four_conditions_must_hold_price_not_high_counterexample():
    rows = [_row(electricity_price=p) for p in [3.0, 3.0, 3.0, 7.0, 7.0, 7.0]]
    rows.append(_row(electricity_price=3.0, grid_import_kw=95.0, battery_soc=50.0, battery_power_kw=-5.0))

    result = evaluate_battery_should_discharge_but_did_not(rows)

    assert result.flagged_row_count == 0


def test_all_four_conditions_must_hold_grid_import_too_low_counterexample():
    rows = [_row(electricity_price=p) for p in [3.0, 3.0, 3.0, 7.0, 7.0, 7.0]]
    rows.append(_row(electricity_price=7.0, grid_import_kw=50.0, contract_capacity_kw=100.0,
                      battery_soc=50.0, battery_power_kw=-5.0))

    result = evaluate_battery_should_discharge_but_did_not(rows)

    assert result.flagged_row_count == 0


def test_all_four_conditions_must_hold_low_soc_counterexample():
    rows = [_row(electricity_price=p) for p in [3.0, 3.0, 3.0, 7.0, 7.0, 7.0]]
    rows.append(_row(electricity_price=7.0, grid_import_kw=95.0, contract_capacity_kw=100.0,
                      battery_soc=25.0, battery_power_kw=-5.0))

    result = evaluate_battery_should_discharge_but_did_not(rows)

    assert result.flagged_row_count == 0


def test_all_four_conditions_must_hold_charging_counterexample():
    rows = [_row(electricity_price=p) for p in [3.0, 3.0, 3.0, 7.0, 7.0, 7.0]]
    rows.append(_row(electricity_price=7.0, grid_import_kw=95.0, contract_capacity_kw=100.0,
                      battery_soc=50.0, battery_power_kw=5.0))

    result = evaluate_battery_should_discharge_but_did_not(rows)

    assert result.flagged_row_count == 0


def test_soc_exactly_30_does_not_trigger():
    rows = [_row(electricity_price=p) for p in [3.0, 3.0, 3.0, 7.0, 7.0, 7.0]]
    rows.append(_row(electricity_price=7.0, grid_import_kw=95.0, contract_capacity_kw=100.0,
                      battery_soc=30.0, battery_power_kw=-5.0))

    result = evaluate_battery_should_discharge_but_did_not(rows)

    assert result.flagged_row_count == 0


def test_battery_power_exactly_zero_triggers():
    rows = [_row(electricity_price=p) for p in [3.0, 3.0, 3.0, 7.0, 7.0, 7.0]]
    rows.append(_row(electricity_price=7.0, grid_import_kw=95.0, contract_capacity_kw=100.0,
                      battery_soc=50.0, battery_power_kw=0.0))

    result = evaluate_battery_should_discharge_but_did_not(rows)

    assert result.flagged_row_count == 1


def test_grid_import_exactly_90_percent_triggers():
    rows = [_row(electricity_price=p) for p in [3.0, 3.0, 3.0, 7.0, 7.0, 7.0]]
    rows.append(_row(electricity_price=7.0, grid_import_kw=90.0, contract_capacity_kw=100.0,
                      battery_soc=50.0, battery_power_kw=-5.0))

    result = evaluate_battery_should_discharge_but_did_not(rows)

    assert result.flagged_row_count == 1
    assert result.anomalies[0].evidence.contract_capacity_ratio == 0.9


def test_price_threshold_boundary_equal_triggers():
    rows = [_row(electricity_price=p) for p in [3.0, 3.0, 3.0, 7.0, 7.0, 7.0]]
    rows.append(_row(electricity_price=7.0, grid_import_kw=95.0, contract_capacity_kw=100.0,
                      battery_soc=50.0, battery_power_kw=-5.0))

    result = evaluate_battery_should_discharge_but_did_not(rows)

    assert result.flagged_row_count == 1
    assert result.anomalies[0].evidence.electricity_price == 7.0
    assert result.anomalies[0].evidence.high_price_threshold == 7.0


def test_contract_capacity_zero_and_negative_are_not_evaluated():
    rows = [_row(electricity_price=p) for p in [3.0, 3.0, 3.0, 7.0, 7.0, 7.0]]
    rows.append(_row(electricity_price=7.0, grid_import_kw=95.0, contract_capacity_kw=0.0,
                      battery_soc=50.0, battery_power_kw=-5.0))
    rows.append(_row(electricity_price=7.0, grid_import_kw=95.0, contract_capacity_kw=-10.0,
                      battery_soc=50.0, battery_power_kw=-5.0))

    result = evaluate_battery_should_discharge_but_did_not(rows)

    assert result.evaluated_row_count == 6  # only the baseline 6 rows, the two extra ones excluded
    assert result.flagged_row_count == 0


def test_counts_and_flagged_row_count_match_anomalies_length():
    rows = [_row(electricity_price=p) for p in [3.0, 3.0, 3.0, 7.0, 7.0, 7.0]]
    # 3 rows that should each be flagged
    for _ in range(3):
        rows.append(_row(electricity_price=7.0, grid_import_kw=95.0, contract_capacity_kw=100.0,
                          battery_soc=50.0, battery_power_kw=-5.0))
    # 1 row that should not be flagged (charging)
    rows.append(_row(electricity_price=7.0, grid_import_kw=95.0, contract_capacity_kw=100.0,
                      battery_soc=50.0, battery_power_kw=5.0))

    result = evaluate_battery_should_discharge_but_did_not(rows)

    assert result.input_row_count == 10
    assert result.evaluated_row_count == 10
    assert result.flagged_row_count == 3
    assert len(result.anomalies) == result.flagged_row_count


def test_anomalies_preserve_input_row_order():
    rows = [_row(electricity_price=p) for p in [3.0, 3.0, 3.0, 7.0, 7.0, 7.0]]
    rows.append(_row(timestamp=datetime(2026, 1, 2, 0), electricity_price=7.0, grid_import_kw=95.0,
                      contract_capacity_kw=100.0, battery_soc=50.0, battery_power_kw=-5.0))
    rows.append(_row(timestamp=datetime(2026, 1, 3, 0), electricity_price=3.0))  # not flagged, price not high
    rows.append(_row(timestamp=datetime(2026, 1, 1, 0), electricity_price=7.0, grid_import_kw=95.0,
                      contract_capacity_kw=100.0, battery_soc=50.0, battery_power_kw=-5.0))

    result = evaluate_battery_should_discharge_but_did_not(rows)

    assert result.flagged_row_count == 2
    assert [a.timestamp for a in result.anomalies] == [
        datetime(2026, 1, 2, 0),
        datetime(2026, 1, 1, 0),
    ]
