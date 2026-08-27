"""The MERRA-2 target grid and the pixel-center membership rule.

The comparison grid is the model's own native grid. Fine reference pixels are
aggregated up onto it; the model is never interpolated down. This module owns
the two things that decision depends on: which cells are in the domain, and
which fine pixel belongs to which cell.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["TargetGrid", "build_target_grid"]

# Published MERRA-2 grid geometry (M2T1NXLND, 0.625 x 0.5 degrees).
MERRA_LON_ORIGIN = -180.0
MERRA_LAT_ORIGIN = -90.0
MERRA_LON_STEP = 0.625
MERRA_LAT_STEP = 0.5
MERRA_N_LON = 576
MERRA_N_LAT = 361

# Authalic sphere radius used by the MODIS sinusoidal projection, in metres.
MODIS_SPHERE_RADIUS_M = 6371007.181


@dataclass(frozen=True)
class TargetGrid:
    """A rectangular block of complete native MERRA-2 cells.

    Cells are stored in a stable row-major order - latitude ascending (south to
    north), then longitude ascending (west to east). Checkpoint rows are written
    in this order and validated against it, so it must never change.
    """

    lat_centers: np.ndarray
    lon_centers: np.ndarray
    lat_indices: np.ndarray
    lon_indices: np.ndarray
    lat_edges: np.ndarray
    lon_edges: np.ndarray
    cell_ids: tuple[str, ...]

    @property
    def n_lat(self) -> int:
        return int(self.lat_centers.size)

    @property
    def n_lon(self) -> int:
        return int(self.lon_centers.size)

    @property
    def n_cells(self) -> int:
        return self.n_lat * self.n_lon

    def cell_index(self, lat_pos: int, lon_pos: int) -> int:
        """Return the stable row-major index of the cell at these positions."""
        if not 0 <= lat_pos < self.n_lat:
            raise IndexError(f"lat_pos {lat_pos} outside 0..{self.n_lat - 1}")
        if not 0 <= lon_pos < self.n_lon:
            raise IndexError(f"lon_pos {lon_pos} outside 0..{self.n_lon - 1}")
        return lat_pos * self.n_lon + lon_pos

    def cell_center(self, index: int) -> tuple[float, float]:
        """Return the ``(latitude, longitude)`` center of a cell by index."""
        if not 0 <= index < self.n_cells:
            raise IndexError(f"cell index {index} outside 0..{self.n_cells - 1}")
        lat_pos, lon_pos = divmod(index, self.n_lon)
        return float(self.lat_centers[lat_pos]), float(self.lon_centers[lon_pos])

    def assign(self, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
        """Map fine pixel centers to target-cell indices, ``-1`` when outside.

        Membership is decided by the pixel *center* falling inside a cell's
        complete edges. Cells are half-open ``[lower, upper)``, so a center
        exactly on a shared edge belongs to the upper cell. This rule is
        reproducible and order-independent; it does not fractionally clip
        pixels that straddle an edge, which is acceptable only because a fine
        pixel is a small fraction of a cell.
        """
        lon = np.asarray(lon, dtype=np.float64)
        lat = np.asarray(lat, dtype=np.float64)
        if lon.shape != lat.shape:
            raise ValueError(f"lon shape {lon.shape} != lat shape {lat.shape}")

        finite = np.isfinite(lon) & np.isfinite(lat)
        safe_lon = np.where(finite, lon, self.lon_edges[0] - 1.0)
        safe_lat = np.where(finite, lat, self.lat_edges[0] - 1.0)

        lon_pos = np.searchsorted(self.lon_edges, safe_lon, side="right") - 1
        lat_pos = np.searchsorted(self.lat_edges, safe_lat, side="right") - 1

        inside = (
            finite
            & (lon_pos >= 0)
            & (lon_pos < self.n_lon)
            & (lat_pos >= 0)
            & (lat_pos < self.n_lat)
        )
        flat = lat_pos * self.n_lon + lon_pos
        return np.where(inside, flat, -1).astype(np.int64)

    def validate_model_coordinates(self, lat: np.ndarray, lon: np.ndarray) -> None:
        """Raise if a model subset's coordinates are not this exact domain.

        Called on every decoded model granule. A silently shifted or reordered
        subset would corrupt every downstream statistic without any other symptom.
        """
        lat = np.asarray(lat, dtype=np.float64)
        lon = np.asarray(lon, dtype=np.float64)
        if lat.shape != self.lat_centers.shape or lon.shape != self.lon_centers.shape:
            raise ValueError(
                f"model subset shape {(lat.shape, lon.shape)} does not match target "
                f"grid shape {(self.lat_centers.shape, self.lon_centers.shape)}"
            )
        if not np.all(np.diff(lat) > 0):
            raise ValueError("model latitude axis is not strictly ascending")
        if not np.all(np.diff(lon) > 0):
            raise ValueError("model longitude axis is not strictly ascending")
        if not np.allclose(lat, self.lat_centers, atol=1e-6):
            raise ValueError(
                f"model latitude centers {lat} do not match target {self.lat_centers}"
            )
        if not np.allclose(lon, self.lon_centers, atol=1e-6):
            raise ValueError(
                f"model longitude centers {lon} do not match target {self.lon_centers}"
            )

    def cell_areas_m2(self) -> np.ndarray:
        """Return the spherical area of each cell, in square metres."""
        lat_bottom = np.radians(self.lat_edges[:-1])
        lat_top = np.radians(self.lat_edges[1:])
        lon_span = np.radians(np.diff(self.lon_edges))
        band = (
            MODIS_SPHERE_RADIUS_M**2 * (np.sin(lat_top) - np.sin(lat_bottom))
        )  # per radian of longitude
        return np.outer(band, lon_span).ravel()

    def expected_pixels_per_cell(self, fine_pixel_area_m2: float) -> np.ndarray:
        """Geometric count of equal-area fine pixels a complete cell can hold.

        This is a *static* expectation used to cross-check the mapping actually
        derived from tile geometry. Deriving support from the pixels present on
        a given day would make support 1.0 by construction and the threshold
        would never fire.
        """
        if fine_pixel_area_m2 <= 0:
            raise ValueError("fine_pixel_area_m2 must be positive")
        return self.cell_areas_m2() / float(fine_pixel_area_m2)


def build_target_grid(
    lon_min: float = -109.0,
    lon_max: float = -104.0,
    lat_min: float = 37.0,
    lat_max: float = 41.0,
) -> TargetGrid:
    """Select complete MERRA-2 cells whose centers lie within the bounds.

    Selection is by cell *center*, so the resulting complete cells extend up to
    half a cell beyond the requested bounds. Every selected cell is whole, which
    is what makes a single expected-support count valid for the whole domain.
    """
    all_lat = MERRA_LAT_ORIGIN + MERRA_LAT_STEP * np.arange(MERRA_N_LAT)
    all_lon = MERRA_LON_ORIGIN + MERRA_LON_STEP * np.arange(MERRA_N_LON)

    lat_indices = np.flatnonzero((all_lat >= lat_min) & (all_lat <= lat_max))
    lon_indices = np.flatnonzero((all_lon >= lon_min) & (all_lon <= lon_max))
    if lat_indices.size == 0 or lon_indices.size == 0:
        raise ValueError(
            f"no MERRA-2 cell centers inside lon {lon_min}..{lon_max}, "
            f"lat {lat_min}..{lat_max}"
        )

    lat_centers = all_lat[lat_indices]
    lon_centers = all_lon[lon_indices]
    lat_edges = np.concatenate(
        [lat_centers - MERRA_LAT_STEP / 2, [lat_centers[-1] + MERRA_LAT_STEP / 2]]
    )
    lon_edges = np.concatenate(
        [lon_centers - MERRA_LON_STEP / 2, [lon_centers[-1] + MERRA_LON_STEP / 2]]
    )
    cell_ids = tuple(
        f"j{int(j):03d}_i{int(i):03d}" for j in lat_indices for i in lon_indices
    )

    return TargetGrid(
        lat_centers=lat_centers,
        lon_centers=lon_centers,
        lat_indices=lat_indices,
        lon_indices=lon_indices,
        lat_edges=lat_edges,
        lon_edges=lon_edges,
        cell_ids=cell_ids,
    )
