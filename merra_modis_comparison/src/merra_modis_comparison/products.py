from __future__ import annotations

import os
import random
import time
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import h5py
import numpy as np
from pyproj import CRS, Transformer

from .config import TargetGrid
from .grids import SpatialGrid


MODSCAG_ROOT = "ftp://sidads.colorado.edu/pub/DATASETS/STC_MODSCGDRF_HIST_v1"
MERRA_COLLECTION = "C1276812861-GES_DISC"
SINUSOIDAL_RADIUS = 6_371_007.181
SINUSOIDAL_CRS = CRS.from_proj4(
    f"+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +a={SINUSOIDAL_RADIUS} "
    f"+b={SINUSOIDAL_RADIUS} +units=m +no_defs"
)
TO_SINUSOIDAL = Transformer.from_crs("EPSG:4326", SINUSOIDAL_CRS, always_xy=True)
TO_GEOGRAPHIC = Transformer.from_crs(SINUSOIDAL_CRS, "EPSG:4326", always_xy=True)
MODIS_X_MIN = -20_015_109.355797417
MODIS_Y_MAX = 10_007_554.677898709
MODIS_TILE_SIZE = 1_111_950.519766523
MODIS_TILE_PIXELS = 2400
MODSCAG_ARCHIVE_TILES = frozenset(
    {"h08v04", "h08v05", "h09v04", "h09v05", "h10v04"}
)


class AuthenticationRequired(RuntimeError):
    pass


@dataclass(frozen=True)
class TileMapping:
    tile: str
    row_start: int
    row_stop: int
    col_start: int
    col_stop: int
    target_index: np.ndarray
    expected_counts: np.ndarray


def _projected_target_bounds(grid: SpatialGrid) -> tuple[float, float, float, float]:
    west, south, east, north = grid.geographic_bounds
    lons = np.linspace(west, east, 121)
    lats = np.linspace(south, north, 121)
    lon_mesh, lat_mesh = np.meshgrid(lons, lats)
    x, y = TO_SINUSOIDAL.transform(lon_mesh, lat_mesh)
    return float(x.min()), float(y.min()), float(x.max()), float(y.max())


def tiles_for_grid(grid: SpatialGrid) -> tuple[str, ...]:
    west, south, east, north = grid.geographic_bounds
    lons = np.linspace(west, east, 121)
    lats = np.linspace(south, north, 121)
    lon_mesh, lat_mesh = np.meshgrid(lons, lats)
    x, y = TO_SINUSOIDAL.transform(lon_mesh, lat_mesh)
    h = np.floor((x - MODIS_X_MIN) / MODIS_TILE_SIZE).astype(int)
    v = np.floor((MODIS_Y_MAX - y) / MODIS_TILE_SIZE).astype(int)
    pairs = sorted(
        (int(hh), int(vv))
        for hh, vv in set(zip(h.ravel(), v.ravel(), strict=True))
        if 0 <= hh <= 35 and 0 <= vv <= 17
    )
    return tuple(f"h{hh:02d}v{vv:02d}" for hh, vv in pairs)


def archived_tiles_for_grid(grid: SpatialGrid) -> tuple[str, ...]:
    return tuple(tile for tile in tiles_for_grid(grid) if tile in MODSCAG_ARCHIVE_TILES)


def modscag_filename(tile: str, day: date) -> str:
    return f"STC_MODSCGDRF_HIST_{tile}_{day:%Y%m%d}_v01.0.nc"


def modscag_url(tile: str, day: date) -> str:
    return f"{MODSCAG_ROOT}/{tile}/{day:%Y}/{modscag_filename(tile, day)}"


def download_modscag(
    tile: str, day: date, directory: Path, retries: int = 4
) -> Path:
    destination = directory / modscag_filename(tile, day)
    request = urllib.request.Request(
        modscag_url(tile, day), headers={"User-Agent": "merra-modis-fsca/0.1"}
    )
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                with destination.open("wb") as output:
                    while block := response.read(1024 * 1024):
                        output.write(block)
            if destination.stat().st_size < 1024:
                raise OSError(f"implausibly small MODSCAG granule: {destination}")
            return destination
        except Exception as exc:  # network errors vary by urllib backend
            last_error = exc
            destination.unlink(missing_ok=True)
            if attempt + 1 < retries:
                connection_limited = "421 Too many connections" in str(exc)
                if connection_limited:
                    delay = min(5 * 2**attempt, 40) + random.uniform(0, 1)
                    print(
                        "MODSCAG archive connection limit reached; "
                        f"retrying {tile} {day.isoformat()} in {delay:.1f}s",
                        flush=True,
                    )
                else:
                    delay = min(2**attempt, 8)
                time.sleep(delay)
    raise RuntimeError(
        f"failed to download {tile} for {day.isoformat()} after {retries} attempts"
    ) from last_error


