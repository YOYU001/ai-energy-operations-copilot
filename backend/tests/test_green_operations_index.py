from datetime import datetime, timedelta

from app.services.green_operations_index import evaluate_green_operations_index

BASE_TS = datetime(2026, 1, 1)
MAX_GAP_HOURS = 24.0


def _row(hour, site_id="site_a", **overrides):
    base = {
        "timestamp": BASE_TS + timedelta(hours=hour),
        "site_id": site_id,
        "grid_import_kw": 10.0,
        "contract_capacity_kw": 100.0,
        "battery_soc": 50.0,
        "battery_power_kw": 0.0,
        "battery_temperature": 25.0,
        "battery_soh": 90.0,
        "battery_health_status": "normal",
        "electricity_price": float(hour + 1),  # varies so price classification is usable
        "grid_export_kw": 0.0,
        "battery_is_second_life": False,
    }
    base.update(overrides)
    return base


def _component(result, site_index, name):
    return next(c for c in result.per_site[site_index].components for c in [c] if c.component == name)


def _get_component(site_result, name):
    return next(c for c in site_result.components if c.component == name)


def test_all_signals_clear_yields_max_scores_and_zero_bonus():
    rows = [_row(h) for h in range(6)]  # 5 intervals, all safe values

    result = evaluate_green_operations_index(rows, MAX_GAP_HOURS)

    site = result.per_site[0]
    scores = {c.component: c for c in site.components}
    assert scores["pv_utilization"].score == 25.0
    assert scores["battery_operation"].score == 20.0
    assert scores["grid_dependency"].score == 20.0
    assert scores["battery_health"].score == 25.0
    assert site.second_life_bonus == 0.0
    assert site.total_score == 90.0


def test_missing_component_columns_is_insufficient_data_and_nulls_total():
    rows = [
        {k: v for k, v in _row(h).items() if k != "grid_export_kw"}  # pv_utilization column missing
        for h in range(6)
    ]

    result = evaluate_green_operations_index(rows, MAX_GAP_HOURS)

    site = result.per_site[0]
    pv = _get_component(site, "pv_utilization")
    assert pv.score is None
    assert pv.status == "insufficient_data"
    assert pv.eligible_duration_hours == 0.0
    assert site.total_score is None  # one null base component nulls the total


def test_same_interval_multiple_signals_are_unioned_not_double_counted():
    rows = [
        _row(0, battery_temperature=45.0, battery_soc=10.0),  # interval 1 (2h): both signals flag
        _row(2, battery_temperature=25.0, battery_soc=50.0),  # interval 2 (3h): neither flags
        _row(5),  # last row, excluded
    ]

    result = evaluate_green_operations_index(rows, MAX_GAP_HOURS)

    health = _get_component(result.per_site[0], "battery_health")
    assert health.eligible_duration_hours == 5.0  # 2h + 3h
    assert health.flagged_duration_hours == 2.0  # interval 1's duration, NOT doubled
    assert health.score == round(25.0 * (1 - 2.0 / 5.0), 2)
    assert set(health.penalty_reasons) == {"battery_health_risk", "low_soc_risk"}


def test_second_life_bonus_true_and_safe():
    rows = [_row(h, battery_is_second_life=True) for h in range(6)]

    result = evaluate_green_operations_index(rows, MAX_GAP_HOURS)

    assert result.per_site[0].second_life_bonus == 10.0


def test_second_life_bonus_disqualified_by_one_unsafe_reading():
    # note: the LAST row of a site is never a valid interval's start_row
    # (compute_valid_intervals excludes it -- no next timestamp), so the
    # unsafe reading must be injected into a non-last row to actually be
    # visible to the second-life bonus computation.
    rows = [_row(h, battery_is_second_life=True) for h in range(6)]
    rows[4] = _row(4, battery_is_second_life=True, battery_temperature=45.0)

    result = evaluate_green_operations_index(rows, MAX_GAP_HOURS)

    assert result.per_site[0].second_life_bonus == 0.0


def test_second_life_bonus_unavailable_when_partial_data_and_nothing_confirmed_unsafe():
    # row 4 (a valid interval's start_row) is missing battery_health_status
    # -- incomplete, but nothing anywhere is confirmed unsafe -- must be
    # reported as unavailable (None), not silently defaulted to 0.
    rows = [_row(h, battery_is_second_life=True) for h in range(6)]
    rows[4] = _row(4, battery_is_second_life=True, battery_health_status=None)

    result = evaluate_green_operations_index(rows, MAX_GAP_HOURS)

    assert result.per_site[0].second_life_bonus is None


