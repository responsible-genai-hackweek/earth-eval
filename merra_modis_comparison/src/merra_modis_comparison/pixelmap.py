"""The static fine-pixel to target-cell mapping, and the support denominator.

Two things live here, and keeping them separate is the whole point.

``global_expected_counts`` answers "how many fine pixel centers does a complete
cell contain?" purely from grid geometry, with no reference to which tiles are
configured. It is the denominator of the support fraction. Deriving it from the
tiles actually fetched would make support 1.0 by construction and the 80%
threshold could never fire.

``coverage_report`` answers "how many of those pixels can the configured tiles
actually deliver?" The difference between the two is a permanent coverage hole,
which is a different failure from a cloudy day and must not be allowed to hide
inside the support fraction.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .errors import DomainCoverageError
from .grid import TargetGrid
from .modis import (
    GLOBAL_X_MAX,
    MODIS_SPHERE_RADIUS_M,
    TILE_SIZE_M,
    nominal_pixel_size_m,
    tiles_covering,
)

__all__ = [
    "CoverageReport",
    "TileWindow",
    "assert_coverage",
    "build_tile_window",
    "coverage_report",
    "global_expected_counts",
    "reduce_tile",
]

GLOBAL_Y_MAX = GLOBAL_X_MAX / 2.0

#: A cell below this fraction of its geometric support is reported as deficient.
COVERAGE_TOLERANCE = 0.999


@dataclass(frozen=True)
class CoverageReport:
    """What the configured tiles can deliver, against what a complete cell holds."""

    expected: np.ndarray
    available: np.ndarray
    fraction: np.ndarray
    deficient: tuple[int, ...]
    cell_ids: tuple[str, ...]
    required_tiles: tuple[str, ...]
    configured_tiles: tuple[str, ...]
    missing_tiles: tuple[str, ...]


@dataclass(frozen=True)
class TileWindow:
    """The crop of one tile that intersects the domain, and its cell mapping.

    ``cell_index`` is a 2-D array shaped like the cropped granule block, holding
    the target-cell index of each fine pixel or ``-1`` when it falls outside the
    domain. It is static for a whole run and is built once per worker.
    """

    tile: str
    row_start: int
    row_stop: int
    col_start: int
    col_stop: int
    cell_index: np.ndarray

    @property
    def is_empty(self) -> bool:
        return self.cell_index.size == 0

    @property
    def shape(self) -> tuple[int, int]:
        return (self.row_stop - self.row_start, self.col_stop - self.col_start)


def _global_pixel_rows(grid: TargetGrid, pixel: float) -> tuple[np.ndarray, np.ndarray]:
    """Return global row indices and their latitudes covering the domain."""
    y_lo = MODIS_SPHERE_RADIUS_M * np.radians(grid.lat_edges[0])
    y_hi = MODIS_SPHERE_RADIUS_M * np.radians(grid.lat_edges[-1])
    first = int(np.floor((GLOBAL_Y_MAX - y_hi) / pixel)) - 1
    last = int(np.ceil((GLOBAL_Y_MAX - y_lo) / pixel)) + 1
    rows = np.arange(first, last + 1)
    lat = np.degrees((GLOBAL_Y_MAX - (rows + 0.5) * pixel) / MODIS_SPHERE_RADIUS_M)
    keep = (lat >= grid.lat_edges[0]) & (lat < grid.lat_edges[-1])
    return rows[keep], lat[keep]


def _row_columns(
    grid: TargetGrid, lat: float, pixel: float
) -> tuple[np.ndarray, np.ndarray]:
    """Return global column indices and longitudes inside the domain at one row."""
    cos_phi = np.cos(np.radians(lat))
    x_west = MODIS_SPHERE_RADIUS_M * np.radians(grid.lon_edges[0]) * cos_phi
    x_east = MODIS_SPHERE_RADIUS_M * np.radians(grid.lon_edges[-1]) * cos_phi
    first = int(np.floor((x_west + GLOBAL_X_MAX) / pixel)) - 1
    last = int(np.ceil((x_east + GLOBAL_X_MAX) / pixel)) + 1
    cols = np.arange(first, last + 1)
    x = -GLOBAL_X_MAX + (cols + 0.5) * pixel
    lon = np.degrees(x / (MODIS_SPHERE_RADIUS_M * cos_phi))
    keep = (lon >= grid.lon_edges[0]) & (lon < grid.lon_edges[-1])
    return cols[keep], lon[keep]


def _accumulate(grid: TargetGrid, grid_size: int) -> tuple[np.ndarray, dict]:
    """Count domain pixel centers per cell, globally and per originating tile."""
    pixel = nominal_pixel_size_m(grid_size)
    expected = np.zeros(grid.n_cells, dtype=np.int64)
    per_tile: dict[str, np.ndarray] = {}

    rows, lats = _global_pixel_rows(grid, pixel)
    for row, lat in zip(rows, lats):
        cols, lon = _row_columns(grid, float(lat), pixel)
        if lon.size == 0:
            continue
        cells = grid.assign(lon, np.full(lon.shape, lat))
        inside = cells >= 0
        if not np.any(inside):
            continue
        cells = cells[inside]
        np.add.at(expected, cells, 1)

        x = -GLOBAL_X_MAX + (cols[inside] + 0.5) * pixel
        y = GLOBAL_Y_MAX - (row + 0.5) * pixel
        h = np.floor((x + GLOBAL_X_MAX) / TILE_SIZE_M).astype(int)
        v = int(np.floor((GLOBAL_Y_MAX - y) / TILE_SIZE_M))
        for h_value in np.unique(h):
            tile = f"h{int(h_value):02d}v{v:02d}"
            bucket = per_tile.setdefault(tile, np.zeros(grid.n_cells, dtype=np.int64))
            np.add.at(bucket, cells[h == h_value], 1)
    return expected, per_tile


def global_expected_counts(grid: TargetGrid, grid_size: int = 2400) -> np.ndarray:
    """Fine pixel centers a complete cell contains, from global grid geometry.

    Independent of which tiles are configured or available. This is the support
    denominator of record.
    """
    return _cached(grid, grid_size)[0].copy()


def coverage_report(
    grid: TargetGrid, tiles: tuple[str, ...], grid_size: int = 2400
) -> CoverageReport:
    """Compare what ``tiles`` can deliver against the geometric expectation."""
    expected, per_tile = _cached(grid, grid_size)
    available = np.zeros(grid.n_cells, dtype=np.int64)
    for tile in tiles:
        if tile in per_tile:
            available += per_tile[tile]

    fraction = np.where(expected > 0, available / np.maximum(expected, 1), np.nan)
    deficient = tuple(int(i) for i in np.flatnonzero(fraction < COVERAGE_TOLERANCE))
    required = tiles_covering(
        grid.lon_edges[0], grid.lon_edges[-1], grid.lat_edges[0], grid.lat_edges[-1]
    )
    missing = tuple(t for t in required if t not in tiles and t in per_tile)
    return CoverageReport(
        expected=expected.copy(),
        available=available,
        fraction=fraction,
        deficient=deficient,
        cell_ids=grid.cell_ids,
        required_tiles=required,
        configured_tiles=tuple(tiles),
        missing_tiles=missing,
    )


def assert_coverage(report: CoverageReport, *, accept_deficit: bool = False) -> None:
    """Refuse a tile set that cannot fully cover every target cell.

    An under-covered cell is dangerous precisely because it is *not* obviously
    broken: it can sit above the support threshold every clear day while its
    reference mean is drawn from only part of its area.
    """
    if not report.deficient:
        return
    detail = ", ".join(
        f"{report.cell_ids[i]} (slot {i}: {report.available[i]}/{report.expected[i]} = "
        f"{report.fraction[i]:.6f})"
        for i in report.deficient
    )
    message = (
        f"configured tiles {report.configured_tiles} do not cover "
        f"{len(report.deficient)} cell(s): {detail}; missing tiles "
        f"{report.missing_tiles or 'none published'}"
    )
    if not accept_deficit:
        raise DomainCoverageError(message)


def build_tile_window(
    tile: str, grid: TargetGrid, x: np.ndarray, y: np.ndarray
) -> TileWindow:
    """Build the static pixel-to-cell mapping for one tile's domain crop.

    ``x`` and ``y`` are the granule's own pixel-center coordinate variables:
    ``x`` ascending, ``y`` descending. Cropping happens in projected coordinates
    before any transform, so only the pixels that can matter are ever converted.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)

    lat_lo, lat_hi = float(grid.lat_edges[0]), float(grid.lat_edges[-1])
    lon_lo, lon_hi = float(grid.lon_edges[0]), float(grid.lon_edges[-1])
    y_lo = MODIS_SPHERE_RADIUS_M * np.radians(lat_lo)
    y_hi = MODIS_SPHERE_RADIUS_M * np.radians(lat_hi)

    cosines = np.cos(np.radians([lat_lo, lat_hi]))
    x_candidates = [
        MODIS_SPHERE_RADIUS_M * np.radians(lon) * cos
        for lon in (lon_lo, lon_hi)
        for cos in cosines
    ]
    x_lo, x_hi = min(x_candidates), max(x_candidates)

    rows = np.flatnonzero((y >= y_lo) & (y <= y_hi))
    cols = np.flatnonzero((x >= x_lo) & (x <= x_hi))
    if rows.size == 0 or cols.size == 0:
        return TileWindow(tile, 0, 0, 0, 0, np.empty((0, 0), dtype=np.int64))

    row_start, row_stop = int(rows[0]), int(rows[-1]) + 1
    col_start, col_stop = int(cols[0]), int(cols[-1]) + 1

    grid_x, grid_y = np.meshgrid(x[col_start:col_stop], y[row_start:row_stop])
    lat = np.degrees(grid_y / MODIS_SPHERE_RADIUS_M)
    lon = np.degrees(grid_x / (MODIS_SPHERE_RADIUS_M * np.cos(np.radians(lat))))
    cell_index = grid.assign(lon.ravel(), lat.ravel()).reshape(lat.shape)

    return TileWindow(
        tile=tile,
        row_start=row_start,
        row_stop=row_stop,
        col_start=col_start,
        col_stop=col_stop,
        cell_index=cell_index,
    )


