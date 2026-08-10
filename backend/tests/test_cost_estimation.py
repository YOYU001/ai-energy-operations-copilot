from datetime import datetime, timedelta

from app.services.cost_estimation import evaluate_cost_estimation

BASE_TS = datetime(2026, 1, 1)
MAX_GAP_HOURS = 6.0


def _row(hour, site_id="site_a", **overrides):
    base = {
        "timestamp": BASE_TS + timedelta(hours=hour),
        "site_id": site_id,
        "grid_import_kw": 10.0,
        "electricity_price": 5.0,
        "battery_power_kw": 0.0,
        "contract_capacity_kw": 100.0,
    }
    base.update(overrides)
    return base


def test_single_site_energy_cost_uses_actual_duration():
    rows = [_row(0), _row(1)]  # 1-hour interval

    result = evaluate_cost_estimation(rows, MAX_GAP_HOURS)

    assert result.site_count == 1
    site = result.per_site[0]
    assert site.interval_count == 1
    interval = site.intervals[0]
    assert interval.duration_hours == 1.0
    assert interval.energy_kwh == 10.0  # 10 kW * 1h
    assert interval.estimated_cost == 50.0  # 10 kWh * 5.0
    assert site.total_energy_cost == 50.0


def test_discharge_produces_positive_arbitrage_saving():
    rows = [_row(0, battery_power_kw=4.0), _row(1)]

    result = evaluate_cost_estimation(rows, MAX_GAP_HOURS)

    interval = result.per_site[0].intervals[0]
    assert interval.battery_arbitrage == 20.0  # 4 kW * 1h * 5.0
    assert result.per_site[0].total_arbitrage_saving == 20.0


def test_charge_produces_negative_arbitrage():
    rows = [_row(0, battery_power_kw=-4.0), _row(1)]

    result = evaluate_cost_estimation(rows, MAX_GAP_HOURS)

    interval = result.per_site[0].intervals[0]
    assert interval.battery_arbitrage == -20.0
    assert result.per_site[0].total_arbitrage_saving == -20.0


def test_multi_site_rows_are_not_paired_across_sites():
    rows = [
        _row(0, site_id="site_a"),
        _row(1, site_id="site_b"),  # interleaved by timestamp, different site
        _row(2, site_id="site_a"),
        _row(3, site_id="site_b"),
    ]

    result = evaluate_cost_estimation(rows, MAX_GAP_HOURS)

    assert result.site_count == 2
    site_ids = {site.site_id for site in result.per_site}
    assert site_ids == {"site_a", "site_b"}
    for site in result.per_site:
        assert site.row_count == 2
        # each site's own 2 rows are 2h apart (hour 0 & 2, or 1 & 3)
        assert site.interval_count == 1
        assert site.intervals[0].duration_hours == 2.0


def test_dataset_aggregate_sums_across_sites():
    rows = [
        _row(0, site_id="site_a"),
        _row(1, site_id="site_a"),
        _row(0, site_id="site_b"),
        _row(1, site_id="site_b"),
    ]

    result = evaluate_cost_estimation(rows, MAX_GAP_HOURS)

    aggregate = result.dataset_aggregate
    assert aggregate.site_id == "__all__"
    assert aggregate.row_count == 4
    assert aggregate.interval_count == 2
    assert aggregate.total_energy_cost == sum(s.total_energy_cost for s in result.per_site)
    assert aggregate.total_arbitrage_saving == sum(s.total_arbitrage_saving for s in result.per_site)


def test_over_contract_risk_penalty_flag_on_flagged_interval():
    rows = [
        _row(0, grid_import_kw=95.0, contract_capacity_kw=100.0),  # >= 0.90 ratio -> flagged
        _row(1, grid_import_kw=10.0, contract_capacity_kw=100.0),
        _row(2, grid_import_kw=10.0, contract_capacity_kw=100.0),
    ]

    result = evaluate_cost_estimation(rows, MAX_GAP_HOURS)

    site = result.per_site[0]
    assert len(site.over_contract_penalty_flags) == 1
    assert site.over_contract_penalty_flags[0].signal == "over_contract_risk"
    assert site.over_contract_penalty_flags[0].interval_start == rows[0]["timestamp"]


def test_last_row_excluded_reported_as_limitation_not_warning():
    rows = [_row(0), _row(1), _row(2)]

    result = evaluate_cost_estimation(rows, MAX_GAP_HOURS)

    site = result.per_site[0]
    assert any(note.type == "last_row_excluded" for note in site.limitations)
    assert all(note.type != "last_row_excluded" for note in site.warnings)


def test_aggregate_notes_are_stamped_with_originating_site_id():
    rows = [
        _row(0, site_id="site_a"),
        _row(0, site_id="site_a"),  # duplicate timestamp -> warning
        _row(1, site_id="site_a"),
        _row(0, site_id="site_b"),
        _row(1, site_id="site_b"),
    ]

    result = evaluate_cost_estimation(rows, MAX_GAP_HOURS)

    aggregate_warning_site_ids = {n.site_id for n in result.dataset_aggregate.warnings if n.type == "duplicate_timestamp"}
    assert aggregate_warning_site_ids == {"site_a"}
