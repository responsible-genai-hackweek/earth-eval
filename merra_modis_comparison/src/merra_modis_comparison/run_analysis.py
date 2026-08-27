"""Build the daily record for both reanalyses, water year by water year.

**The per-cell slab is the checkpoint.** Each water year is stored as a compressed
array of daily fields on the model's own native grid, and the domain-mean CSV is
*derived* from it. That ordering matters: a scalar cannot be un-averaged, so a
checkpoint holding only domain means cannot answer a question about a product or
ratio of two fields, nor produce a map. Storing the cells costs about twelve
megabytes for the whole record and makes every downstream quantity rebuildable
with no network access at all.

Raw granules are still never persisted - only the 72-cell (or 399-cell) daily
means that the analysis is defined over.
"""

from __future__ import annotations

import csv
import os
import sys
from datetime import date
from pathlib import Path

import numpy as np

from .calendars import enumerate_dates
from .fetch import domain_mean_of, era5_daily_cells, merra2_daily_cells, open_era5
from .grid import build_target_grid
from .regrid import domain_area_weights
from .terrain import BANDS, band_masks, mountain_mask
from .snowvars import (
    era5_snow_cover,
    geometric_depth_m,
    grid_mean_depth_m,
    swe_from_water_equivalent_m,
)

RESULTS = Path(__file__).resolve().parents[2] / "results"
CELLS = RESULTS / "water_year_1981_2026_cell_checkpoints"
CHECKPOINTS = RESULTS / "water_year_1981_2026_daily_checkpoints"

#: Last MERRA-2 granule published, verified against the archive. The collection
#: lags real time by about four weeks.
MERRA2_LAST_DATE = date(2026, 8, 1)

DOMAIN = (-109.0625, -104.0625, 36.75, 41.25)
#: Band columns are suffixed onto the masked domain series, so one file per
#: water year still holds everything derived from that year's cells.
_BAND_KEYS = tuple(key for key, _, _, _ in BANDS)
ERA5_COLUMNS = (
    ("date", "stream", "swe_mm_we", "snow_density_kg_m3", "depth_m", "fsca")
    + tuple(f"swe_mm_{k}" for k in _BAND_KEYS)
    + tuple(f"depth_m_{k}" for k in _BAND_KEYS)
)
MERRA2_COLUMNS = (
    ("date", "frsno", "snodp_m", "snomas_kg_m2", "depth_m")
    + tuple(f"swe_mm_{k}" for k in _BAND_KEYS)
    + tuple(f"depth_m_{k}" for k in _BAND_KEYS)
)


def cell_path(model: str, wy: int) -> Path:
    return CELLS / f"{model}_WY{wy}.npz"


def checkpoint_path(model: str, wy: int) -> Path:
    return CHECKPOINTS / f"{model}_WY{wy}.csv"


def _write_atomic_npz(path: Path, **arrays) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp{os.getpid()}.npz")
    np.savez_compressed(tmp, **arrays)
    tmp.replace(path)


