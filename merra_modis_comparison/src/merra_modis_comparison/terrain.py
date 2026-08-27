"""Per-cell terrain, and the mountain mask derived from it.

The analysis domain is a rectangle, so it necessarily includes ground that is
not mountain: its eastern column reaches the High Plains and its western column
the Colorado Plateau. Low ground rarely holds snow, so leaving it in dilutes a
domain mean with cells that contribute mostly zeros.

The mask is applied as a *weight*, not a crop, so the grid, the slot order and
every checkpoint stay untouched. Because the daily fields are stored per cell,
changing the threshold re-derives every downstream number without refetching
anything.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

__all__ = [
    "BAND_SPLIT_FT",
    "BAND_SPLIT_M",
    "MOUNTAIN_MIN_ELEVATION_FT",
    "BANDS",
    "MOUNTAIN_MIN_ELEVATION_M",
    "band_masks",
    "cell_mean_elevation",
    "dem_path",
    "domain_description",
    "mountain_mask",
]

#: Thresholds are chosen and stated in feet, the unit Colorado terrain is
#: discussed in, and converted to metres for use against the DEM. Round numbers
#: in the unit a reader thinks in beat round numbers in the unit the file stores.
MOUNTAIN_MIN_ELEVATION_FT = 6500.0
BAND_SPLIT_FT = 8000.0

#: Cells whose mean elevation is below this are excluded from domain means.
#: Stated on every figure rather than buried, because it changes every number.
MOUNTAIN_MIN_ELEVATION_M = MOUNTAIN_MIN_ELEVATION_FT * 0.3048

#: Elevation dividing the montane band from the subalpine and alpine one.
BAND_SPLIT_M = BAND_SPLIT_FT * 0.3048

#: The two bands, as ``(key, label, low, high)``. A single split at
#: :data:`BAND_SPLIT_M`, above and below. The lower band starts at the mountain
#: threshold rather than at zero, because the mask has already removed the
#: plains - "below" here means the montane band, not the whole lowland.
BANDS = (
    ("below", f"Below {BAND_SPLIT_FT:,.0f} ft", MOUNTAIN_MIN_ELEVATION_M, BAND_SPLIT_M),
    ("above", f"Above {BAND_SPLIT_FT:,.0f} ft", BAND_SPLIT_M, float("inf")),
)


def dem_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "usgs_3dep_coarse_dem.tif"


@lru_cache(maxsize=4)
def _dem() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    import rasterio

    with rasterio.open(dem_path()) as handle:
        values = handle.read(1).astype(np.float64)
        transform = handle.transform
    rows, cols = np.mgrid[0 : values.shape[0], 0 : values.shape[1]]
    lon = transform.c + (cols + 0.5) * transform.a
    lat = transform.f + (rows + 0.5) * transform.e
    return values, lat, lon


def cell_mean_elevation(lat_centers: np.ndarray, lon_centers: np.ndarray) -> np.ndarray:
    """Mean bare-earth elevation of every cell, in metres, shaped (nlat, nlon).

    Works for any regular latitude/longitude grid, so the same mask can be
    applied to both models on their own native grids.
    """
    values, lat, lon = _dem()
    lat_c = np.asarray(lat_centers, dtype=np.float64)
    lon_c = np.asarray(lon_centers, dtype=np.float64)
    lon_c = np.where(lon_c > 180.0, lon_c - 360.0, lon_c)

    lat_edges = _edges(lat_c)
    lon_edges = _edges(lon_c)
    out = np.full((lat_c.size, lon_c.size), np.nan)
    for i in range(lat_c.size):
        lo, hi = sorted(lat_edges[i : i + 2])
        rows = (lat >= lo) & (lat < hi)
        for j in range(lon_c.size):
            left, right = sorted(lon_edges[j : j + 2])
            picked = values[rows & (lon >= left) & (lon < right)]
            if picked.size:
                out[i, j] = picked.mean()
    return out


def mountain_mask(
    lat_centers: np.ndarray,
    lon_centers: np.ndarray,
    threshold_m: float = MOUNTAIN_MIN_ELEVATION_M,
) -> np.ndarray:
    """Boolean mask of cells whose mean elevation reaches ``threshold_m``.

    Cells the DEM does not cover are excluded: an unknown elevation is not an
    argument for keeping a cell in a mountain mask.
    """
    elevation = cell_mean_elevation(lat_centers, lon_centers)
    return np.isfinite(elevation) & (elevation >= threshold_m)


def band_masks(
    lat_centers: np.ndarray, lon_centers: np.ndarray
) -> dict[str, np.ndarray]:
    """Boolean mask per elevation band, keyed by the band's short name."""
    elevation = cell_mean_elevation(lat_centers, lon_centers)
    return {
        key: np.isfinite(elevation) & (elevation >= low) & (elevation < high)
        for key, _, low, high in BANDS
    }


def domain_description(lat_centers: np.ndarray, lon_centers: np.ndarray) -> str:
    """One terse line naming the bounding box and the mask, for a subtitle.

    Stated on the figure rather than in a methods note, because the mask changes
    every number on it.
    """
    lon = np.asarray(lon_centers, dtype=np.float64)
    lon = np.where(lon > 180.0, lon - 360.0, lon)
    lat_e, lon_e = _edges(np.asarray(lat_centers, float)), _edges(lon)
    mask = mountain_mask(lat_centers, lon_centers)
    return (
        f"{abs(lon_e.min()):.2f}\u2013{abs(lon_e.max()):.2f}\u00b0W, "
        f"{lat_e.min():.2f}\u2013{lat_e.max():.2f}\u00b0N  \u00b7  "
        f"{int(mask.sum())} of {mask.size} cells with mean elevation "
        f"\u2265 {MOUNTAIN_MIN_ELEVATION_FT:,.0f} ft"
    )


def _edges(centers: np.ndarray) -> np.ndarray:
    inner = (centers[:-1] + centers[1:]) / 2.0
    first = centers[0] - (inner[0] - centers[0])
    last = centers[-1] + (centers[-1] - inner[-1])
    return np.concatenate([[first], inner, [last]])