def _tile_coordinates(tile: str) -> tuple[np.ndarray, np.ndarray]:
    h = int(tile[1:3])
    v = int(tile[4:6])
    pixel = MODIS_TILE_SIZE / MODIS_TILE_PIXELS
    x0 = MODIS_X_MIN + h * MODIS_TILE_SIZE
    y0 = MODIS_Y_MAX - v * MODIS_TILE_SIZE
    x = x0 + (np.arange(MODIS_TILE_PIXELS, dtype=np.float64) + 0.5) * pixel
    y = y0 - (np.arange(MODIS_TILE_PIXELS, dtype=np.float64) + 0.5) * pixel
    return x, y


def build_tile_mapping(
    path: Path | None, tile: str, grid: SpatialGrid
) -> TileMapping:
    xmin, ymin, xmax, ymax = _projected_target_bounds(grid)
    expected_x, expected_y = _tile_coordinates(tile)
    if path is None:
        x, y = expected_x, expected_y
    else:
        with h5py.File(path, "r") as dataset:
            x = np.asarray(dataset["x"][:], dtype=np.float64)
            y = np.asarray(dataset["y"][:], dtype=np.float64)
            if dataset["snow_fraction"].shape != (1, y.size, x.size):
                raise ValueError(f"unexpected snow_fraction shape in {path.name}")
            if dataset["days_without_observation"].shape != (1, y.size, x.size):
                raise ValueError(
                    f"unexpected days_without_observation shape in {path.name}"
                )
        if not np.allclose(x, expected_x, atol=1e-5) or not np.allclose(
            y, expected_y, atol=1e-5
        ):
            raise ValueError(f"unexpected MODIS sinusoidal coordinates in {path.name}")
    pixel = max(abs(float(np.median(np.diff(x)))), abs(float(np.median(np.diff(y)))))
    cols = np.flatnonzero((x >= xmin - pixel) & (x <= xmax + pixel))
    rows = np.flatnonzero((y >= ymin - pixel) & (y <= ymax + pixel))
    if cols.size == 0 or rows.size == 0:
        raise ValueError(f"tile {tile} does not intersect target grid")
    col_start, col_stop = int(cols[0]), int(cols[-1] + 1)
    row_start, row_stop = int(rows[0]), int(rows[-1] + 1)
    xx, yy = np.meshgrid(x[col_start:col_stop], y[row_start:row_stop])
    lon, lat = TO_GEOGRAPHIC.transform(xx, yy)
    target_index = grid.assign_points(lon, lat)
    expected = np.bincount(
        target_index[target_index >= 0], minlength=grid.size
    ).astype(np.int64)
    return TileMapping(
        tile=tile,
        row_start=row_start,
        row_stop=row_stop,
        col_start=col_start,
        col_stop=col_stop,
        target_index=target_index,
        expected_counts=expected,
    )