def _write_atomic_csv(path: Path, header, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp{os.getpid()}")
    with tmp.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


def _masked_weights(lat, lon):
    """Area weights zeroed outside the mountain mask, plus one set per band.

    The mask is a weight rather than a crop, so the grid and every checkpoint
    stay untouched and the threshold can be changed by re-deriving alone.
    """
    area = domain_area_weights(lat, lon, *DOMAIN)
    masked = area * mountain_mask(lat, lon)
    bands = {k: area * m for k, m in band_masks(lat, lon).items()}
    return masked, bands


def derive_era5_csv(wy: int) -> None:
    """Rebuild one ERA5 domain-mean CSV from its stored cells. No network."""
    with np.load(cell_path("era5", wy), allow_pickle=False) as data:
        days = [str(d) for d in data["_days"]]
        streams = [str(s) for s in data["_stream"]]
        weights, bands = _masked_weights(data["_lat"], data["_lon"])
        swe_cells = swe_from_water_equivalent_m(data["snow_depth"])
        density_cells = data["snow_density"]

    depth_cells = geometric_depth_m(swe_cells, density_cells)
    swe = domain_mean_of(swe_cells, weights)
    density = domain_mean_of(density_cells, weights)
    # Derived per cell, then averaged - the mean of a ratio, not a ratio of means.
    depth = domain_mean_of(depth_cells, weights)
    fsca = domain_mean_of(era5_snow_cover(swe_cells, density_cells), weights)
    band_swe = {k: domain_mean_of(swe_cells, w) for k, w in bands.items()}
    band_depth = {k: domain_mean_of(depth_cells, w) for k, w in bands.items()}

    rows = [
        [days[i], streams[i], f"{swe[i]:.6f}", f"{density[i]:.4f}",
         f"{depth[i]:.8f}", f"{fsca[i]:.8f}"]
        + [f"{band_swe[k][i]:.6f}" for k in _BAND_KEYS]
        + [f"{band_depth[k][i]:.8f}" for k in _BAND_KEYS]
        for i in range(len(days))
    ]
    _write_atomic_csv(checkpoint_path("era5", wy), ERA5_COLUMNS, rows)


def derive_merra2_csv(wy: int) -> None:
    """Rebuild one MERRA-2 domain-mean CSV from its stored cells. No network."""
    grid = build_target_grid()
    weights, bands = _masked_weights(grid.lat_centers, grid.lon_centers)
    with np.load(cell_path("merra2", wy), allow_pickle=False) as data:
        days = [str(d) for d in data["_days"]]
        frsno_cells = np.clip(data["FRSNO"], 0.0, 1.0)
        snodp_cells = data["SNODP"]
        snomas_cells = data["SNOMAS"]

    depth_cells = grid_mean_depth_m(frsno_cells, snodp_cells)
    frsno = domain_mean_of(frsno_cells, weights)
    snodp = domain_mean_of(snodp_cells, weights)
    snomas = domain_mean_of(snomas_cells, weights)
    depth = domain_mean_of(depth_cells, weights)
    band_swe = {k: domain_mean_of(snomas_cells, w) for k, w in bands.items()}
    band_depth = {k: domain_mean_of(depth_cells, w) for k, w in bands.items()}

    rows = [
        [days[i], f"{frsno[i]:.8f}", f"{snodp[i]:.8f}", f"{snomas[i]:.6f}",
         f"{depth[i]:.8f}"]
        + [f"{band_swe[k][i]:.6f}" for k in _BAND_KEYS]
        + [f"{band_depth[k][i]:.8f}" for k in _BAND_KEYS]
        for i in range(len(days))
    ]
    _write_atomic_csv(checkpoint_path("merra2", wy), MERRA2_COLUMNS, rows)


def build_era5_year(wy: int, workers: int = 24) -> None:
    """Fetch and store one water year, clipped to what the store actually holds."""
    if not cell_path("era5", wy).exists():
        _, _, _, era5t_stop = open_era5()
        days = [d for d in enumerate_dates((wy,)) if d <= era5t_stop]
        if not days:
            return
        got = era5_daily_cells(
            days, variables=("snow_depth", "snow_density"), hours=(12,), workers=workers
        )
        _write_atomic_npz(cell_path("era5", wy), **got)
    derive_era5_csv(wy)


def build_merra2_year(wy: int, workers: int = 16) -> None:
    if not cell_path("merra2", wy).exists():
        days = [d for d in enumerate_dates((wy,)) if d <= MERRA2_LAST_DATE]
        if not days:
            return
        got = merra2_daily_cells(days, workers=workers)
        _write_atomic_npz(cell_path("merra2", wy), **got)
    derive_merra2_csv(wy)


def fetch_order(first: int, last: int) -> list[int]:
    """Most recent water year first, working backwards.

    Ordering by recency rather than by date ascending means every partial run is
    a usable record: the years the analysis is about arrive within minutes, and
    each additional year deepens the climatology from the recent end. A
    chronological walk delivers the least relevant years first and the feature
    years last, which is the wrong thing to hold when time runs out.
    """
    return list(range(last, first - 1, -1))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    model = argv[0] if argv else "both"
    first = int(argv[1]) if len(argv) > 1 else 1981
    last = int(argv[2]) if len(argv) > 2 else 2026

    for wy in fetch_order(first, last):
        try:
            if model in ("era5", "both"):
                build_era5_year(wy)
            if model in ("merra2", "both"):
                build_merra2_year(wy)
            print(f"WY{wy} done", flush=True)
        except Exception as exc:  # a year may fail without losing the rest
            print(f"WY{wy} FAILED: {type(exc).__name__}: {exc}", flush=True)
    # A run that skipped a year must say so. A silent gap in the record is
    # otherwise only found by reading a directory listing, which is not a check.
    wanted = set(fetch_order(first, last))
    have = {
        int(p.stem.split("WY")[1])
        for p in CELLS.glob(f"{'era5' if model == 'era5' else 'merra2'}_*.npz")
    }
    missing = sorted(wanted - have)
    if missing:
        print(f"INCOMPLETE: {len(missing)} water year(s) missing: {missing}", flush=True)
    else:
        print(f"complete: all {len(wanted)} water years present", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
