"""MODIS sinusoidal grid geometry.

The reference product is distributed on the MODIS sinusoidal grid, which is
equal area. That single property is what lets the aggregation count pixels as
area weights and take a plain arithmetic mean - no latitude weighting anywhere.

Two conventions in this grid cause silent half-pixel and hemisphere errors, so
they are stated once here and asserted in tests: coordinate variables hold pixel
*centers*, and the y axis *descends* (row 0 is the northern edge of the tile).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from pyproj import CRS, Transformer

__all__ = [
    "GLOBAL_X_MAX",
    "MODIS_SINUSOIDAL_PROJ4",
    "MODIS_SPHERE_RADIUS_M",
    "TILE_SIZE_M",
    "TileBounds",
    "nominal_pixel_size_m",
    "sinusoidal_to_lonlat",
    "tile_bounds",
    "tile_coordinates",
    "tiles_covering",
]

#: Authalic sphere radius of the MODIS sinusoidal projection, in metres.
MODIS_SPHERE_RADIUS_M = 6371007.181

#: Proj4 definition carried by the reference granules' ``crs`` variable.
MODIS_SINUSOIDAL_PROJ4 = (
    "+proj=sinu +lon_0=0 +x_0=0 +y_0=0 "
    f"+a={MODIS_SPHERE_RADIUS_M} +b={MODIS_SPHERE_RADIUS_M} "
    "+units=m +no_defs +nadgrids=@null +wktext"
)

#: Half the global sinusoidal extent in x, i.e. the x of 180 degrees at the equator.
GLOBAL_X_MAX = MODIS_SPHERE_RADIUS_M * np.pi

#: Edge length of one 10-degree tile, in metres.
TILE_SIZE_M = GLOBAL_X_MAX / 18

_TILE_RE = re.compile(r"^h(\d{2})v(\d{2})$")
_N_H = 36
_N_V = 18

_TRANSFORMER = Transformer.from_crs(
    CRS.from_proj4(MODIS_SINUSOIDAL_PROJ4), CRS.from_epsg(4326), always_xy=True
)


@dataclass(frozen=True)
class TileBounds:
    """Projected extent of a tile, in sinusoidal metres."""

    x_min: float
    x_max: float
    y_min: float
    y_max: float


def nominal_pixel_size_m(grid_size: int) -> float:
    """Return the pixel edge length for a tile of ``grid_size`` pixels a side."""
    if grid_size <= 0:
        raise ValueError(f"grid_size must be positive, got {grid_size}")
    return TILE_SIZE_M / grid_size


def parse_tile(tile: str) -> tuple[int, int]:
    """Return the ``(h, v)`` indices of a tile name such as ``h09v04``."""
    match = _TILE_RE.match(tile)
    if match is None:
        raise ValueError(f"malformed MODIS tile name {tile!r}, expected e.g. 'h09v04'")
    h, v = int(match.group(1)), int(match.group(2))
    if not (0 <= h < _N_H and 0 <= v < _N_V):
        raise ValueError(f"tile {tile!r} outside the MODIS grid ({_N_H}x{_N_V})")
    return h, v


def tile_bounds(tile: str) -> TileBounds:
    """Return the projected bounds of ``tile``."""
    h, v = parse_tile(tile)
    x_min = -GLOBAL_X_MAX + h * TILE_SIZE_M
    y_max = GLOBAL_X_MAX / 2 - v * TILE_SIZE_M
    return TileBounds(
        x_min=x_min, x_max=x_min + TILE_SIZE_M, y_min=y_max - TILE_SIZE_M, y_max=y_max
    )


def tile_coordinates(tile: str, grid_size: int = 2400) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(x, y)`` pixel-center coordinates for ``tile``.

    ``x`` ascends west to east; ``y`` *descends*, matching the row order of the
    stored arrays where row 0 is the tile's northern edge. These are computed
    from tile algebra and are only a cross-check - production code reads the
    granule's own ``x`` and ``y`` variables, which are authoritative.
    """
    bounds = tile_bounds(tile)
    pixel = nominal_pixel_size_m(grid_size)
    half = pixel / 2
    x = bounds.x_min + half + pixel * np.arange(grid_size)
    y = bounds.y_max - half - pixel * np.arange(grid_size)
    return x, y


def sinusoidal_to_lonlat(
    x: np.ndarray, y: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Transform sinusoidal metres to longitude/latitude degrees."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if x.shape != y.shape:
        raise ValueError(f"x shape {x.shape} != y shape {y.shape}")
    lon, lat = _TRANSFORMER.transform(x, y)
    return np.asarray(lon), np.asarray(lat)


def tiles_covering(
    lon_min: float, lon_max: float, lat_min: float, lat_max: float
) -> tuple[str, ...]:
    """Return every tile whose extent intersects the geographic box.

    Includes tiles that clip only a corner. Callers must compare the result with
    what the archive actually publishes: a tile that is required here but absent
    upstream is a permanent coverage hole, not a transient gap.
    """
    if lon_min >= lon_max or lat_min >= lat_max:
        raise ValueError("bounds must be ordered min < max")

    # Sample the box boundary densely; sinusoidal x depends on latitude, so a
    # corner-only sample can miss a tile the box crosses in between.
    lons = np.linspace(lon_min, lon_max, 200)
    lats = np.linspace(lat_min, lat_max, 200)
    grid_lon, grid_lat = np.meshgrid(lons, lats)
    lat_rad = np.radians(grid_lat)
    x = MODIS_SPHERE_RADIUS_M * np.radians(grid_lon) * np.cos(lat_rad)
    y = MODIS_SPHERE_RADIUS_M * lat_rad

    h = np.floor((x + GLOBAL_X_MAX) / TILE_SIZE_M).astype(int)
    v = np.floor((GLOBAL_X_MAX / 2 - y) / TILE_SIZE_M).astype(int)
    pairs = sorted({(int(a), int(b)) for a, b in zip(h.ravel(), v.ravel())})
    return tuple(f"h{a:02d}v{b:02d}" for a, b in pairs)
