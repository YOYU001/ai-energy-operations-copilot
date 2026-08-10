import pandas as pd

from app.services.price_classification import (
    classify_price,
    classify_price_series,
    compute_price_threshold,
)


def test_insufficient_data_below_minimum_samples():
    prices = pd.Series([1.0, 2.0, 3.0, 4.0])

    threshold = compute_price_threshold(prices)

    assert threshold.mode == "insufficient_data"
    assert threshold.low_threshold is None
    assert threshold.high_threshold is None
    assert classify_price(1.0, threshold) == "neutral"
    assert classify_price(4.0, threshold) == "neutral"


def test_no_distinguishable_peak_when_constant():
    prices = pd.Series([5.0] * 10)

    threshold = compute_price_threshold(prices)

    assert threshold.mode == "no_distinguishable_peak"
    assert threshold.low_threshold is None
    assert threshold.high_threshold is None
    assert classify_price(5.0, threshold) == "neutral"


def test_discrete_two_tier_tou_min_is_low_max_is_high_no_neutral():
    prices = pd.Series([3.0, 3.0, 3.0, 7.0, 7.0, 7.0])

    threshold = compute_price_threshold(prices)

    assert threshold.mode == "discrete_tou_max"
    assert threshold.low_threshold == 3.0
    assert threshold.high_threshold == 7.0
    assert classify_price(3.0, threshold) == "low"
    assert classify_price(7.0, threshold) == "high"


def test_discrete_three_tier_tou_middle_is_neutral():
    prices = pd.Series([2.0, 2.0, 5.0, 5.0, 9.0, 9.0])

    threshold = compute_price_threshold(prices)

    assert threshold.mode == "discrete_tou_max"
    assert threshold.low_threshold == 2.0
    assert threshold.high_threshold == 9.0
    assert classify_price(2.0, threshold) == "low"
    assert classify_price(5.0, threshold) == "neutral"
    assert classify_price(9.0, threshold) == "high"


def test_percentile_mode_normal_distribution():
    prices = pd.Series([float(x) for x in range(1, 21)])  # 1..20, 20 distinct values

    threshold = compute_price_threshold(prices)

    assert threshold.mode == "percentile"
    assert threshold.low_threshold is not None
    assert threshold.high_threshold is not None
    assert threshold.low_threshold < threshold.high_threshold

    assert classify_price(threshold.low_threshold - 0.01, threshold) == "low"
    assert classify_price(threshold.high_threshold + 0.01, threshold) == "high"
    assert classify_price(threshold.low_threshold, threshold) == "neutral"
    assert classify_price(threshold.high_threshold, threshold) == "neutral"


def test_percentile_mode_collapsed_thresholds_are_all_neutral():
    # Highly skewed: 16/20 samples at 1.0 plus 4 distinct outliers -- enough
    # distinct values (5) to land in percentile mode, but skewed enough that
    # both the 25th and 75th percentile fall inside the 1.0 block, collapsing
    # low_threshold == high_threshold == 1.0.
    prices = pd.Series([1.0] * 16 + [2.0, 3.0, 4.0, 5.0])

    threshold = compute_price_threshold(prices)

    assert threshold.mode == "percentile"
    # both quantiles land on 1.0 here -> low_threshold >= high_threshold
    assert threshold.low_threshold >= threshold.high_threshold
    assert classify_price(1.0, threshold) == "neutral"
    assert classify_price(0.5, threshold) == "neutral"
    assert classify_price(100.0, threshold) == "neutral"


def test_classify_price_none_value_is_neutral():
    prices = pd.Series([float(x) for x in range(1, 21)])
    threshold = compute_price_threshold(prices)

    assert classify_price(None, threshold) == "neutral"


def test_classify_price_series_matches_scalar_classify_price():
    prices = pd.Series([float(x) for x in range(1, 21)] + [None])
    threshold = compute_price_threshold(prices.dropna())

    series_result = classify_price_series(prices, threshold)
    scalar_result = [classify_price(v if pd.notna(v) else None, threshold) for v in prices]

    assert list(series_result) == scalar_result
