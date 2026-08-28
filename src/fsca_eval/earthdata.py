"""Earthdata authentication, MERRA-2/MODSCAG download, and FTP concurrency control.

Both `RealTransport.fetch_merra_subset` and `RealTransport.fetch_modscag_tiles`
are implemented and have been exercised against real archives:
MERRA-2 via a plain authenticated HTTPS GET against GES DISC (in-memory
h5netcdf decode, no OPeNDAP/cloud dependency); MODSCAG via anonymous FTP
against `sidads.colorado.edu` (no Earthdata login required for this archive),
downloading each granule to a caller-owned temporary directory, decoding only
the domain-relevant pixel crop, and deleting the granule immediately. The
retry/backoff/session-concurrency logic is fully unit-tested with an injected
fake transport (see tests/test_earthdata.py).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date
from typing import Callable, Protocol

import numpy as np

from . import config


class TransientFetchError(Exception):
    """Retryable failure: FTP 421 (too many connections), transient network error."""


class FatalFetchError(Exception):
    """Non-retryable failure: auth failure, corrupt/unexpected data, contract
    mismatch. Must propagate loudly -- never swallowed by requeue logic.
    """


@dataclass(frozen=True)
class MerraSubset:
    """MERRA-2 FRSNO at time index 15, already subset to the 72-cell domain."""

    frsno: np.ndarray  # shape (N_LAT_CELLS, N_LON_CELLS), fraction 0-1
    lon_centers: np.ndarray  # shape (N_LON_CELLS,)
    lat_centers: np.ndarray  # shape (N_LAT_CELLS,)
    stream: int


@dataclass(frozen=True)
class ModscagTile:
    """One MODSCAG granule's pixel-center geometry and values."""

    pixel_x_sinusoidal: np.ndarray  # flattened, meters
    pixel_y_sinusoidal: np.ndarray  # flattened, meters
    snow_fraction: np.ndarray  # flattened, 0-100(+) percent
    days_without_observation: np.ndarray  # flattened


class Transport(Protocol):
    def fetch_merra_subset(self, d: date, stream: int) -> MerraSubset: ...

    def fetch_modscag_tiles(self, d: date, tmp_dir: str) -> list[ModscagTile]: ...


