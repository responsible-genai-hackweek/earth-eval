"""Sufficient statistics and the error metrics derived from them.

Everything downstream - monthly tables, seasonal groups, climatologies, maps -
is a function of these additive sums. Storing sums rather than metrics is what
makes a checkpoint recombinable: derived metrics cannot be re-averaged into a
correct pooled value, sums can.

The error is always ``model - reference``, so a positive bias means the model
is too snowy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace
from typing import Iterable

import numpy as np

__all__ = [
    "SufficientStats",
    "accumulate_cell_days",
    "bias_pp",
    "combine_over_cells",
    "combine_over_time",
    "direct_observation_fraction",
    "mae_pp",
    "nmae_pct",
    "nmb_pct",
    "support_fraction",
]

#: Fields that add when statistics are pooled across space *or* time.
_SPATIALLY_ADDITIVE = (
    "sum_w",
    "sum_w_error",
    "sum_w_abs_error",
    "sum_w_reference",
    "valid_pixels",
    "expected_pixels",
    "observed_pixels",
    "n_cell_days",
)

#: Fields that add over time but *not* over space - two cells paired on the same
#: day are one day, not two.
_TIME_ONLY_ADDITIVE = ("n_days", "n_calendar_days")


@dataclass(frozen=True)
class SufficientStats:
    """Additive statistics for one spatial unit over one time span."""

    sum_w: float = 0.0
    sum_w_error: float = 0.0
    sum_w_abs_error: float = 0.0
    sum_w_reference: float = 0.0
    valid_pixels: int = 0
    expected_pixels: int = 0
    observed_pixels: int = 0
    n_cell_days: int = 0
    n_days: int = 0
    n_calendar_days: int = 0

    @classmethod
    def zero(cls) -> "SufficientStats":
        return cls()

    def __add__(self, other: "SufficientStats") -> "SufficientStats":
        """Add over time. Use :func:`combine_over_cells` to pool across space."""
        if not isinstance(other, SufficientStats):
            return NotImplemented
        return SufficientStats(
            **{f.name: getattr(self, f.name) + getattr(other, f.name) for f in fields(self)}
        )

    __radd__ = __add__


def accumulate_cell_days(
    model: np.ndarray,
    reference: np.ndarray,
    weights: np.ndarray,
    *,
    expected_pixels: int = 0,
    observed_pixels: int = 0,
    n_days: int = 0,
    n_calendar_days: int = 0,
) -> SufficientStats:
    """Reduce paired cell-days into sufficient statistics.

    ``model`` and ``reference`` are fSCA fractions in 0..1; ``weights`` are the
    valid fine-pixel counts backing each pair, which represent paired fine-pixel
    area. Pairs where either side is not finite are excluded - they are missing
    observations, not zero error.
    """
    model = np.asarray(model, dtype=np.float64)
    reference = np.asarray(reference, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    if not (model.shape == reference.shape == weights.shape):
        raise ValueError(
            f"shape mismatch: model {model.shape}, reference {reference.shape}, "
            f"weights {weights.shape}"
        )

    usable = np.isfinite(model) & np.isfinite(reference) & np.isfinite(weights) & (weights > 0)
    m = model[usable]
    r = reference[usable]
    w = weights[usable]
    error = m - r

    return SufficientStats(
        sum_w=float(w.sum()),
        sum_w_error=float((w * error).sum()),
        sum_w_abs_error=float((w * np.abs(error)).sum()),
        sum_w_reference=float((w * r).sum()),
        valid_pixels=int(w.sum()),
        expected_pixels=int(expected_pixels),
        observed_pixels=int(observed_pixels),
        n_cell_days=int(usable.sum()),
        n_days=int(n_days),
        n_calendar_days=int(n_calendar_days),
    )


def combine_over_time(parts: Iterable[SufficientStats]) -> SufficientStats:
    """Pool statistics for one spatial unit across successive time spans."""
    total = SufficientStats.zero()
    for part in parts:
        total = total + part
    return total


def combine_over_cells(
    parts: Iterable[SufficientStats], *, n_days: int, n_calendar_days: int
) -> SufficientStats:
    """Pool statistics across spatial units within one time span.

    Day counts are supplied by the caller rather than summed: the number of
    calendar days with at least one paired cell is a property of the domain, not
    the sum of each cell's paired-day count.
    """
    total = SufficientStats.zero()
    for part in parts:
        total = SufficientStats(
            **{name: getattr(total, name) + getattr(part, name) for name in _SPATIALLY_ADDITIVE},
        )
    return replace(total, n_days=int(n_days), n_calendar_days=int(n_calendar_days))


def bias_pp(s: SufficientStats) -> float:
    """Weighted mean signed error, in fSCA percentage points."""
    return _ratio(100.0 * s.sum_w_error, s.sum_w)


def mae_pp(s: SufficientStats) -> float:
    """Weighted mean absolute error, in fSCA percentage points."""
    return _ratio(100.0 * s.sum_w_abs_error, s.sum_w)


def nmb_pct(s: SufficientStats) -> float:
    """Normalized mean bias, percent of the paired reference snow signal."""
    return _ratio(100.0 * s.sum_w_error, s.sum_w_reference)


def nmae_pct(s: SufficientStats) -> float:
    """Normalized mean absolute error, percent of the reference snow signal."""
    return _ratio(100.0 * s.sum_w_abs_error, s.sum_w_reference)


def support_fraction(s: SufficientStats) -> float:
    """Valid fine pixels as a fraction of the expected complete-cell support."""
    return _ratio(float(s.valid_pixels), float(s.expected_pixels))


def direct_observation_fraction(s: SufficientStats) -> float:
    """Directly observed fine pixels as a fraction of the valid ones."""
    return _ratio(float(s.observed_pixels), float(s.valid_pixels))


def _ratio(numerator: float, denominator: float) -> float:
    """Divide, returning NaN for an undefined ratio instead of raising.

    A group with no paired data has a *null* metric. Returning 0.0 would be a
    silent claim of zero error.
    """
    if denominator == 0 or not math.isfinite(denominator) or not math.isfinite(numerator):
        return math.nan
    return numerator / denominator
