import pandas as pd

from app.schemas import PriceClassificationThreshold

# Mirrors rule_engine.py's existing thresholds -- same dataset-relative
# philosophy, extended with a symmetric low-side percentile
# (docs/step13_rules_and_api_design.md 2.1).
MINIMUM_PRICE_SAMPLES = 5
DISCRETE_TOU_MAX_DISTINCT_VALUES = 3
LOW_PRICE_PERCENTILE = 0.25
HIGH_PRICE_PERCENTILE = 0.75


def compute_price_threshold(prices: pd.Series) -> PriceClassificationThreshold:
    """Decide the dataset-relative low/neutral/high price classification for
    one dataset. Never uses an absolute price threshold -- electricity_price
    is a simplified TOU price whose scale is arbitrary per dataset/site.
    """
    non_null = prices.dropna()
    sample_count = int(len(non_null))
    distinct_count = int(non_null.nunique())

    if sample_count < MINIMUM_PRICE_SAMPLES:
        return PriceClassificationThreshold(
            mode="insufficient_data",
            non_null_sample_count=sample_count,
            distinct_price_count=distinct_count,
            reason=(
                f"non-null electricity_price sample count ({sample_count}) is "
                f"below the minimum required ({MINIMUM_PRICE_SAMPLES})"
            ),
        )

    if distinct_count < 2:
        return PriceClassificationThreshold(
            mode="no_distinguishable_peak",
            non_null_sample_count=sample_count,
            distinct_price_count=distinct_count,
            reason="electricity_price does not vary in this dataset; no low/high price period can be identified",
        )

    if distinct_count <= DISCRETE_TOU_MAX_DISTINCT_VALUES:
        # 2 prices: min=low, max=high, no neutral value ever occurs.
        # 3 prices: min=low, middle=neutral, max=high.
        sorted_values = sorted(non_null.unique())
        return PriceClassificationThreshold(
            mode="discrete_tou_max",
            low_threshold=float(sorted_values[0]),
            high_threshold=float(sorted_values[-1]),
            non_null_sample_count=sample_count,
            distinct_price_count=distinct_count,
        )

    return PriceClassificationThreshold(
        mode="percentile",
        low_threshold=float(non_null.quantile(LOW_PRICE_PERCENTILE, interpolation="linear")),
        high_threshold=float(non_null.quantile(HIGH_PRICE_PERCENTILE, interpolation="linear")),
        non_null_sample_count=sample_count,
        distinct_price_count=distinct_count,
    )


def classify_price(value, threshold: PriceClassificationThreshold) -> str:
    """Scalar classification for one price value. Returns "low" | "neutral" | "high"."""
    if value is None:
        return "neutral"

    if threshold.mode in ("insufficient_data", "no_distinguishable_peak"):
        return "neutral"

    if threshold.mode == "discrete_tou_max":
        # Exact-value mapping, not a strict >/< comparison -- min/max are
        # themselves valid observed prices, so "< low_threshold" would
        # never match the minimum value itself.
        if threshold.low_threshold is not None and value == threshold.low_threshold:
            return "low"
        if threshold.high_threshold is not None and value == threshold.high_threshold:
            return "high"
        return "neutral"

    # percentile mode
    if threshold.low_threshold is None or threshold.high_threshold is None:
        return "neutral"
    if threshold.low_threshold >= threshold.high_threshold:
        # Degenerate/overlapping percentiles (highly skewed distribution) --
        # do not prioritize either side, per docs/step13_rules_and_api_design.md 2.1.
        return "neutral"
    if value < threshold.low_threshold:
        return "low"
    if value > threshold.high_threshold:
        return "high"
    return "neutral"


def classify_price_series(prices: pd.Series, threshold: PriceClassificationThreshold) -> pd.Series:
    """Vectorized equivalent of classify_price for a whole column -- avoids a
    Python-level per-row loop for callers evaluating a signal across an
    entire dataset (code-style.md: prefer pandas vectorization)."""
    result = pd.Series("neutral", index=prices.index, dtype=object)

    if threshold.mode in ("insufficient_data", "no_distinguishable_peak"):
        return result

    notna = prices.notna()

    if threshold.mode == "discrete_tou_max":
        if threshold.low_threshold is not None:
            result = result.mask(notna & (prices == threshold.low_threshold), "low")
        if threshold.high_threshold is not None:
            result = result.mask(notna & (prices == threshold.high_threshold), "high")
        return result

    # percentile mode
    if (
        threshold.low_threshold is None
        or threshold.high_threshold is None
        or threshold.low_threshold >= threshold.high_threshold
    ):
        return result

    result = result.mask(notna & (prices < threshold.low_threshold), "low")
    result = result.mask(notna & (prices > threshold.high_threshold), "high")
    return result
