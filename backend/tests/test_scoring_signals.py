import pandas as pd

from app.services.price_classification import compute_price_threshold
from app.services.scoring_signals import (
    evaluate_battery_health_risk_mask,
    evaluate_green_energy_waste_mask,
    evaluate_low_soc_risk_mask,
    evaluate_over_contract_risk_mask,
    evaluate_peak_period_abnormal_charging_mask,
)


def test_over_contract_risk_flags_high_ratio_and_respects_eligibility():
    df = pd.DataFrame(
        {
            "grid_import_kw": [95.0, 50.0, None],
            "contract_capacity_kw": [100.0, 100.0, 100.0],
        }
    )

    result = evaluate_over_contract_risk_mask(df)

    assert list(result.eligible) == [True, True, False]
    assert list(result.flagged) == [True, False, False]


def test_over_contract_risk_missing_columns_all_ineligible():
    df = pd.DataFrame({"battery_soc": [50.0]})

    result = evaluate_over_contract_risk_mask(df)

    assert list(result.eligible) == [False]
    assert list(result.flagged) == [False]


def test_battery_health_risk_truth_table():
    df = pd.DataFrame(
        {
            "battery_temperature": [42.0, 20.0, 20.0, 42.0, None],
            "battery_soh": [None, 90.0, None, None, None],
            "battery_health_status": [None, "normal", None, None, None],
        }
    )
    # row 0: only temperature present, and it triggers -> eligible+flagged
    #        (an OR rule's positive determination never needs the other
    #        columns -- one confirmed trigger is enough)
    # row 1: all three present, none trigger -> eligible, not flagged
    #        (only now is "not flagged" actually confirmed)
    # row 2: only temperature present, and it does NOT trigger, soh/status
    #        missing -> ineligible/unknown (a missing column could still
    #        have triggered; partial-safe is not the same as confirmed-safe)
    # row 3: temperature triggers AND soh/status are also missing ->
    #        still eligible+flagged (case 1 takes priority regardless of
    #        how much other data is missing)
    # row 4: all three missing -> ineligible

    result = evaluate_battery_health_risk_mask(df)

    assert list(result.eligible) == [True, True, False, True, False]
    assert list(result.flagged) == [True, False, False, True, False]


def test_battery_health_risk_any_known_trigger_is_eligible_and_flagged_even_with_partial_data():
    df = pd.DataFrame(
        {
            "battery_temperature": [None],
            "battery_soh": [70.0],  # < 80 -- triggers
            "battery_health_status": [None],
        }
    )

    result = evaluate_battery_health_risk_mask(df)

    assert list(result.eligible) == [True]
    assert list(result.flagged) == [True]


def test_battery_health_risk_ineligible_when_all_columns_missing():
    df = pd.DataFrame({"battery_soc": [50.0]})

    result = evaluate_battery_health_risk_mask(df)

    assert list(result.eligible) == [False]
    assert list(result.flagged) == [False]


def test_low_soc_risk():
    df = pd.DataFrame({"battery_soc": [15.0, 25.0, None]})

    result = evaluate_low_soc_risk_mask(df)

    assert list(result.eligible) == [True, True, False]
    assert list(result.flagged) == [True, False, False]


def test_green_energy_waste_requires_all_three_columns():
    df = pd.DataFrame(
        {
            "grid_export_kw": [5.0, 5.0, None],
            "battery_soc": [50.0, 95.0, 50.0],
            "battery_power_kw": [1.0, 1.0, 1.0],
        }
    )

    result = evaluate_green_energy_waste_mask(df)

    assert list(result.eligible) == [True, True, False]
    # row 0: export>0, soc<90, power>=0 -> flagged
    # row 1: soc=95 not <90 -> not flagged
    assert list(result.flagged) == [True, False, False]


def test_peak_period_abnormal_charging_uses_price_classification():
    df = pd.DataFrame(
        {
            "electricity_price": [float(x) for x in range(1, 21)],
            "battery_power_kw": [-1.0] * 20,
        }
    )
    threshold = compute_price_threshold(df["electricity_price"])

    result = evaluate_peak_period_abnormal_charging_mask(df, threshold)

    assert bool(result.eligible.all())
    # only rows classified "high" (price > 75th percentile) AND charging should flag
    high_price_rows = df["electricity_price"] > threshold.high_threshold
    assert list(result.flagged) == list(high_price_rows & (df["battery_power_kw"] < 0))
    assert result.flagged.sum() > 0


def test_peak_period_abnormal_charging_ineligible_when_threshold_unusable():
    df = pd.DataFrame({"electricity_price": [5.0, 5.0], "battery_power_kw": [-1.0, -1.0]})
    threshold = compute_price_threshold(df["electricity_price"])  # constant -> no_distinguishable_peak

    result = evaluate_peak_period_abnormal_charging_mask(df, threshold)

    assert list(result.eligible) == [False, False]
    assert list(result.flagged) == [False, False]
