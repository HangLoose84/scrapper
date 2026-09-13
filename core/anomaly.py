from collections.abc import Sequence
from statistics import median


def drop_ratio(current: float, history: Sequence[float]) -> float:
    """How far `current` sits below the median of `history`, as a fraction.

    0.62 vs a median of 1.00 -> 0.38. Returns 0.0 when there is no history,
    no usable baseline, or the price went up.
    Median, not mean: one flash sale in the history should not move the baseline.
    """
    if not history:
        return 0.0
    baseline = median(history)
    if baseline <= 0:
        return 0.0
    return max(0.0, (baseline - current) / baseline)