def aggregate_modscag(
    paths: dict[str, Path], mappings: dict[str, TileMapping], grid: SpatialGrid
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    sums = np.zeros(grid.size, dtype=np.float64)
    counts = np.zeros(grid.size, dtype=np.int64)
    observed = np.zeros(grid.size, dtype=np.int64)
    expected = sum(
        (mapping.expected_counts for mapping in mappings.values()),
        start=np.zeros(grid.size, dtype=np.int64),
    )
    for tile in sorted(paths):
        mapping = mappings[tile]
        with h5py.File(paths[tile], "r") as dataset:
            rows = slice(mapping.row_start, mapping.row_stop)
            cols = slice(mapping.col_start, mapping.col_stop)
            snow = np.asarray(dataset["snow_fraction"][0, rows, cols])
            days_without = np.asarray(dataset["days_without_observation"][0, rows, cols])
        target = mapping.target_index
        valid = (target >= 0) & (snow <= 100)
        valid_target = target[valid]
        counts += np.bincount(valid_target, minlength=grid.size).astype(np.int64)
        sums += np.bincount(
            valid_target, weights=snow[valid].astype(np.float64) / 100.0,
            minlength=grid.size,
        )
        directly_observed = valid & (days_without == 0)
        observed += np.bincount(
            target[directly_observed], minlength=grid.size
        ).astype(np.int64)
    fractions = np.full(grid.size, np.nan, dtype=np.float64)
    np.divide(sums, counts, out=fractions, where=counts > 0)
    return (
        fractions.reshape(grid.shape),
        counts.reshape(grid.shape),
        expected.reshape(grid.shape),
        observed.reshape(grid.shape),
    )


def merra_stream_for_date(day: date) -> int:
    """Return the NASA production-stream identifier used in the granule name."""
    if day.year <= 1991:
        return 100
    if day.year <= 2000:
        return 200
    if day.year <= 2010:
        return 300
    # NASA reprocessed these five months and changed their filename prefix from
    # the routine stream 400 to 401. The collection/version and science variable
    # remain M2T1NXLND 5.12.4 FRSNO.
    if (day.year, day.month) == (2020, 9) or (
        day.year == 2021 and 6 <= day.month <= 9
    ):
        return 401
    return 400


def merra_opendap_url(day: date) -> str:
    stream = merra_stream_for_date(day)
    granule = f"MERRA2_{stream}.tavg1_2d_lnd_Nx.{day:%Y%m%d}.nc4"
    encoded_id = f"M2T1NXLND.5.12.4%3A{granule}"
    return (
        "https://opendap.earthdata.nasa.gov/collections/"
        f"{MERRA_COLLECTION}/granules/{encoded_id}"
    )


def authenticated_earthdata_session() -> Any:
    try:
        import earthaccess
    except ImportError as exc:
        raise AuthenticationRequired(
            "earthaccess is required; install the project dependencies first"
        ) from exc
    has_token = bool(os.environ.get("EARTHDATA_TOKEN"))
    has_pair = bool(os.environ.get("EARTHDATA_USERNAME")) and bool(
        os.environ.get("EARTHDATA_PASSWORD")
    )
    netrc_path = Path(os.environ.get("NETRC", Path.home() / ".netrc"))
    if has_token or has_pair:
        strategy = "environment"
    elif netrc_path.exists():
        strategy = "netrc"
    else:
        raise AuthenticationRequired(
            "NASA Earthdata authentication is required. Configure ~/.netrc or "
            "set EARTHDATA_TOKEN in the shell; credentials are never passed to "
            "this program as command-line arguments."
        )
    try:
        auth = earthaccess.login(strategy=strategy, persist=False)
        return auth.get_session()
    except Exception as exc:
        raise AuthenticationRequired(
            "NASA Earthdata authentication failed; check the configured token "
            "or ~/.netrc credentials and GES DISC authorization."
        ) from exc


def _dataset_variable(dataset: Any, name: str) -> Any:
    if name in dataset:
        return dataset[name]
    lookup = {str(key).upper(): key for key in dataset.keys()}
    if name.upper() not in lookup:
        raise KeyError(f"remote MERRA-2 dataset lacks {name}")
    return dataset[lookup[name.upper()]]


def read_merra_frsno(
    day: date,
    grid: TargetGrid,
    session: Any,
    retries: int = 4,
    validate_coordinates: bool = False,
) -> np.ndarray:
    try:
        from pydap.client import open_url
    except ImportError as exc:
        raise RuntimeError("pydap>=3.5.5 is required for MERRA-2 DAP4 subsets") from exc
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            dataset = open_url(
                merra_opendap_url(day), session=session, protocol="dap4", timeout=120
            )
            variable = _dataset_variable(dataset, "FRSNO")
            subset = variable[
                15,
                grid.lat_slice.start : grid.lat_slice.stop,
                grid.lon_slice.start : grid.lon_slice.stop,
            ]
            data = getattr(subset, "data", subset)
            array = np.asarray(data, dtype=np.float64).squeeze()
            if array.shape != grid.shape:
                raise ValueError(
                    f"unexpected MERRA-2 subset shape {array.shape}; expected {grid.shape}"
                )
            array[(array < 0) | (array > 1) | (array > 1e10)] = np.nan
            if validate_coordinates:
                remote_lats = np.asarray(
                    getattr(_dataset_variable(dataset, "lat")[grid.lat_slice], "data", _dataset_variable(dataset, "lat")[grid.lat_slice])
                ).squeeze()
                remote_lons = np.asarray(
                    getattr(_dataset_variable(dataset, "lon")[grid.lon_slice], "data", _dataset_variable(dataset, "lon")[grid.lon_slice])
                ).squeeze()
                if not np.allclose(remote_lats, grid.lats) or not np.allclose(
                    remote_lons, grid.lons
                ):
                    raise ValueError("remote MERRA-2 coordinates do not match target grid")
            return array
        except Exception as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(min(2**attempt, 8))
    raise RuntimeError(
        f"failed to read MERRA-2 FRSNO for {day.isoformat()} after {retries} attempts"
    ) from last_error
