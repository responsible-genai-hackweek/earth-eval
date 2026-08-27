"""Water year 2023 satellite validation: STC-MODSCAG fSCA against both models.

WY2023 is the validation year because it lies entirely inside the clean
historical MODSCAG record, which ends 2023-09-30. No product splice, no
near-real-time era and no algorithm-version break is involved.

The three published tiles cannot fully cover the domain: cell ``j260_i121``
receives only 85.6% of its pixel centres because the rest live in ``h10v05``,
which NSIDC does not publish. That deficit is above the 80% support threshold, so
it would pass silently. It is accepted explicitly here and recorded per day.
"""

from __future__ import annotations

import concurrent.futures as cf
import csv
import os
import threading
from datetime import date
from pathlib import Path

import numpy as np

from .calendars import enumerate_dates
from .grid import build_target_grid
from .modis import tile_coordinates
from .pixelmap import (
    assert_coverage,
    build_tile_window,
    coverage_report,
    global_expected_counts,
    reduce_tile,
)
from .regrid import domain_area_weights
from .sources.modscag import open_session, read_snow_fraction

__all__ = ["build_wy2023_reference"]

TILES = ("h09v04", "h09v05", "h10v04")
SUPPORT_THRESHOLD = 0.8
#: ``status`` distinguishes a day with no usable reference from a day whose
#: fetch failed. Both leave ``domain_fsca`` empty, and conflating them would
#: silently shorten the record.
COLUMNS = (
    "date", "domain_fsca", "cells_supported", "mean_support",
    "status", "deficient_cells",
)


def _windows(grid):
    return {tile: build_tile_window(tile, grid, *tile_coordinates(tile, 2400))
            for tile in TILES}


def reference_day(day: date, grid, windows, expected, weights, session):
    """Aggregate one day's MODSCAG tiles onto the target grid."""
    sums = np.zeros(grid.n_cells)
    counts = np.zeros(grid.n_cells, dtype=np.int64)
    for tile, window in windows.items():
        if window.is_empty:
            continue
        fraction, valid = read_snow_fraction(
            tile, day, session,
            slice(window.row_start, window.row_stop),
            slice(window.col_start, window.col_stop),
        )
        tile_sums, tile_counts = reduce_tile(
            np.nan_to_num(fraction), valid, window, grid.n_cells
        )
        sums += tile_sums
        counts += tile_counts

    support = counts / np.maximum(expected, 1)
    supported = support >= SUPPORT_THRESHOLD
    cell_fsca = np.where(supported & (counts > 0), sums / np.maximum(counts, 1), np.nan)

    flat_weights = weights.ravel()
    usable = supported & np.isfinite(cell_fsca)
    domain = (
        float((cell_fsca[usable] * flat_weights[usable]).sum() / flat_weights[usable].sum())
        if np.any(usable) else float("nan")
    )
    return domain, int(supported.sum()), float(support.mean())


def build_wy2023_reference(results: Path, workers: int = 6) -> Path:
    """Write the daily domain-mean MODSCAG fSCA series for WY2023."""
    grid = build_target_grid()
    report = coverage_report(grid, TILES)
    # Documented, not discovered at runtime: h10v05 is not published.
    assert_coverage(report, accept_deficit=True)
    deficient = ",".join(grid.cell_ids[i] for i in report.deficient)

    windows = _windows(grid)
    expected = global_expected_counts(grid)
    weights = domain_area_weights(
        grid.lat_centers, grid.lon_centers, -109.0625, -104.0625, 36.75, 41.25
    )
    days = enumerate_dates((2023,))
    local = threading.local()
    failures: list[str] = []

    def one(day: date):
        session = getattr(local, "session", None)
        if session is None:
            session = open_session()
            local.session = session
        try:
            domain, supported, mean_support = reference_day(
                day, grid, windows, expected, weights, session
            )
            status = "ok" if supported else "no_reference"
            return day, (domain, supported, mean_support, status)
        except Exception as exc:
            # Recorded, not swallowed: a day that silently became NaN would
            # shorten the record without anyone noticing.
            failures.append(f"{day.isoformat()}: {type(exc).__name__}: {exc}")
            return day, (float("nan"), 0, float("nan"), "fetch_failed")

    rows = []
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for day, (domain, supported, mean_support, status) in pool.map(one, days):
            rows.append([
                day.isoformat(),
                "" if not np.isfinite(domain) else f"{domain:.6f}",
                supported,
                "" if not np.isfinite(mean_support) else f"{mean_support:.4f}",
                status,
                deficient,
            ])

    rows.sort(key=lambda r: r[0])
    path = results / "wy2023_modscag_domain_fsca.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp{os.getpid()}")
    with tmp.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)
    if failures:
        print(f"{len(failures)} day(s) failed; first: {failures[0]}", flush=True)
    return path


if __name__ == "__main__":
    print(build_wy2023_reference(Path(__file__).resolve().parents[2] / "results"))
