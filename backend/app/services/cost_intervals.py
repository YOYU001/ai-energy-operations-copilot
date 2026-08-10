from datetime import datetime
from typing import NamedTuple

import pandas as pd

from app.schemas import AnalysisNote

# Bounded sample size so a dataset with thousands of duplicate/invalid
# timestamps doesn't inflate the response with thousands of entries -- only
# the count is unbounded, the sample list stays small.
MAX_WARNING_SAMPLE_SIZE = 5


class ValidInterval(NamedTuple):
    """One [interval_start, interval_end) pair with a positive duration,
    ready for cost_estimation.py / green_operations_index.py to read
    whatever columns they each need from start_row."""

    start_row: dict
    interval_start: datetime
    interval_end: datetime
    duration_hours: float
    is_large_gap: bool


def compute_valid_intervals(
    rows: list[dict],
    max_expected_interval_hours: float,
) -> tuple[list[ValidInterval], list[AnalysisNote]]:
    """Pure function, single site only -- the caller MUST already have
    grouped rows by site_id before calling this (docs/step13_rules_and_api_design.md
    4.3): pairing timestamps across two different sites would compute a
    physically meaningless duration/energy value. As a defensive check
    against that contract being violated, this raises if more than one
    distinct site_id is present.

    Excludes, each with a structured AnalysisNote (not a raw string per
    occurrence) rather than silently dropping them:
      - rows with an unparseable/missing timestamp ("unparseable_timestamp")
      - duplicate timestamps, i.e. duration == 0 ("duplicate_timestamp")
      - non-positive intervals, duration < 0 -- should not occur after the
        internal sort below, kept as a defensive check ("non_positive_interval")
      - the last row of the site (no next timestamp to pair with) ("last_row_excluded")

    duration_hours > max_expected_interval_hours is NOT excluded -- it is
    kept as a valid interval and flagged via is_large_gap / a "large_gap"
    AnalysisNote (docs/step13_rules_and_api_design.md 4.2 item 5): a big gap
    is a data-quality signal, not proof the number is wrong.
    """
    if not rows:
        return [], []

    df = pd.DataFrame(rows)

    if "site_id" in df.columns and df["site_id"].nunique(dropna=False) > 1:
        raise ValueError(
            "compute_valid_intervals received rows spanning multiple site_id "
            "values; group by site_id before calling this function"
        )

    if "timestamp" not in df.columns:
        return [], [AnalysisNote(type="unparseable_timestamp", count=len(rows))]

    parsed = pd.to_datetime(df["timestamp"], errors="coerce")
    valid_mask = parsed.notna()
    unparseable_count = int((~valid_mask).sum())

    df = df.loc[valid_mask].copy()
    df["_parsed_timestamp"] = parsed.loc[valid_mask]
    df = df.sort_values("_parsed_timestamp", kind="stable").reset_index(drop=True)

    notes: list[AnalysisNote] = []
    if unparseable_count:
        notes.append(AnalysisNote(type="unparseable_timestamp", count=unparseable_count))

    if len(df) == 0:
        return [], notes

    if len(df) == 1:
        notes.append(
            AnalysisNote(
                type="last_row_excluded",
                count=1,
                sample_timestamps=[df["_parsed_timestamp"].iloc[0].to_pydatetime()],
            )
        )
        return [], notes

    next_timestamp = df["_parsed_timestamp"].shift(-1)
    duration_hours = (next_timestamp - df["_parsed_timestamp"]).dt.total_seconds() / 3600.0

    intervals: list[ValidInterval] = []
    duplicate_timestamps: list[datetime] = []
    non_positive_timestamps: list[datetime] = []
    large_gap_timestamps: list[datetime] = []

    for idx in range(len(df) - 1):
        duration = float(duration_hours.iloc[idx])
        start_ts = df["_parsed_timestamp"].iloc[idx].to_pydatetime()

        if duration == 0:
            duplicate_timestamps.append(start_ts)
            continue
        if duration < 0:
            non_positive_timestamps.append(start_ts)
            continue

        is_large_gap = duration > max_expected_interval_hours
        if is_large_gap:
            large_gap_timestamps.append(start_ts)

        end_ts = df["_parsed_timestamp"].iloc[idx + 1].to_pydatetime()
        start_row = df.iloc[idx].drop(labels=["_parsed_timestamp"]).to_dict()
        intervals.append(
            ValidInterval(
                start_row=start_row,
                interval_start=start_ts,
                interval_end=end_ts,
                duration_hours=duration,
                is_large_gap=is_large_gap,
            )
        )

    notes.append(
        AnalysisNote(
            type="last_row_excluded",
            count=1,
            sample_timestamps=[df["_parsed_timestamp"].iloc[-1].to_pydatetime()],
        )
    )
    if duplicate_timestamps:
        notes.append(
            AnalysisNote(
                type="duplicate_timestamp",
                count=len(duplicate_timestamps),
                sample_timestamps=duplicate_timestamps[:MAX_WARNING_SAMPLE_SIZE],
            )
        )
    if non_positive_timestamps:
        notes.append(
            AnalysisNote(
                type="non_positive_interval",
                count=len(non_positive_timestamps),
                sample_timestamps=non_positive_timestamps[:MAX_WARNING_SAMPLE_SIZE],
            )
        )
    if large_gap_timestamps:
        notes.append(
            AnalysisNote(
                type="large_gap",
                count=len(large_gap_timestamps),
                sample_timestamps=large_gap_timestamps[:MAX_WARNING_SAMPLE_SIZE],
            )
        )

    return intervals, notes