def with_backoff(
    fn: Callable[[], object],
    *,
    backoffs: tuple[int, ...] = config.FTP_BACKOFF_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> object:
    """Call `fn()`, retrying on TransientFetchError with staggered backoff.

    Total attempts = len(backoffs) + 1. FatalFetchError is never retried and
    propagates immediately. If all retries are exhausted, the last
    TransientFetchError propagates.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except FatalFetchError:
            raise
        except TransientFetchError:
            if attempt >= len(backoffs):
                raise
            sleep(backoffs[attempt])
            attempt += 1


class FtpSlotPool:
    """Bounded semaphore around MODSCAG FTP downloads.

    The archive rejects 10 simultaneous connections from one IP; the
    operational plan fixes this at 8 slots regardless of worker count so it
    never needs to track the CPU count.
    """

    def __init__(self, slots: int = config.FTP_SEMAPHORE_SLOTS):
        self._semaphore = threading.Semaphore(slots)

    def __enter__(self) -> "FtpSlotPool":
        self._semaphore.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._semaphore.release()


@dataclass
class MonthRequeueQueue:
    """FIFO of (year, month) month-tasks with failed tasks pushed to the back."""

    _pending: list[tuple[int, int]]

    def __init__(self, months: list[tuple[int, int]]):
        self._pending = list(months)

    def pop(self) -> tuple[int, int] | None:
        return self._pending.pop(0) if self._pending else None

    def requeue_to_back(self, month: tuple[int, int]) -> None:
        self._pending.append(month)

    def __len__(self) -> int:
        return len(self._pending)


def create_session(login_fn: Callable[[], object] | None = None):
    """One authenticated Earthdata session per worker process.

    `login_fn` defaults to `earthaccess.login`, invoked once per worker (see
    pipeline.py's ProcessPoolExecutor initializer). Raises FatalFetchError on
    authentication failure -- an auth failure is a configuration problem, not
    a transient network hiccup, and must not be retried or requeued silently.
    """
    if login_fn is None:
        import earthaccess

        login_fn = earthaccess.login

    try:
        return login_fn()
    except Exception as exc:  # noqa: BLE001 - re-raised as a typed fatal error
        raise FatalFetchError(f"Earthdata authentication failed: {exc}") from exc


MERRA_GLOBAL_LON_MIN = -180.0  # global M2T1NXLND grid origin, west edge center
MERRA_GLOBAL_LAT_MIN = -90.0  # global M2T1NXLND grid origin, south edge center

MERRA_URL_TEMPLATE = (
    "https://data.gesdisc.earthdata.nasa.gov/data/MERRA2/{collection}.{version}/"
    "{year:04d}/{month:02d}/MERRA2_{stream}.tavg1_2d_lnd_Nx.{ymd}.nc4"
)


def merra_granule_url(d: date, stream: int) -> str:
    return MERRA_URL_TEMPLATE.format(
        collection=config.MERRA_COLLECTION,
        version=config.MERRA_VERSION,
        year=d.year,
        month=d.month,
        stream=stream,
        ymd=d.strftime("%Y%m%d"),
    )


def merra_domain_index_ranges() -> tuple[slice, slice]:
    """Integer (lon, lat) index ranges into the global MERRA-2 grid for the
    fixed 72-cell domain.

    The domain's cell centers already sit exactly on the global 0.625x0.5
    degree grid, so this is pure index slicing -- never interpolation.
    """
    lon_start = round((config.CELL_LON_CENTERS[0] - MERRA_GLOBAL_LON_MIN) / config.LON_SPACING)
    lat_start = round((config.CELL_LAT_CENTERS[0] - MERRA_GLOBAL_LAT_MIN) / config.LAT_SPACING)
    lon_slice = slice(lon_start, lon_start + config.N_LON_CELLS)
    lat_slice = slice(lat_start, lat_start + config.N_LAT_CELLS)
    return lon_slice, lat_slice


# --- STC-MODSCAG (anonymous FTP, no Earthdata login required) --------------

MODSCAG_FTP_HOST = "sidads.colorado.edu"
MODSCAG_FTP_BASE_PATH = "/pub/DATASETS/STC_MODSCGDRF_HIST_v1"

# The 5 tiles archived for this product; only the ones intersecting our
# domain are ever fetched (see `modscag_domain_tiles`).
MODSCAG_ARCHIVE_TILES = ("h08v04", "h08v05", "h09v04", "h09v05", "h10v04")

# Standard global MODIS sinusoidal grid constants (sphere radius 6371007.181 m,
# matching regrid.MODIS_SINUSOIDAL_PROJ4). Confirmed against a real granule's
# own GeoTransform/crs metadata.
MODSCAG_SINUSOIDAL_X_MIN = -20_015_109.355797417
MODSCAG_SINUSOIDAL_Y_MAX = 10_007_554.677898709
MODSCAG_TILE_SIZE_M = 1_111_950.519766523
MODSCAG_TILE_PIXELS = 2400

_MODSCAG_DOMAIN_CROP_CACHE: dict[str, tuple[slice, slice] | None] = {}


def modscag_remote_path(tile: str, d: date) -> str:
    return (
        f"{MODSCAG_FTP_BASE_PATH}/{tile}/{d.year:04d}/"
        f"STC_MODSCGDRF_HIST_{tile}_{d.strftime('%Y%m%d')}_v01.0.nc"
    )


def _modscag_tile_pixel_centers(tile: str) -> tuple[np.ndarray, np.ndarray]:
    """Full 2400-length (x, y) pixel-center coordinate arrays for one tile,
    in meters, reconstructed purely from its h/v index -- no network needed.
    """
    h, v = int(tile[1:3]), int(tile[4:6])
    x0 = MODSCAG_SINUSOIDAL_X_MIN + h * MODSCAG_TILE_SIZE_M
    y0 = MODSCAG_SINUSOIDAL_Y_MAX - v * MODSCAG_TILE_SIZE_M
    pixel = MODSCAG_TILE_SIZE_M / MODSCAG_TILE_PIXELS
    x = x0 + (np.arange(MODSCAG_TILE_PIXELS) + 0.5) * pixel
    y = y0 - (np.arange(MODSCAG_TILE_PIXELS) + 0.5) * pixel
    return x, y


def modscag_domain_crop(tile: str) -> tuple[slice, slice] | None:
    """Row/col crop range (into the tile's native 2400x2400 grid) covering the
    configured domain, with a 2-pixel buffer, or None if the tile does not
    intersect the domain at all.

    Pure geometry -- the result depends only on `tile` and the fixed domain
    edges, never on the date, so every day fetches the identical pixel set
    for a given tile (required so the static `regrid.PixelCellMapping` built
    once at worker startup stays valid for every subsequent day).
    """
    if tile in _MODSCAG_DOMAIN_CROP_CACHE:
        return _MODSCAG_DOMAIN_CROP_CACHE[tile]

    from . import regrid

    x, y = _modscag_tile_pixel_centers(tile)
    xx, yy = np.meshgrid(x, y)
    lon, lat = regrid.transform_sinusoidal_to_lonlat(xx.ravel(), yy.ravel())
    lon = lon.reshape(xx.shape)
    lat = lat.reshape(xx.shape)
    inside = (
        (lon >= config.DOMAIN_LON_EDGE_MIN)
        & (lon <= config.DOMAIN_LON_EDGE_MAX)
        & (lat >= config.DOMAIN_LAT_EDGE_MIN)
        & (lat <= config.DOMAIN_LAT_EDGE_MAX)
    )
    if not inside.any():
        _MODSCAG_DOMAIN_CROP_CACHE[tile] = None
        return None

    rows = np.flatnonzero(inside.any(axis=1))
    cols = np.flatnonzero(inside.any(axis=0))
    buffer = 2
    row_slice = slice(max(0, int(rows[0]) - buffer), min(MODSCAG_TILE_PIXELS, int(rows[-1]) + 1 + buffer))
    col_slice = slice(max(0, int(cols[0]) - buffer), min(MODSCAG_TILE_PIXELS, int(cols[-1]) + 1 + buffer))
    result = (row_slice, col_slice)
    _MODSCAG_DOMAIN_CROP_CACHE[tile] = result
    return result


def modscag_domain_tiles() -> tuple[str, ...]:
    """The archived tiles intersecting the configured domain, sorted for a
    stable fetch/concatenation order across every call.
    """
    return tuple(sorted(t for t in MODSCAG_ARCHIVE_TILES if modscag_domain_crop(t) is not None))


def _default_modscag_ftp_factory():
    from ftplib import FTP

    ftp = FTP(MODSCAG_FTP_HOST, timeout=120)
    ftp.login()  # anonymous
    return ftp


class RealTransport:
    """Live MERRA-2/MODSCAG transport. `session` is whatever `create_session()`
    returned -- typically an `earthaccess` Auth object; an authenticated
    `requests.Session` is obtained from it lazily via `.get_session()`.

    `ftp_factory` returns a connected, logged-in FTP client (ftplib.FTP-like:
    needs `.retrbinary(cmd, callback)` and `.quit()`); defaults to a real
    anonymous connection to the MODSCAG archive. Injectable for tests.
    """

    def __init__(self, session, ftp_pool: FtpSlotPool, ftp_factory: Callable[[], object] | None = None):
        self._session = session
        self._ftp_pool = ftp_pool
        self._ftp_factory = ftp_factory or _default_modscag_ftp_factory

    def _http_session(self):
        session = self._session
        if hasattr(session, "get_session"):
            return session.get_session()
        return session

    def fetch_merra_subset(self, d: date, stream: int) -> MerraSubset:
        import io

        import requests
        import xarray as xr

        url = merra_granule_url(d, stream)
        try:
            response = self._http_session().get(url, timeout=120)
        except requests.exceptions.RequestException as exc:
            raise TransientFetchError(f"MERRA-2 request failed for {url}: {exc}") from exc

        if response.status_code in (401, 403):
            raise FatalFetchError(
                f"MERRA-2 request unauthorized ({response.status_code}) for {url}: "
                f"{response.text[:500]}"
            )
        if response.status_code >= 500:
            raise TransientFetchError(f"MERRA-2 server error {response.status_code} for {url}")
        if response.status_code != 200:
            raise FatalFetchError(
                f"MERRA-2 request failed ({response.status_code}) for {url}: {response.text[:500]}"
            )

        lon_slice, lat_slice = merra_domain_index_ranges()
        try:
            with xr.open_dataset(io.BytesIO(response.content), engine="h5netcdf") as ds:
                subset = ds[config.MERRA_VARIABLE].isel(
                    time=config.MERRA_TIME_INDEX, lon=lon_slice, lat=lat_slice
                )
                frsno = subset.values.astype(np.float64)
                lon_centers = subset["lon"].values.astype(np.float64)
                lat_centers = subset["lat"].values.astype(np.float64)
        except Exception as exc:
            raise FatalFetchError(f"Failed to decode MERRA-2 granule {url}: {exc}") from exc

        if not np.allclose(lon_centers, config.CELL_LON_CENTERS, atol=1e-6) or not np.allclose(
            lat_centers, config.CELL_LAT_CENTERS, atol=1e-6
        ):
            raise FatalFetchError(
                f"MERRA-2 subset coordinates for {url} do not match the configured "
                f"domain (lon={lon_centers.tolist()}, lat={lat_centers.tolist()})"
            )

        if not np.all(np.isfinite(frsno)) or np.any((frsno < -1e-6) | (frsno > 1 + 1e-6)):
            raise FatalFetchError(
                f"MERRA-2 FRSNO values out of expected [0, 1] range for {url}: "
                f"min={np.nanmin(frsno)} max={np.nanmax(frsno)}"
            )

        return MerraSubset(
            frsno=frsno,
            lon_centers=np.array(config.CELL_LON_CENTERS),
            lat_centers=np.array(config.CELL_LAT_CENTERS),
            stream=stream,
        )

    def fetch_modscag_tiles(self, d: date, tmp_dir: str) -> list[ModscagTile]:
        tiles = modscag_domain_tiles()
        if not tiles:
            raise FatalFetchError("No archived MODSCAG tile intersects the configured domain")
        return [self._fetch_one_modscag_tile(tile, d, tmp_dir) for tile in tiles]

    def _fetch_one_modscag_tile(self, tile: str, d: date, tmp_dir: str) -> ModscagTile:
        import os
        from ftplib import error_perm, error_temp

        row_slice, col_slice = modscag_domain_crop(tile)
        remote_path = modscag_remote_path(tile, d)
        # tmp_dir is shared by every worker process in the pool (all workers
        # bootstrap their pixel-cell mapping from the same fixed date), so the
        # local filename must be per-process or concurrent workers overwrite
        # each other's in-progress download and corrupt the HDF5 file.
        local_path = os.path.join(
            tmp_dir, f"modscag_{tile}_{d.strftime('%Y%m%d')}_{os.getpid()}.nc"
        )

        with self._ftp_pool:
            ftp = None
            try:
                ftp = self._ftp_factory()
                with open(local_path, "wb") as fh:
                    ftp.retrbinary(f"RETR {remote_path}", fh.write)
            except error_temp as exc:
                raise TransientFetchError(
                    f"MODSCAG FTP transient error for {tile} {d}: {exc}"
                ) from exc
            except error_perm as exc:
                raise FatalFetchError(
                    f"MODSCAG FTP permanent error for {tile} {d} at {remote_path}: {exc}"
                ) from exc
            except OSError as exc:
                raise TransientFetchError(
                    f"MODSCAG FTP connection failed for {tile} {d}: {exc}"
                ) from exc
            finally:
                if ftp is not None:
                    try:
                        ftp.quit()
                    except Exception:
                        ftp.close()

        try:
            import xarray as xr

            with xr.open_dataset(local_path, engine="h5netcdf", mask_and_scale=False) as ds:
                snow = (
                    ds[config.MODSCAG_VARIABLE]
                    .isel(time=0, y=row_slice, x=col_slice)
                    .values.astype(np.float64)
                )
                dwo = (
                    ds[config.MODSCAG_DIAGNOSTIC_VARIABLE]
                    .isel(time=0, y=row_slice, x=col_slice)
                    .values.astype(np.float64)
                )
        except Exception as exc:
            raise FatalFetchError(f"Failed to decode MODSCAG granule for {tile} {d}: {exc}") from exc
        finally:
            if os.path.exists(local_path):
                os.remove(local_path)

        x, y = _modscag_tile_pixel_centers(tile)
        xx, yy = np.meshgrid(x[col_slice], y[row_slice])

        return ModscagTile(
            pixel_x_sinusoidal=xx.ravel(),
            pixel_y_sinusoidal=yy.ravel(),
            snow_fraction=snow.ravel(),
            days_without_observation=dwo.ravel(),
        )
