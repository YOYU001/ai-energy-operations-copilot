from datetime import datetime, timedelta, timezone

import pytest

from app.services.cost_intervals import compute_valid_intervals

MAX_GAP_HOURS = 6.0


def _row(hour_offset, **overrides):
    base = {
        "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=hour_offset),
        "site_id": "site_a",
        "grid_import_kw": 10.0,
        "electricity_price": 5.0,
    }
    base.update(overrides)
    return base


def test_empty_rows_returns_no_intervals_and_no_notes():
    intervals, notes = compute_valid_intervals([], MAX_GAP_HOURS)
    assert intervals == []
    assert notes == []


def test_single_row_is_last_row_excluded_no_intervals():
    rows = [_row(0)]

    intervals, notes = compute_valid_intervals(rows, MAX_GAP_HOURS)

    assert intervals == []
    assert len(notes) == 1
    assert notes[0].type == "last_row_excluded"
    assert notes[0].count == 1


def test_normal_hourly_rows_produce_n_minus_1_intervals_last_excluded():
    rows = [_row(h) for h in range(5)]

    intervals, notes = compute_valid_intervals(rows, MAX_GAP_HOURS)

    assert len(intervals) == 4
    for interval in intervals:
        assert interval.duration_hours == 1.0
        assert interval.is_large_gap is False

    last_row_notes = [n for n in notes if n.type == "last_row_excluded"]
    assert len(last_row_notes) == 1
    assert last_row_notes[0].sample_timestamps[0] == rows[-1]["timestamp"]


def test_unsorted_input_is_sorted_before_pairing():
    rows = [_row(2), _row(0), _row(1)]

    intervals, _notes = compute_valid_intervals(rows, MAX_GAP_HOURS)

    assert len(intervals) == 2
    assert intervals[0].interval_start == rows[1]["timestamp"]  # hour 0
    assert intervals[1].interval_start == rows[2]["timestamp"]  # hour 1


def test_duplicate_timestamp_excluded_with_warning():
    rows = [_row(0), _row(0), _row(1)]  # two rows at hour 0

    intervals, notes = compute_valid_intervals(rows, MAX_GAP_HOURS)

    # the duplicate pair (duration 0) is excluded; only one real interval remains
    assert len(intervals) == 1
    assert intervals[0].duration_hours == 1.0

    duplicate_notes = [n for n in notes if n.type == "duplicate_timestamp"]
    assert len(duplicate_notes) == 1
    assert duplicate_notes[0].count == 1


def test_unparseable_timestamp_excluded_with_warning():
    rows = [_row(0), _row(1, timestamp="not-a-timestamp"), _row(2)]

    intervals, notes = compute_valid_intervals(rows, MAX_GAP_HOURS)

    unparseable_notes = [n for n in notes if n.type == "unparseable_timestamp"]
    assert len(unparseable_notes) == 1
    assert unparseable_notes[0].count == 1
    # the two valid rows (hour 0, hour 2) still pair into one interval
    assert len(intervals) == 1
    assert intervals[0].duration_hours == 2.0


def test_large_gap_kept_as_valid_interval_with_warning():
    rows = [_row(0), _row(20)]  # 20h gap, exceeds MAX_GAP_HOURS=6.0

    intervals, notes = compute_valid_intervals(rows, MAX_GAP_HOURS)

    assert len(intervals) == 1
    assert intervals[0].duration_hours == 20.0
    assert intervals[0].is_large_gap is True

    gap_notes = [n for n in notes if n.type == "large_gap"]
    assert len(gap_notes) == 1
    assert gap_notes[0].count == 1


def test_multi_site_rows_raise_value_error():
    rows = [_row(0, site_id="site_a"), _row(1, site_id="site_b")]

    with pytest.raises(ValueError):
        compute_valid_intervals(rows, MAX_GAP_HOURS)


def test_start_row_carries_original_columns_for_downstream_use():
    rows = [_row(0, grid_import_kw=42.0), _row(1)]

    intervals, _notes = compute_valid_intervals(rows, MAX_GAP_HOURS)

    assert intervals[0].start_row["grid_import_kw"] == 42.0
    assert "_parsed_timestamp" not in intervals[0].start_row
