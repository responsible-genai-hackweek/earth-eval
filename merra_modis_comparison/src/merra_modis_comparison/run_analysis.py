"""Build the daily domain-mean series for both reanalyses, water year by water year.

Checkpoints one CSV per model per water year, so an interrupted run resumes
without refetching. Raw fields are never persisted - only the domain means.
"""

from __future__ import annotations

import csv
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from .calendars import enumerate_dates
from .fetch import era5_daily_means, merra2_daily_means, open_era5

RESULTS = Path(__file__).resolve().parents[2] / "results"
CHECKPOINTS = RESULTS / "daily_domain_means"

#: Last MERRA-2 granule published, verified against the archive. The collection
#: lags real time by about four weeks.
MERRA2_LAST_DATE = date(2026, 8, 1)

ERA5_COLUMNS = ("date", "stream", "swe_mm_we", "snow_density_kg_m3", "depth_m", "fsca")
MERRA2_COLUMNS = ("date", "frsno", "snodp_m", "snomas_kg_m2", "depth_m")


def checkpoint_path(model: str, wy: int) -> Path:
    return CHECKPOINTS / f"{model}_WY{wy}.csv"


def _write_atomic(path: Path, header: tuple[str, ...], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp{os.getpid()}")
    with tmp.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


def build_era5_year(wy: int, with_density: bool, workers: int = 24) -> None:
    """Build one water year, clipped to what the store actually holds.

    The most recent water year is necessarily partial. Clipping is explicit
    rather than incidental: the alternative is reading absent chunks back as
    NaN, which would quietly turn a short year into a missing one.
    """
    path = checkpoint_path("era5", wy)
    if path.exists():
        return
    _, _, _, era5t_stop = open_era5()
    days = [d for d in enumerate_dates((wy,)) if d <= era5t_stop]
    if not days:
        return
    variables = ("snow_depth", "snow_density") if with_density else ("snow_depth",)
    got = era5_daily_means(days, variables=variables, hours=(12,), workers=workers)
    density = got.get("snow_density")
    depth = got.get("depth_m")
    fsca = got.get("fsca")
    rows = [
        [
            d.isoformat(),
            got["_stream"][i],
            f"{got['snow_depth'][i] * 1000.0:.6f}",
            f"{density[i]:.4f}" if density is not None else "",
            f"{depth[i]:.8f}" if depth is not None else "",
            f"{fsca[i]:.8f}" if fsca is not None else "",
        ]
        for i, d in enumerate(got["_days"])
    ]
    _write_atomic(path, ERA5_COLUMNS, rows)


def build_merra2_year(wy: int, workers: int = 16) -> None:
    path = checkpoint_path("merra2", wy)
    if path.exists():
        return
    days = [d for d in enumerate_dates((wy,)) if d <= MERRA2_LAST_DATE]
    if not days:
        return
    got = merra2_daily_means(days, workers=workers)
    rows = [
        [
            d.isoformat(),
            f"{got['FRSNO'][i]:.8f}",
            f"{got['SNODP'][i]:.8f}",
            f"{got['SNOMAS'][i]:.6f}",
            f"{got['depth_m'][i]:.8f}",
        ]
        for i, d in enumerate(got["_days"])
    ]
    _write_atomic(path, MERRA2_COLUMNS, rows)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    model = argv[0] if argv else "both"
    first = int(argv[1]) if len(argv) > 1 else 1981
    last = int(argv[2]) if len(argv) > 2 else 2026

    for wy in range(first, last + 1):
        try:
            if model in ("era5", "both"):
                build_era5_year(wy, with_density=True)
            if model in ("merra2", "both"):
                build_merra2_year(wy)
            print(f"WY{wy} done", flush=True)
        except Exception as exc:  # a year may fail without losing the rest
            print(f"WY{wy} FAILED: {type(exc).__name__}: {exc}", flush=True)
    print("all requested water years attempted", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
