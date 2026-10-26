"""Robust price statistics.

Marketplace prices have fat tails on both sides: a $4 "starting bid" that
will not end at $4, a $250 listing from a seller fishing for the unwary, a
mislabelled chase car. Means are useless here; medians and percentiles after
outlier rejection are what a buyer can act on.

Outliers are rejected with the modified z-score (Iglewicz & Hoaglin): a value
is an outlier when |0.6745 * (x - median) / MAD| > 3.5. When more than half the
prices are identical the MAD is zero, so the Tukey IQR fences take over. With
fewer than MIN_FOR_REJECTION points nothing is rejected: there is not enough
data to call anything unusual.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

MIN_FOR_REJECTION = 5
MODIFIED_Z_LIMIT = 3.5
IQR_K = 1.5


def percentile(values: list[float], p: float) -> float:
    """Linear interpolation between closest ranks (numpy's default method)."""
    if not values:
        raise ValueError("percentile of empty list")
    if not 0 <= p <= 100:
        raise ValueError("p must be in [0, 100]")
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    rank = (len(xs) - 1) * p / 100
    lo, hi = math.floor(rank), math.ceil(rank)
    return xs[lo] + (xs[hi] - xs[lo]) * (rank - lo)


def median(values: list[float]) -> float:
    return percentile(values, 50)


def mad(values: list[float]) -> float:
    m = median(values)
    return median([abs(x - m) for x in values])


def split_outliers(values: list[float]) -> tuple[list[float], list[float]]:
    """Return (kept, rejected), each in input order."""
    if len(values) < MIN_FOR_REJECTION:
        return list(values), []
    m, d = median(values), mad(values)
    if d > 0:
        is_out = [abs(0.6745 * (x - m) / d) > MODIFIED_Z_LIMIT for x in values]
    else:
        q1, q3 = percentile(values, 25), percentile(values, 75)
        spread = q3 - q1
        if spread == 0:
            # Most prices identical: anything off by more than half is an outlier.
            is_out = [abs(x - m) > 0.5 * m for x in values]
        else:
            lo, hi = q1 - IQR_K * spread, q3 + IQR_K * spread
            is_out = [x < lo or x > hi for x in values]
    kept = [x for x, o in zip(values, is_out) if not o]
    rejected = [x for x, o in zip(values, is_out) if o]
    return kept, rejected


@dataclass
class Summary:
    n: int               # points kept
    n_rejected: int      # outliers dropped
    median: float
    p10: float
    p25: float
    p75: float
    p90: float
    low: float
    high: float

    def as_dict(self) -> dict:
        return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def summarise(values: list[float]) -> Summary | None:
    if not values:
        return None
    kept, rejected = split_outliers(values)
    return Summary(
        n=len(kept), n_rejected=len(rejected),
        median=median(kept),
        p10=percentile(kept, 10), p25=percentile(kept, 25),
        p75=percentile(kept, 75), p90=percentile(kept, 90),
        low=min(kept), high=max(kept),
    )