def test_second_life_bonus_none_when_column_entirely_missing():
    rows = [{k: v for k, v in _row(h).items() if k != "battery_is_second_life"} for h in range(6)]

    result = evaluate_green_operations_index(rows, MAX_GAP_HOURS)

    assert result.per_site[0].second_life_bonus is None


def test_no_intervals_at_all_is_insufficient_data_for_every_component():
    rows = [_row(0)]  # single row -> no intervals possible

    result = evaluate_green_operations_index(rows, MAX_GAP_HOURS)

    site = result.per_site[0]
    assert all(c.score is None and c.status == "insufficient_data" for c in site.components)
    assert site.total_score is None
    assert site.second_life_bonus is None


def test_multi_site_aggregate_is_duration_weighted():
    # site_a: 1 interval of 10h, fully flagged (score 0 on grid_dependency)
    site_a_rows = [
        _row(0, site_id="site_a", grid_import_kw=95.0, contract_capacity_kw=100.0),
        _row(10, site_id="site_a", grid_import_kw=95.0, contract_capacity_kw=100.0),
    ]
    # site_b: 1 interval of 10h, never flagged (score 20 on grid_dependency)
    site_b_rows = [
        _row(0, site_id="site_b", grid_import_kw=10.0, contract_capacity_kw=100.0),
        _row(10, site_id="site_b", grid_import_kw=10.0, contract_capacity_kw=100.0),
    ]

    result = evaluate_green_operations_index(site_a_rows + site_b_rows, MAX_GAP_HOURS)

    assert result.site_count == 2
    grid_a = _get_component(next(s for s in result.per_site if s.site_id == "site_a"), "grid_dependency")
    grid_b = _get_component(next(s for s in result.per_site if s.site_id == "site_b"), "grid_dependency")
    assert grid_a.score == 0.0
    assert grid_b.score == 20.0

    aggregate_grid = _get_component(result.dataset_aggregate, "grid_dependency")
    # equal 10h weight each -> simple average of 0.0 and 20.0
    assert aggregate_grid.score == 10.0
    assert result.dataset_aggregate.site_id == "__all__"


def test_dataset_level_price_threshold_used_across_sites():
    # site_a's own price range (1-6) alone would classify 6.0 as locally
    # "high" (75th percentile of [1,2,3,4,6,6] is 5.5); combined with
    # site_b's much larger range (101-106), the correct dataset-level
    # threshold (docs/step13_rules_and_api_design.md 2.1) has a 75th
    # percentile around 103.25, so 6.0 must classify as "neutral" instead.
    # A charging event (battery_power_kw < 0) at that price must therefore
    # NOT be flagged as peak_period_abnormal_charging.
    site_a_rows = [_row(h, site_id="site_a") for h in range(6)]
    site_a_rows[4] = _row(4, site_id="site_a", electricity_price=6.0, battery_power_kw=-5.0)
    site_b_rows = [_row(h, site_id="site_b", electricity_price=float(h + 101)) for h in range(6)]

    result = evaluate_green_operations_index(site_a_rows + site_b_rows, MAX_GAP_HOURS)

    battery_op_a = _get_component(next(s for s in result.per_site if s.site_id == "site_a"), "battery_operation")
    assert "peak_period_abnormal_charging" not in battery_op_a.penalty_reasons


def test_aggregate_second_life_bonus_is_none_when_any_site_unknown():
    # site_a: fully confirmed safe second-life data -> bonus 10.0.
    # site_b: incomplete second-life data, nothing confirmed unsafe -> bonus
    # None. The aggregate must not silently average over only site_a's
    # known bonus -- it must report None too, per _sum_total_score's
    # all-non-null-required contract.
    site_a_rows = [_row(h, site_id="site_a", battery_is_second_life=True) for h in range(6)]
    site_b_rows = [_row(h, site_id="site_b", battery_is_second_life=True) for h in range(6)]
    site_b_rows[4] = _row(4, site_id="site_b", battery_is_second_life=True, battery_health_status=None)

    result = evaluate_green_operations_index(site_a_rows + site_b_rows, MAX_GAP_HOURS)

    site_a = next(s for s in result.per_site if s.site_id == "site_a")
    site_b = next(s for s in result.per_site if s.site_id == "site_b")
    assert site_a.second_life_bonus == 10.0
    assert site_b.second_life_bonus is None
    assert result.dataset_aggregate.second_life_bonus is None
