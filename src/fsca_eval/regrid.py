"""MODIS pixel-center to MERRA-2 cell aggregation.

This is the single code path used by both the production pipeline
(`worker.reduce_day`) and the illustrative example-day figures
(`examples.py`). Do not duplicate this logic elsewhere, and never resample
MERRA-2 down to MODIS resolution here or anywhere else -- see
scientific-contract.md "Regridding".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyproj

from . import config

# Standard MODIS sinusoidal projection (sphere radius 6371007.181 m).
MODIS_SINUSOIDAL_PROJ4 = "+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +R=6371007.181 +units=m +no_defs"

_transformer = pyproj.Transformer.from_crs(
    MODIS_SINUSOIDAL_PROJ4, "EPSG:4326", always_xy=True
)


def transform_sinusoidal_to_lonlat(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Transform MODIS sinusoidal pixel-center coordinates (meters) to lon/lat."""
    lon, lat = _transformer.transform(np.asarray(x), np.asarray(y))
    return np.asarray(lon), np.asarray(lat)


def cell_lon_edges() -> np.ndarray:
    return np.array(
        [config.DOMAIN_LON_EDGE_MIN + i * config.LON_SPACING for i in range(config.N_LON_CELLS + 1)]
    )


def cell_lat_edges() -> np.ndarray:
    return np.array(
        [config.DOMAIN_LAT_EDGE_MIN + i * config.LAT_SPACING for i in range(config.N_LAT_CELLS + 1)]
    )


def cell_id_from_indices(lon_idx: np.ndarray, lat_idx: np.ndarray) -> np.ndarray:
    """Stable cell_id in [0, N_CELLS), row-major over (lon_idx, lat_idx)."""
    return lon_idx * config.N_LAT_CELLS + lat_idx


def cell_id_to_center(cell_id: int) -> tuple[float, float]:
    lon_idx, lat_idx = divmod(cell_id, config.N_LAT_CELLS)
    return config.CELL_LON_CENTERS[lon_idx], config.CELL_LAT_CENTERS[lat_idx]


@dataclass(frozen=True)
class PixelCellMapping:
    """Static geometry: which MERRA cell each MODIS pixel center falls into.

    This depends only on fixed MODIS tile pixel-center geometry, not on any
    day's data, so one instance is built once per worker process and reused
    for every date it handles.
    """

    pixel_cell_id: np.ndarray  # shape (n_pixels,), -1 if outside the domain
    expected_pixels_per_cell: np.ndarray  # shape (N_CELLS,), int


def build_mapping(pixel_lon: np.ndarray, pixel_lat: np.ndarray) -> PixelCellMapping:
    """Build the static pixel -> MERRA cell membership mapping.

    Parameters
    ----------
    pixel_lon, pixel_lat:
        Flattened arrays of MODIS pixel-center longitude/latitude (degrees),
        already transformed out of sinusoidal coordinates.
    """
    pixel_lon = np.asarray(pixel_lon)
    pixel_lat = np.asarray(pixel_lat)

    lon_edges = cell_lon_edges()
    lat_edges = cell_lat_edges()

    # searchsorted gives the right bin only for values within edges; check bounds explicitly.
    lon_idx = np.searchsorted(lon_edges, pixel_lon, side="right") - 1
    lat_idx = np.searchsorted(lat_edges, pixel_lat, side="right") - 1

    inside = (
        (pixel_lon >= lon_edges[0])
        & (pixel_lon < lon_edges[-1])
        & (pixel_lat >= lat_edges[0])
        & (pixel_lat < lat_edges[-1])
        & (lon_idx >= 0)
        & (lon_idx < config.N_LON_CELLS)
        & (lat_idx >= 0)
        & (lat_idx < config.N_LAT_CELLS)
    )

    pixel_cell_id = np.full(pixel_lon.shape, -1, dtype=np.int64)
    pixel_cell_id[inside] = cell_id_from_indices(lon_idx[inside], lat_idx[inside])

    expected_pixels_per_cell = np.bincount(
        pixel_cell_id[pixel_cell_id >= 0], minlength=config.N_CELLS
    ).astype(np.int64)

    return PixelCellMapping(
        pixel_cell_id=pixel_cell_id, expected_pixels_per_cell=expected_pixels_per_cell
    )


@dataclass(frozen=True)
class CellDayAggregate:
    """One day's aggregated MODSCAG reference value and pixel accounting, per cell."""

    reference_fraction: np.ndarray  # shape (N_CELLS,), NaN where valid_pixels == 0
    valid_pixels: np.ndarray  # shape (N_CELLS,), int
    expected_pixels: np.ndarray  # shape (N_CELLS,), int
    observed_pixels: np.ndarray  # shape (N_CELLS,), int
    support_fraction: np.ndarray  # shape (N_CELLS,), float, 0 where expected == 0


def apply_mapping(
    mapping: PixelCellMapping,
    snow_fraction: np.ndarray,
    days_without_observation: np.ndarray,
) -> CellDayAggregate:
    """Aggregate one day's MODSCAG pixels to the MERRA-2 cell grid.

    `snow_fraction` is the raw 0-100(+) percent array; values > 100 are fill
    and excluded. `days_without_observation == 0` marks a directly observed
    pixel; other valid values are the product's own documented
    interpolation and are still counted as valid, just not "observed".
    """
    snow_fraction = np.asarray(snow_fraction).ravel()
    days_without_observation = np.asarray(days_without_observation).ravel()
    cell_id = mapping.pixel_cell_id

    if snow_fraction.shape != cell_id.shape:
        raise ValueError(
            f"snow_fraction shape {snow_fraction.shape} does not match mapping "
            f"geometry shape {cell_id.shape}; MODIS grid disagrees with the "
            "cached static mapping."
        )

    in_domain = cell_id >= 0
    valid = in_domain & (snow_fraction <= 100)
    observed = valid & (days_without_observation == 0)

    n = config.N_CELLS
    valid_ids = cell_id[valid]
    sum_fraction = np.bincount(valid_ids, weights=snow_fraction[valid] / 100.0, minlength=n)
    valid_pixels = np.bincount(valid_ids, minlength=n).astype(np.int64)
    observed_pixels = np.bincount(cell_id[observed], minlength=n).astype(np.int64)

    expected_pixels = mapping.expected_pixels_per_cell.astype(np.int64)

    with np.errstate(invalid="ignore", divide="ignore"):
        reference_fraction = np.where(valid_pixels > 0, sum_fraction / valid_pixels, np.nan)
        support_fraction = np.where(expected_pixels > 0, valid_pixels / expected_pixels, 0.0)

    return CellDayAggregate(
        reference_fraction=reference_fraction,
        valid_pixels=valid_pixels,
        expected_pixels=expected_pixels,
        observed_pixels=observed_pixels,
        support_fraction=support_fraction,
    )
