"""USGS 3DEP terrain background: DEM fetch, hillshade, elevation contours,
whitespace cropping, and the diverging/sequential colormap conventions from
statistics-and-figures.md.

Note: DEM rasters fetched here may be resized with ordinary image
interpolation (including bilinear) when the source resolution differs from
the display grid. This is unrelated to, and does not affect, the MODIS ->
MERRA aggregation in regrid.py -- the scientific-contract prohibition on
bilinear resampling applies only to the fSCA comparison reference, never to
this cosmetic terrain basemap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import matplotlib.colors as mcolors
import numpy as np

CONTOUR_LEVELS_M = (2000, 3000)  # statistics-and-figures.md: major contours only
HILLSHADE_AZIMUTH_DEG = 315.0
HILLSHADE_ALTITUDE_DEG = 45.0

DEM_SERVICE_URL = (
    "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/"
    "ImageServer/exportImage"
)


@dataclass(frozen=True)
class DemGrid:
    """A coarse elevation raster covering a lon/lat bounding box."""

    elevation_m: np.ndarray  # shape (height_px, width_px)
    lon_edges: np.ndarray  # shape (width_px + 1,)
    lat_edges: np.ndarray  # shape (height_px + 1,)


class DemTransport(Protocol):
    def fetch(
        self, lon_min: float, lat_min: float, lon_max: float, lat_max: float, width_px: int, height_px: int
    ) -> DemGrid: ...


class RealDemTransport:
    """Live USGS 3DEP ImageServer transport. Requires network access.
    Tests use a fake DemTransport instead."""

    def fetch(
        self, lon_min: float, lat_min: float, lon_max: float, lat_max: float, width_px: int, height_px: int
    ) -> DemGrid:
        import io

        import rasterio
        import requests

        params = {
            "bbox": f"{lon_min},{lat_min},{lon_max},{lat_max}",
            "bboxSR": 4326,
            "imageSR": 4326,
            "size": f"{width_px},{height_px}",
            "format": "tiff",
            "pixelType": "F32",
            "noData": "-9999",
            "interpolation": "RSP_BilinearInterpolation",  # DEM basemap only, see module docstring
            "f": "image",
        }
        response = requests.get(DEM_SERVICE_URL, params=params, timeout=60)
        response.raise_for_status()

        with rasterio.io.MemoryFile(response.content) as memfile:
            with memfile.open() as dataset:
                elevation = dataset.read(1).astype(np.float64)
                elevation[elevation == -9999] = np.nan

        lon_edges = np.linspace(lon_min, lon_max, width_px + 1)
        lat_edges = np.linspace(lat_min, lat_max, height_px + 1)
        return DemGrid(elevation_m=elevation, lon_edges=lon_edges, lat_edges=lat_edges)


class LocalFileDemTransport:
    """Reads a local GeoTIFF instead of hitting the live 3DEP service --
    e.g. the checked-in `tests/fixtures/domain_dem_3dep.tif` fixture, which
    is a real (not synthetic) 3DEP raster already covering the configured
    domain at the same 800x600 display grid `fetch_dem` defaults to.
    """

    def __init__(self, path: str) -> None:
        self.path = path

    def fetch(
        self, lon_min: float, lat_min: float, lon_max: float, lat_max: float, width_px: int, height_px: int
    ) -> DemGrid:
        import rasterio

        with rasterio.open(self.path) as dataset:
            elevation = dataset.read(1).astype(np.float64)
            if dataset.nodata is not None:
                elevation[elevation == dataset.nodata] = np.nan

        lon_edges = np.linspace(lon_min, lon_max, width_px + 1)
        lat_edges = np.linspace(lat_min, lat_max, height_px + 1)
        return DemGrid(elevation_m=elevation, lon_edges=lon_edges, lat_edges=lat_edges)


def fetch_dem(
    lon_min: float, lat_min: float, lon_max: float, lat_max: float,
    transport: DemTransport, width_px: int = 800, height_px: int = 600,
) -> DemGrid:
    return transport.fetch(lon_min, lat_min, lon_max, lat_max, width_px, height_px)


def hillshade(
    elevation_m: np.ndarray,
    cellsize_x_m: float,
    cellsize_y_m: float,
    azimuth_deg: float = HILLSHADE_AZIMUTH_DEG,
    altitude_deg: float = HILLSHADE_ALTITUDE_DEG,
) -> np.ndarray:
    """Standard analytical hillshade, returned as a float array in [0, 1]."""
    dz_dy, dz_dx = np.gradient(elevation_m, cellsize_y_m, cellsize_x_m)
    slope = np.arctan(np.hypot(dz_dx, dz_dy))
    aspect = np.arctan2(-dz_dx, dz_dy)

    azimuth_rad = np.deg2rad(360.0 - azimuth_deg + 90.0)
    altitude_rad = np.deg2rad(altitude_deg)

    shaded = np.sin(altitude_rad) * np.cos(slope) + np.cos(altitude_rad) * np.sin(slope) * np.cos(
        azimuth_rad - aspect
    )
    return np.clip(shaded, 0.0, 1.0)


def contour_levels() -> tuple[int, ...]:
    return CONTOUR_LEVELS_M


def smooth_for_contours(elevation_m: np.ndarray, sigma_px: float = 12.0) -> np.ndarray:
    """Gaussian-smooth elevation before contouring only (never before
    hillshade). A real 3DEP raster has fine ridge/valley texture that turns
    two raw contour levels into an illegible tangle at domain scale; this
    blurs out sub-mountain-range detail so contours trace the major terrain
    shape. NaN-safe via normalized convolution so nodata edges stay NaN
    instead of bleeding a false low elevation into neighboring pixels.
    """
    from scipy.ndimage import gaussian_filter

    valid = np.isfinite(elevation_m)
    filled = np.where(valid, elevation_m, 0.0)
    weight = gaussian_filter(valid.astype(np.float64), sigma=sigma_px)
    smoothed = gaussian_filter(filled, sigma=sigma_px)

    with np.errstate(invalid="ignore", divide="ignore"):
        result = smoothed / weight
    result[weight < 1e-6] = np.nan
    return result


def crop_to_data_extent(array: np.ndarray, valid_mask: np.ndarray) -> tuple[slice, slice]:
    """Return (row_slice, col_slice) trimming all-invalid outer rows/columns."""
    if not valid_mask.any():
        return slice(0, 0), slice(0, 0)

    rows = np.where(valid_mask.any(axis=1))[0]
    cols = np.where(valid_mask.any(axis=0))[0]
    return slice(rows.min(), rows.max() + 1), slice(cols.min(), cols.max() + 1)


def diverging_norm(values: np.ndarray, trim_percentile: float = 2.0) -> mcolors.TwoSlopeNorm:
    """Diverging scale centered at zero for signed bias/error, with extremes
    trimmed by percentile to avoid a few outlier cell-days dominating the scale.
    """
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return mcolors.TwoSlopeNorm(vmin=-1.0, vcenter=0.0, vmax=1.0)

    low = np.percentile(finite, trim_percentile)
    high = np.percentile(finite, 100.0 - trim_percentile)
    bound = max(abs(low), abs(high), 1e-9)
    return mcolors.TwoSlopeNorm(vmin=-bound, vcenter=0.0, vmax=bound)


def sequential_norm(values: np.ndarray) -> mcolors.Normalize:
    """Non-diverging scale for nonnegative quantities (MAE, fSCA)."""
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return mcolors.Normalize(vmin=0.0, vmax=1.0)
    return mcolors.Normalize(vmin=0.0, vmax=max(float(finite.max()), 1e-9))


def shared_norm(*value_arrays: np.ndarray, diverging: bool = False) -> mcolors.Normalize:
    """Compute one norm shared across multiple panels' arrays."""
    stacked = np.concatenate([np.asarray(a).ravel() for a in value_arrays])
    if diverging:
        return diverging_norm(stacked)
    return sequential_norm(stacked)