def reduce_tile(
    values: np.ndarray, valid: np.ndarray, window: TileWindow, n_cells: int
) -> tuple[np.ndarray, np.ndarray]:
    """Sum valid fine values into target cells and count the contributors.

    Invalid pixels contribute to neither the sum nor the count. Fill is a screen,
    not an observation of zero snow, so counting it would bias the cell mean low
    exactly where the retrieval had nothing to say.
    """
    if values.shape != window.cell_index.shape:
        raise ValueError(
            f"values shape {values.shape} does not match window {window.cell_index.shape}"
        )
    if valid.shape != values.shape:
        raise ValueError(f"valid shape {valid.shape} does not match values {values.shape}")

    cells = window.cell_index.ravel()
    usable = (cells >= 0) & valid.ravel() & np.isfinite(values.ravel())
    picked = cells[usable]
    sums = np.bincount(picked, weights=values.ravel()[usable], minlength=n_cells)
    counts = np.bincount(picked, minlength=n_cells)
    return sums[:n_cells], counts[:n_cells].astype(np.int64)


_CACHE: dict[tuple, tuple[np.ndarray, dict]] = {}


def _cached(grid: TargetGrid, grid_size: int) -> tuple[np.ndarray, dict]:
    key = (grid.cell_ids, grid_size)
    if key not in _CACHE:
        _CACHE[key] = _accumulate(grid, grid_size)
    return _CACHE[key]
