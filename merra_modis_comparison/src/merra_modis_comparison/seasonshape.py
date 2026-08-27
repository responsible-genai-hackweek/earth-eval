"""Season-shape statistics: when a snowpack season turns, not how big it is.

Companion to :mod:`snowseason`, which answers "how much" from a domain-mean
series. This module answers "when", per *member* — one station-year or one
cell-year — because the comparison it serves puts a point observation beside a
gridded model and neither side may be reduced to the other's support first.

Every statistic here is invariant under a uniform rescaling of the series. That
is deliberate and it is the whole point: MERRA-2 and ERA5 disagree about
Colorado snowpack magnitude by a factor of three in midwinter that grows past
ten by April, and none of that disagreement may leak into a timing result.

Thresholds are therefore stated as a *fraction of that member's own peak*, never
as an absolute value. A SNOTEL site melts to exactly zero while a cell mean only
asymptotes toward it, so an absolute cutoff would compare unlike things and would
additionally reintroduce the magnitude difference this module exists to exclude.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "SeasonShape",
    "METRICS",
    "adjust_to_elevation",
    "elevation_gradient",
    "normalised_composite",
    "season_shape",
]

#: Metric field names in season order, which is also the order they are plotted.
METRICS = ("onset", "centroid", "peak", "melt_out")


@dataclass(frozen=True)
class SeasonShape:
    """Four turning points of one season, as days since 1 October.

    ``onset`` and ``melt_out`` may be NaN where the series begins above the
    threshold or never falls back below it. ``centroid`` and ``peak`` are always
    finite for a member that passed the floor.
    """

    onset: float
    centroid: float
    peak: float
    melt_out: float
    peak_value: float


def season_shape(
    days: np.ndarray,
    values: np.ndarray,
    *,
    fraction: float = 0.1,
    floor: float = 0.0,
) -> SeasonShape | None:
    """Locate one member's turning points, or ``None`` if it carries no season.

    ``days`` are days since 1 October of the water year; ``values`` any snow
    amount in any unit. Non-finite values are read as zero rather than
    propagated, so one missing day cannot destroy a whole member — the caller's
    coverage gate is what decides whether the member is admissible at all.

    ``floor`` rejects a member whose peak is too small to have a meaningful
    shape. It is the one absolute threshold here and it is a gate, not a metric:
    it decides membership, never a reported day.
    """
    days = np.asarray(days, dtype=float)
    values = np.nan_to_num(np.asarray(values, dtype=float), nan=0.0)
    if days.size != values.size:
        raise ValueError(f"{days.size} days but {values.size} values")
    if values.size == 0 or values.max() <= 0.0 or values.max() < floor:
        return None

    top = int(np.argmax(values))
    peak_day, peak_value = float(days[top]), float(values[top])
    cutoff = fraction * peak_value

    before = np.flatnonzero((days < peak_day) & (values > cutoff))
    after = np.flatnonzero((days > peak_day) & (values < cutoff))
    return SeasonShape(
        onset=float(days[before[0]]) if before.size else float("nan"),
        centroid=float((days * values).sum() / values.sum()),
        peak=peak_day,
        melt_out=float(days[after[0]]) if after.size else float("nan"),
        peak_value=peak_value,
    )


def normalised_composite(
    days: np.ndarray, values: np.ndarray, members: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Median season curve over members, each divided by its own peak.

    Returns ``(day, fraction)``. The composite is rescaled to its own maximum,
    which is not cosmetic. Members peak on different days, so the per-day median
    of member curves that each reach 1.0 tops out *below* 1.0 by an amount that
    tracks peak-date dispersion. Left alone, that puts timing dispersion on an
    axis labelled "fraction of peak", where a reader will read it as magnitude —
    the very claim dividing by the peak was meant to remove.
    """
    days = np.asarray(days, dtype=float)
    values = np.nan_to_num(np.asarray(values, dtype=float), nan=0.0)
    members = np.asarray(members)

    scaled = np.empty_like(values)
    for member in np.unique(members):
        sel = members == member
        top = values[sel].max()
        scaled[sel] = values[sel] / top if top > 0 else 0.0

    grid = np.unique(days)
    composite = np.array([np.median(scaled[days == day]) for day in grid])
    top = composite.max()
    return grid, composite / top if top > 0 else composite


def elevation_gradient(
    elevations: np.ndarray, metric: np.ndarray
) -> tuple[float, float, float]:
    """Least-squares gradient of a timing metric on elevation.

    Returns ``(slope_per_foot, intercept, pearson_r)``. The caller supplies one
    value per station, not per station-year, so that a long-record station does
    not outweigh a short one in the fit.
    """
    elevations = np.asarray(elevations, dtype=float)
    metric = np.asarray(metric, dtype=float)
    both = np.isfinite(elevations) & np.isfinite(metric)
    if both.sum() < 3:
        return float("nan"), float("nan"), float("nan")
    slope, intercept = np.polyfit(elevations[both], metric[both], 1)
    r = float(np.corrcoef(elevations[both], metric[both])[0, 1])
    return float(slope), float(intercept), r


def adjust_to_elevation(
    metric: np.ndarray, elevations: np.ndarray, slope_per_foot: float, target: float
) -> np.ndarray:
    """Remove each station's elevation offset from ``target``.

    This correction is load-bearing and it runs *against* ERA5: it moves the
    observation earlier — toward MERRA-2 — on every metric whose gradient is
    positive. Omitting it yields a stronger-looking ERA5 for the wrong reason.

    Valid only where ``target`` lies inside the elevation span the gradient was
    fitted over; the caller is responsible for checking that it is an
    interpolation rather than an extrapolation.
    """
    metric = np.asarray(metric, dtype=float)
    elevations = np.asarray(elevations, dtype=float)
    return metric - slope_per_foot * (elevations - target)
