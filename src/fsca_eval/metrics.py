"""Sufficient-statistic accumulation and error-metric formulas.

Error sign is fixed: error = M (MERRA-2) - R (MODSCAG). Sufficient statistics
are combined first; derived metrics (bias, MAE, NMB, NMAE) are computed from
combined sums, never averaged pre-derived across months/cells. See
scientific-contract.md "Error metrics".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class SufficientStats:
    """Additive sufficient statistics for one cell (or the domain) over any
    number of cell-days. Combine two instances with `+`.
    """

    sum_w: float = 0.0
    sum_w_error: float = 0.0
    sum_w_abs_error: float = 0.0
    sum_w_r: float = 0.0
    valid_pixels: int = 0
    expected_pixels: int = 0
    observed_pixels: int = 0
    n_cell_days: int = 0  # cell-days meeting the 80% support threshold
    n_days: int = 0  # calendar days with a paired reference for this cell
    n_calendar_days: int = 0  # calendar days considered, paired or not

    def __add__(self, other: "SufficientStats") -> "SufficientStats":
        return SufficientStats(
            sum_w=self.sum_w + other.sum_w,
            sum_w_error=self.sum_w_error + other.sum_w_error,
            sum_w_abs_error=self.sum_w_abs_error + other.sum_w_abs_error,
            sum_w_r=self.sum_w_r + other.sum_w_r,
            valid_pixels=self.valid_pixels + other.valid_pixels,
            expected_pixels=self.expected_pixels + other.expected_pixels,
            observed_pixels=self.observed_pixels + other.observed_pixels,
            n_cell_days=self.n_cell_days + other.n_cell_days,
            n_days=self.n_days + other.n_days,
            n_calendar_days=self.n_calendar_days + other.n_calendar_days,
        )


def cell_day_contribution(
    m_fraction: float,
    r_fraction: float,
    weight: int,
    expected_pixels: int,
    observed_pixels: int,
    support_fraction: float,
    support_threshold: float,
) -> SufficientStats:
    """Sufficient-stat contribution of one cell-day.

    Returns a zero-weight contribution (no paired observation) when the day
    is missing (r_fraction is NaN) or fails the support threshold -- the
    calendar day is still counted in n_calendar_days by the caller, but not
    in n_days/n_cell_days/sum_w*.
    """
    if np.isnan(m_fraction) or np.isnan(r_fraction) or weight <= 0:
        return SufficientStats(
            expected_pixels=expected_pixels,
            observed_pixels=observed_pixels,
            n_calendar_days=1,
        )

    cell_day_valid = support_fraction >= support_threshold
    error = m_fraction - r_fraction

    return SufficientStats(
        sum_w=weight if cell_day_valid else 0.0,
        sum_w_error=weight * error if cell_day_valid else 0.0,
        sum_w_abs_error=weight * abs(error) if cell_day_valid else 0.0,
        sum_w_r=weight * r_fraction if cell_day_valid else 0.0,
        valid_pixels=weight,
        expected_pixels=expected_pixels,
        observed_pixels=observed_pixels,
        n_cell_days=1 if cell_day_valid else 0,
        n_days=1 if cell_day_valid else 0,
        n_calendar_days=1,
    )


def bias_pp(stats: SufficientStats) -> float:
    """Bias in fSCA percentage points. NaN when there is no paired weight."""
    if stats.sum_w <= 0:
        return float("nan")
    return 100.0 * stats.sum_w_error / stats.sum_w


def mae_pp(stats: SufficientStats) -> float:
    if stats.sum_w <= 0:
        return float("nan")
    return 100.0 * stats.sum_w_abs_error / stats.sum_w


def nmb(stats: SufficientStats) -> float:
    """Normalized mean bias, percent relative to paired MODSCAG signal."""
    if stats.sum_w_r <= 0:
        return float("nan")
    return 100.0 * stats.sum_w_error / stats.sum_w_r


def nmae(stats: SufficientStats) -> float:
    if stats.sum_w_r <= 0:
        return float("nan")
    return 100.0 * stats.sum_w_abs_error / stats.sum_w_r


def composite_fsca(stats: SufficientStats) -> float:
    """Weighted mean reference (MODSCAG) fSCA, used for masking thresholds."""
    if stats.sum_w <= 0:
        return float("nan")
    return stats.sum_w_r / stats.sum_w


def support_fraction(stats: SufficientStats) -> float:
    if stats.expected_pixels <= 0:
        return 0.0
    return stats.valid_pixels / stats.expected_pixels


def direct_observation_fraction(stats: SufficientStats) -> float:
    if stats.valid_pixels <= 0:
        return 0.0
    return stats.observed_pixels / stats.valid_pixels
