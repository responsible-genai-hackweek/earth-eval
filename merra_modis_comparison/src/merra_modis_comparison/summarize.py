"""Turn the daily checkpoints into water-year statistics and a ranking.

Both models are expressed in the same units before anything is compared:
snow water equivalent in mm of water equivalent, and grid-cell mean geometric
depth in metres. The conversions are the ones established in :mod:`snowvars`,
including the rule that MERRA-2's grid-mean depth is ``FRSNO * SNODP``.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from .snowseason import (
    DailySeries,
    april_first,
    mean_over,
    melt_out_date,
    peak,
    rank_ascending,
    spearman_rho,
    standardized_anomaly,
)
from .snowvars import geometric_depth_m, grid_mean_depth_m

__all__ = [
    "WaterYearStats",
    "load_depth_series",
    "load_swe_series",
    "model_agreement",
    "summarize_model",
]

#: Domain-mean SWE below which the pack is treated as melted out, mm w.e.
MELT_OUT_THRESHOLD_MM = 5.0


@dataclass(frozen=True)
class WaterYearStats:
    """Per-water-year snowpack statistics for one model."""

    water_year: int
    peak_swe_mm: float
    peak_day: date | None
    april_first_swe_mm: float
    april_first_depth_m: float
    season_mean_swe_mm: float
    melt_out: date | None
    n_days: int


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def load_swe_series(checkpoints: Path, model: str, water_years) -> DailySeries:
    """Load domain-mean SWE in mm of water equivalent.

    MERRA-2 stores SNOMAS in kg m-2, which is numerically mm of water
    equivalent, so no conversion is needed on that side.
    """
    days: list[date] = []
    values: list[float] = []
    for wy in water_years:
        path = checkpoints / f"{model}_WY{wy}.csv"
        if not path.exists():
            continue
        for row in _read(path):
            days.append(date.fromisoformat(row["date"]))
            values.append(
                float(row["swe_mm_we"]) if model == "era5" else float(row["snomas_kg_m2"])
            )
    order = np.argsort(days)
    return DailySeries(
        dates=tuple(np.array(days, dtype=object)[order]),
        values=np.asarray(values, dtype=float)[order],
    )


def load_depth_series(checkpoints: Path, model: str, water_years) -> DailySeries:
    """Load grid-cell mean geometric snow depth, in metres."""
    days: list[date] = []
    values: list[float] = []
    for wy in water_years:
        path = checkpoints / f"{model}_WY{wy}.csv"
        if not path.exists():
            continue
        for row in _read(path):
            days.append(date.fromisoformat(row["date"]))
            if model == "era5":
                density = row.get("snow_density_kg_m3") or ""
                values.append(
                    geometric_depth_m(float(row["swe_mm_we"]), float(density))
                    if density
                    else float("nan")
                )
            else:
                values.append(
                    float(grid_mean_depth_m(float(row["frsno"]), float(row["snodp_m"])))
                )
    order = np.argsort(days)
    return DailySeries(
        dates=tuple(np.array(days, dtype=object)[order]),
        values=np.asarray(values, dtype=float)[order],
    )


def summarize_model(
    checkpoints: Path, model: str, water_years
) -> list[WaterYearStats]:
    """Compute per-water-year statistics for one model."""
    from .snowseason import water_year_slice

    swe = load_swe_series(checkpoints, model, water_years)
    depth = load_depth_series(checkpoints, model, water_years)

    out: list[WaterYearStats] = []
    for wy in water_years:
        year_swe = water_year_slice(swe, wy)
        year_depth = water_year_slice(depth, wy)
        if len(year_swe) == 0:
            continue
        top = peak(year_swe)
        out.append(
            WaterYearStats(
                water_year=wy,
                peak_swe_mm=top.value,
                peak_day=top.day,
                april_first_swe_mm=april_first(year_swe, wy),
                april_first_depth_m=april_first(year_depth, wy),
                season_mean_swe_mm=mean_over(
                    year_swe, date(wy - 1, 10, 1), date(wy, 6, 30)
                ),
                melt_out=melt_out_date(year_swe, MELT_OUT_THRESHOLD_MM),
                n_days=len(year_swe),
            )
        )
    return out


def ranked(stats: list[WaterYearStats], field: str) -> dict[int, tuple[float, float, float]]:
    """Return ``{water_year: (value, rank, standardized_anomaly)}`` for a field."""
    values = np.array([getattr(s, field) for s in stats], dtype=float)
    ranks = rank_ascending(values)
    anomalies = standardized_anomaly(values)
    return {
        s.water_year: (float(values[i]), float(ranks[i]), float(anomalies[i]))
        for i, s in enumerate(stats)
    }


def model_agreement(
    a: list[WaterYearStats], b: list[WaterYearStats], field: str
) -> tuple[float, float, int]:
    """Spearman rank correlation between two models over their common years."""
    shared = sorted({s.water_year for s in a} & {s.water_year for s in b})
    va = np.array([getattr(s, field) for s in a if s.water_year in shared], dtype=float)
    vb = np.array([getattr(s, field) for s in b if s.water_year in shared], dtype=float)
    rho, p = spearman_rho(va, vb)
    return rho, p, len(shared)
