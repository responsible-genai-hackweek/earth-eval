"""Water-year snowpack statistics.

Pure functions over a daily domain-mean series. These are the definitions the
headline claim rests on, so each is stated once and tested rather than being
recomputed inline wherever a figure needs it.

One property is worth stating explicitly: these statistics are sensitive to
sampling. A weekly series can miss a narrow peak entirely and invert which year
ranks lowest, which is why the daily series is the input of record.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

__all__ = [
    "DailySeries",
    "Peak",
    "april_first",
    "mean_over",
    "melt_out_date",
    "peak",
    "rank_ascending",
    "spearman_rho",
    "standardized_anomaly",
    "water_year_slice",
]


@dataclass(frozen=True)
class DailySeries:
    """A daily domain-mean series. ``values`` may contain NaN for missing days."""

    dates: tuple[date, ...]
    values: np.ndarray

    def __post_init__(self) -> None:
        if len(self.dates) != np.asarray(self.values).size:
            raise ValueError(
                f"{len(self.dates)} dates but {np.asarray(self.values).size} values"
            )

    def __len__(self) -> int:
        return len(self.dates)


@dataclass(frozen=True)
class Peak:
    """The largest value in a series and the day it occurred."""

    value: float
    day: date | None


def water_year_slice(series: DailySeries, wy: int) -> DailySeries:
    """Return the portion of ``series`` inside water year ``wy``."""
    start, stop = date(wy - 1, 10, 1), date(wy, 9, 30)
    keep = [i for i, d in enumerate(series.dates) if start <= d <= stop]
    return DailySeries(
        dates=tuple(series.dates[i] for i in keep),
        values=np.asarray(series.values, dtype=float)[keep],
    )


def peak(series: DailySeries) -> Peak:
    """Return the maximum and its date, resolving ties to the earliest day."""
    values = np.asarray(series.values, dtype=float)
    if values.size == 0 or not np.any(np.isfinite(values)):
        return Peak(value=float("nan"), day=None)
    index = int(np.nanargmax(values))
    return Peak(value=float(values[index]), day=series.dates[index])


def april_first(series: DailySeries, wy: int) -> float:
    """Return the 1 April value, the standard operational snowpack benchmark."""
    return value_on(series, date(wy, 4, 1))


def value_on(series: DailySeries, day: date) -> float:
    """Return the value for one day, or NaN if the series does not cover it."""
    try:
        index = series.dates.index(day)
    except ValueError:
        return float("nan")
    return float(np.asarray(series.values, dtype=float)[index])


def melt_out_date(series: DailySeries, threshold: float) -> date | None:
    """First day *after the peak* on which the pack falls below ``threshold``.

    Anchoring to the peak matters: early-season days before the pack builds are
    also below the threshold, and would otherwise be reported as melt-out.
    """
    top = peak(series)
    if top.day is None:
        return None
    values = np.asarray(series.values, dtype=float)
    start = series.dates.index(top.day)
    for i in range(start, len(series.dates)):
        if np.isfinite(values[i]) and values[i] < threshold:
            return series.dates[i]
    return None


def mean_over(series: DailySeries, start: date, stop: date) -> float:
    """Mean of the finite values between ``start`` and ``stop``, inclusive."""
    values = np.asarray(series.values, dtype=float)
    picked = [
        values[i] for i, d in enumerate(series.dates) if start <= d <= stop
    ]
    finite = [v for v in picked if np.isfinite(v)]
    return float(np.mean(finite)) if finite else float("nan")


def rank_ascending(values: np.ndarray) -> np.ndarray:
    """Rank values with 1 as the lowest. Missing values get NaN, not a rank."""
    values = np.asarray(values, dtype=float)
    ranks = np.full(values.shape, np.nan)
    finite = np.flatnonzero(np.isfinite(values))
    if finite.size:
        order = finite[np.argsort(values[finite], kind="stable")]
        ranks[order] = np.arange(1, order.size + 1)
    return ranks


def standardized_anomaly(values: np.ndarray) -> np.ndarray:
    """Departure from the mean in units of the standard deviation.

    A field with no finite values - a metric that needs a date the record does
    not reach, say - has no anomaly, and says so rather than warning.
    """
    values = np.asarray(values, dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return np.full(values.shape, np.nan)
    spread = float(finite.std())
    if spread == 0.0:
        return np.full(values.shape, np.nan)
    return (values - float(finite.mean())) / spread


def spearman_rho(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Spearman rank correlation over pairs where both values are finite.

    Rank correlation is the right agreement measure for two models that differ
    substantially in magnitude but may still order the years identically.
    """
    from scipy import stats

    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    both = np.isfinite(a) & np.isfinite(b)
    if both.sum() < 3:
        return float("nan"), float("nan")
    result = stats.spearmanr(a[both], b[both])
    return float(result.statistic), float(result.pvalue)
