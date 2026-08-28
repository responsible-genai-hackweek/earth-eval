"""Illustrative example-day imagery (2011-01-15 high-snow, 2015-06-01 low-snow).

Reruns the target day's month through the real month-task function
(`pipeline.compute_month`) with a capturing callback, so panels 2/3 are
produced by the identical aggregation code path as the checkpoint pipeline --
never a separate or resampled reimplementation. The recomputed month is then
compared against the checkpoint already on disk (never overwriting it) as a
cross-check that this rerun agrees with the validated pipeline. These outputs
are illustrative only and never feed back into checkpoint statistics or the
final aggregate CSVs.

No bilinear (or any other) resampling of MERRA-2 appears anywhere in this
module: M is read directly off the native MERRA grid (worker._merra_fraction_by_cell_id)
and R is the same equal-area pixel-center aggregation used everywhere else
(regrid.apply_mapping). See scientific-contract.md "Regridding".
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

import numpy as np
import xarray as xr

from . import checkpoint, config, dates, earthdata, figures, pipeline, regrid, worker


class ExampleGenerationError(Exception):
    """Raised when the target date is not reachable, or the recomputed month
    checkpoint disagrees with the one already on disk.
    """


@dataclass(frozen=True)
class ExampleDayResult:
    date: date
    label: str
    modis_lon: np.ndarray  # flattened, degrees
    modis_lat: np.ndarray
    modis_snow_fraction: np.ndarray  # flattened, raw 0-100(+) percent, fill included
    r_grid: np.ndarray  # (N_LAT_CELLS, N_LON_CELLS), percent, panel 2
    m_grid: np.ndarray  # (N_LAT_CELLS, N_LON_CELLS), percent, panel 3
    diff_grid: np.ndarray  # M - R, percentage points, panel 4
    support_fraction_grid: np.ndarray  # (N_LAT_CELLS, N_LON_CELLS)
    valid_pixels_grid: np.ndarray
    cross_check_ok: bool
    cross_check_errors: list[str]


def _rows_match(rows_a: list[dict], rows_b: list[dict]) -> tuple[bool, list[str]]:
    errors = []
    if len(rows_a) != len(rows_b):
        return False, [f"row count differs: {len(rows_a)} != {len(rows_b)}"]

    for row_a, row_b in zip(rows_a, rows_b):
        if row_a["cell_id"] != row_b["cell_id"]:
            errors.append(f"cell_id mismatch: {row_a['cell_id']} != {row_b['cell_id']}")
            continue
        for column in checkpoint.ALL_COLUMNS:
            va, vb = row_a[column], row_b[column]
            if column in checkpoint._FLOAT_COLUMNS:
                if not checkpoint._close_or_both_nan(float(va), float(vb)):
                    errors.append(f"cell {row_a['cell_id']}: {column} {va} != {vb}")
            elif va != vb:
                errors.append(f"cell {row_a['cell_id']}: {column} {va} != {vb}")

    return len(errors) == 0, errors


def generate_example(
    d: date, label: str, transport: earthdata.Transport, mapping: regrid.PixelCellMapping,
    results_dir: str, tmp_dir_root: str,
) -> ExampleDayResult:
    water_year = dates.water_year_of(d)
    year, month = d.year, d.month

    captured: dict = {}

    def on_day_processed(day: date, raw: worker.RawDayInputs, record: worker.DayCellRecord) -> None:
        if day == d:
            captured["raw"] = raw
            captured["record"] = record

    rows, _metadata = pipeline.compute_month(
        water_year, year, month, transport, mapping, tmp_dir_root, on_day_processed=on_day_processed
    )

    if "record" not in captured:
        raise ExampleGenerationError(f"date {d} was not processed while computing {year:04d}-{month:02d}")

    raw: worker.RawDayInputs = captured["raw"]
    record: worker.DayCellRecord = captured["record"]

    existing_path = pipeline.month_checkpoint_path(results_dir, year, month)
    if os.path.exists(existing_path):
        _existing_metadata, existing_rows = checkpoint.read_checkpoint(existing_path)
        cross_check_ok, cross_check_errors = _rows_match(rows, existing_rows)
    else:
        cross_check_ok, cross_check_errors = False, [
            f"no existing checkpoint at {existing_path} to cross-check against"
        ]

    modis_lon_parts, modis_lat_parts, modis_sf_parts = [], [], []
    for tile in raw.modscag_tiles:
        lon, lat = regrid.transform_sinusoidal_to_lonlat(tile.pixel_x_sinusoidal, tile.pixel_y_sinusoidal)
        modis_lon_parts.append(lon)
        modis_lat_parts.append(lat)
        modis_sf_parts.append(tile.snow_fraction)

    r_grid = figures.cells_to_grid(record.aggregate.reference_fraction * 100.0)
    m_grid = figures.cells_to_grid(record.m_fraction * 100.0)

    return ExampleDayResult(
        date=d,
        label=label,
        modis_lon=np.concatenate(modis_lon_parts),
        modis_lat=np.concatenate(modis_lat_parts),
        modis_snow_fraction=np.concatenate(modis_sf_parts),
        r_grid=r_grid,
        m_grid=m_grid,
        diff_grid=m_grid - r_grid,
        support_fraction_grid=figures.cells_to_grid(record.aggregate.support_fraction),
        valid_pixels_grid=figures.cells_to_grid(record.aggregate.valid_pixels.astype(np.float64)),
        cross_check_ok=cross_check_ok,
        cross_check_errors=cross_check_errors,
    )


def write_example_netcdf(result: ExampleDayResult, out_path: str) -> None:
    lon_centers = np.array(config.CELL_LON_CENTERS)
    lat_centers = np.array(config.CELL_LAT_CENTERS)

    ds = xr.Dataset(
        data_vars={
            "modis_raw_snow_fraction": ("modis_pixel", result.modis_snow_fraction),
            "modis_pixel_lon": ("modis_pixel", result.modis_lon),
            "modis_pixel_lat": ("modis_pixel", result.modis_lat),
            "modis_aggregated_to_merra": (("lat", "lon"), result.r_grid),
            "merra_raw": (("lat", "lon"), result.m_grid),
            "merra_minus_modis_aggregated": (("lat", "lon"), result.diff_grid),
            "support_fraction": (("lat", "lon"), result.support_fraction_grid),
        },
        coords={"lon": lon_centers, "lat": lat_centers},
        attrs={
            "date": result.date.isoformat(),
            "label": result.label,
            "modscag_product": config.MODSCAG_PRODUCT,
            "modscag_version": config.MODSCAG_VERSION,
            "merra_collection": config.MERRA_COLLECTION,
            "merra_version": config.MERRA_VERSION,
            "merra_time_index": config.MERRA_TIME_INDEX,
            "error_sign": config.ERROR_SIGN,
            "aggregation": "equal_area_pixel_center_mean",
            "resampling": "none -- MERRA-2 is never resampled, see scientific-contract.md",
            "domain_lon_edge_min": config.DOMAIN_LON_EDGE_MIN,
            "domain_lon_edge_max": config.DOMAIN_LON_EDGE_MAX,
            "domain_lat_edge_min": config.DOMAIN_LAT_EDGE_MIN,
            "domain_lat_edge_max": config.DOMAIN_LAT_EDGE_MAX,
            "cross_check_ok": int(result.cross_check_ok),
            "illustrative_only": 1,
        },
    )
    directory = os.path.dirname(out_path) or "."
    os.makedirs(directory, exist_ok=True)
    ds.to_netcdf(out_path)


def render_example_figure(result: ExampleDayResult, out_path: str, dem=None) -> None:
    import matplotlib.pyplot as plt

    from . import terrain

    lon_edges = regrid.cell_lon_edges()
    lat_edges = regrid.cell_lat_edges()

    valid_modis = result.modis_snow_fraction <= 100
    panel1_sf = np.where(valid_modis, result.modis_snow_fraction, np.nan)

    shared_norm = terrain.shared_norm(result.r_grid, result.m_grid, diverging=False)
    diff_norm = terrain.diverging_norm(result.diff_grid)

    fig, axes = plt.subplots(1, 4, figsize=(22, 5), constrained_layout=True)

    for ax in axes:
        figures._draw_hillshade_background(ax, dem)

    ax = axes[0]
    scatter = ax.scatter(
        result.modis_lon, result.modis_lat, c=panel1_sf, cmap="YlOrRd",
        vmin=0, vmax=100, s=1, marker=".", zorder=2,
    )
    figures._draw_elevation_contours(ax, dem)
    fig.colorbar(scatter, ax=ax, shrink=0.85)
    ax.set_xlim(config.DOMAIN_LON_EDGE_MIN, config.DOMAIN_LON_EDGE_MAX)
    ax.set_ylim(config.DOMAIN_LAT_EDGE_MIN, config.DOMAIN_LAT_EDGE_MAX)
    ax.set_title(f"MODIS raw 500 m ({result.date.isoformat()})")

    mean_support = np.nanmean(result.support_fraction_grid)
    total_valid = int(np.nansum(result.valid_pixels_grid))

    ax = axes[1]
    mesh = ax.pcolormesh(lon_edges, lat_edges, result.r_grid, cmap="YlOrRd", norm=shared_norm, alpha=0.85, zorder=2)
    figures._draw_elevation_contours(ax, dem)
    fig.colorbar(mesh, ax=ax, shrink=0.85)
    ax.set_title(
        f"MODIS aggregated to MERRA (R)\nmean support={mean_support:.2f}, valid pixels={total_valid}"
    )

    ax = axes[2]
    mesh = ax.pcolormesh(lon_edges, lat_edges, result.m_grid, cmap="YlOrRd", norm=shared_norm, alpha=0.85, zorder=2)
    figures._draw_elevation_contours(ax, dem)
    fig.colorbar(mesh, ax=ax, shrink=0.85)
    ax.set_title("MERRA-2 raw, native grid (M)")

    ax = axes[3]
    mesh = ax.pcolormesh(lon_edges, lat_edges, result.diff_grid, cmap="RdBu_r", norm=diff_norm, alpha=0.85, zorder=2)
    figures._draw_elevation_contours(ax, dem)
    fig.colorbar(mesh, ax=ax, shrink=0.85)
    ax.set_title("M - R (pp)")

    for ax in axes[1:]:
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")

    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
