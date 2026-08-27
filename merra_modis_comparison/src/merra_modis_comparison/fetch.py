"""Fetching daily domain means from both reanalyses.

The two models have opposite cost structures, and the sampling choice follows
from that rather than from preference.

MERRA-2 returns all twenty-four hours for about 1.8 times the bytes of one hour,
because a fixed netCDF4/DAP4 header dominates each response. A true daily mean
is therefore nearly free and is always used.

ERA5's Zarr chunks are one *global* field per timestep, so every hour costs a
full chunk regardless of how small the spatial window is. Twenty-four hours a
day across the whole record would be roughly a hundred times the transfer of one
hour a day. The sampling is therefore configurable and is calibrated against a
true daily mean rather than assumed adequate - see :func:`era5_diurnal_error`.
"""

from __future__ import annotations

import concurrent.futures as cf
import netrc
from datetime import date, timedelta

import numpy as np

from .calendars import enumerate_dates
from .regrid import domain_area_weights
from .snowvars import (
    era5_snow_cover,
    geometric_depth_m,
    grid_mean_depth_m,
    mask_merra2_fill,
    swe_from_water_equivalent_m,
)
from .sources import era5 as era5_src
from .sources import merra2 as merra2_src

__all__ = [
    "domain_mean_of",
    "era5_daily_cells",
    "era5_diurnal_error",
    "merra2_daily_cells",
    "open_era5",
]


def domain_mean_of(cells: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Area-weighted domain mean of a ``(n_days, ny, nx)`` stack, per day."""
    cells = np.asarray(cells, dtype=np.float64)
    flat = cells.reshape(cells.shape[0], -1)
    w = np.asarray(weights, dtype=np.float64).ravel()
    if flat.shape[1] != w.size:
        raise ValueError(f"cells have {flat.shape[1]} cells but {w.size} weights")
    ok = np.isfinite(flat) & (w > 0)[None, :]
    total = np.where(ok, w[None, :], 0.0).sum(axis=1)
    summed = np.where(ok, flat * w[None, :], 0.0).sum(axis=1)
    return np.where(total > 0, summed / np.maximum(total, 1e-30), np.nan)

DOMAIN = (
    era5_src.DOMAIN_LON_WEST,
    era5_src.DOMAIN_LON_EAST,
    era5_src.DOMAIN_LAT_SOUTH,
    era5_src.DOMAIN_LAT_NORTH,
)
ERA5_EPOCH = date(1900, 1, 1)


_ERA5_CACHE: dict[str, tuple] = {}


def open_era5(store: str = era5_src.ERA5_STORE):
    """Open ARCO-ERA5 and return the dataset plus its true data bounds.

    Cached: one opened dataset is reusable for the lifetime of the process and
    the anonymous token does not expire.
    """
    if store in _ERA5_CACHE:
        return _ERA5_CACHE[store]
    ds = era5_src.open_store(store)
    attrs = ds.attrs
    final = _as_date(attrs.get("valid_time_stop"))
    era5t = _as_date(attrs.get("valid_time_stop_era5t")) or final
    start = _as_date(attrs.get("valid_time_start")) or date(1940, 1, 1)
    _ERA5_CACHE[store] = (ds, start, final, era5t)
    return ds, start, final, era5t


def _as_date(value) -> date | None:
    if value is None:
        return None
    text = str(value)[:10]
    return date(int(text[:4]), int(text[5:7]), int(text[8:10]))


def _era5_window(ds):
    """Return the latitude/longitude index slices for the Colorado domain."""
    lat = np.asarray(ds["latitude"].values, dtype=float)
    lon = np.asarray(ds["longitude"].values, dtype=float)
    west, east = era5_src.colorado_lon_bounds()
    lat_hit = np.flatnonzero((lat >= DOMAIN[2] - 0.25) & (lat <= DOMAIN[3] + 0.25))
    lon_hit = np.flatnonzero((lon >= west - 0.25) & (lon <= east + 0.25))
    return (
        slice(int(lat_hit[0]), int(lat_hit[-1]) + 1),
        slice(int(lon_hit[0]), int(lon_hit[-1]) + 1),
        lat[lat_hit],
        lon[lon_hit],
    )


def era5_daily_cells(
    days: list[date],
    variables: tuple[str, ...] = ("snow_depth", "snow_density"),
    hours: tuple[int, ...] = (12,),
    workers: int = 24,
    store: str = era5_src.ERA5_STORE,
) -> dict[str, np.ndarray]:
    """Per-cell daily fields on ERA5's native grid, one slab per requested day.

    Returns the fields themselves rather than their domain mean. Storing the
    cells is what makes every downstream quantity - a domain mean, a derived
    depth, a difference map - recomputable without going back to the network.
    Reducing to a scalar here would discard the spatial covariance that a
    product or ratio of two fields depends on.

    ``hours`` selects which hours of each day are averaged. One hour is the
    affordable default across a long record; pass all twenty-four to compute a
    true daily mean for a calibration subset.
    """
    ds, start, final, era5t = open_era5(store)
    lat_sl, lon_sl, lat, lon = _era5_window(ds)
    weights = domain_area_weights(lat, lon, *DOMAIN)

    for day in days:
        era5_src.ensure_covered(day, start, era5t)

    arrays = {name: ds[name] for name in variables}

    def one_day(day: date) -> tuple[date, dict[str, float], str]:
        base, _ = era5_src.hour_index_range(day, ERA5_EPOCH)
        fields: dict[str, np.ndarray] = {}
        for name, array in arrays.items():
            samples = [
                np.asarray(
                    array.isel(time=base + hour, latitude=lat_sl, longitude=lon_sl).values,
                    dtype=float,
                )
                for hour in hours
            ]
            fields[name] = np.nanmean(np.stack(samples), axis=0)

        return day, fields, era5_src.classify_stream(day, final, era5t)

    results: dict[date, dict[str, np.ndarray]] = {}
    streams: dict[date, str] = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for day, values, stream in pool.map(one_day, days):
            results[day] = values
            streams[day] = stream

    ordered = sorted(results)
    out: dict[str, np.ndarray] = {
        name: np.stack([results[d][name] for d in ordered]).astype(np.float32)
        for name in variables
    }
    out["_days"] = np.array([d.isoformat() for d in ordered])
    out["_stream"] = np.array([streams[d] for d in ordered])
    out["_lat"] = lat.astype(np.float64)
    out["_lon"] = lon.astype(np.float64)
    return out


def era5_diurnal_error(sample_days: list[date], **kwargs) -> dict[str, float]:
    """Measure how much a single-hour sample differs from a true daily mean.

    Reported rather than assumed. If this is negligible relative to the signal,
    single-hour sampling across the long record is defensible and the number
    justifying it is on the record.
    """
    full = era5_daily_cells(sample_days, hours=tuple(range(24)), **kwargs)
    single = era5_daily_cells(sample_days, hours=(12,), **kwargs)
    report: dict[str, float] = {}
    for name in full:
        if name.startswith("_"):
            continue
        a = np.asarray(full[name]).reshape(len(sample_days), -1).mean(axis=1)
        b = np.asarray(single[name]).reshape(len(sample_days), -1).mean(axis=1)
        ok = np.isfinite(a) & np.isfinite(b)
        if not np.any(ok):
            continue
        report[f"{name}_mean_abs_diff"] = float(np.mean(np.abs(a[ok] - b[ok])))
        scale = float(np.mean(np.abs(a[ok])))
        report[f"{name}_relative"] = (
            float(np.mean(np.abs(a[ok] - b[ok]))) / scale if scale else float("nan")
        )
    return report


def merra2_daily_cells(days: list[date], workers: int = 16) -> dict[str, np.ndarray]:
    """Per-cell true 24-hour daily means of FRSNO, SNODP and SNOMAS.

    Returns the 9x8 fields themselves, for the same reason as
    :func:`era5_daily_cells`: a scalar cannot be un-averaged.
    """
    import requests

    from .grid import build_target_grid

    grid = build_target_grid()
    login, _, password = netrc.netrc().authenticators("urs.earthdata.nasa.gov")

    def worker(day: date):
        session = _SESSIONS.get()
        if session is None:
            session = requests.Session()
            session.auth = (login, password)
            _SESSIONS.set(session)
        return day, _fetch_merra2_day(session, day, grid)

    results: dict[date, dict[str, np.ndarray]] = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for day, values in pool.map(worker, days):
            results[day] = values

    ordered = sorted(results)
    out: dict[str, np.ndarray] = {
        name: np.stack([results[d][name] for d in ordered]).astype(np.float32)
        for name in merra2_src.SNOW_VARIABLES
    }
    out["_days"] = np.array([d.isoformat() for d in ordered])
    out["_lat"] = grid.lat_centers
    out["_lon"] = grid.lon_centers
    return out


def _fetch_merra2_day(session, day: date, grid) -> dict[str, np.ndarray]:
    import io

    import h5netcdf

    url = merra2_src.granule_url(day)
    response = session.get(url, timeout=180)
    if response.status_code != 200:
        raise RuntimeError(
            f"{day.isoformat()}: HTTP {response.status_code} "
            f"({len(response.content)} bytes) - a wrong stream returns a small "
            "error document, not an exception"
        )
    # Read from memory rather than a temporary file. netCDF4's in-memory mode
    # still probes the fake filename first and prints an HDF5 error stack.
    with h5netcdf.File(io.BytesIO(response.content), "r") as ds:
        lat = np.asarray(ds["lat"][:], dtype=float)
        lon = np.asarray(ds["lon"][:], dtype=float)
        units = ds["time"].attrs["units"]
        if isinstance(units, bytes):
            units = units.decode()
        fields = {
            name: mask_merra2_fill(np.asarray(ds[name][:], dtype=float))
            for name in merra2_src.SNOW_VARIABLES
        }
        merra2_src.validate_subset(
            np.where(np.isnan(fields["FRSNO"]), 0.0, fields["FRSNO"]),
            lat, lon, day, str(units),
        )
    # The 24-hour mean of each field, still per cell.
    return {name: np.nanmean(block, axis=0) for name, block in fields.items()}


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)
    if values.shape != weights.shape:
        raise ValueError(f"values {values.shape} do not match weights {weights.shape}")
    ok = np.isfinite(values) & (weights > 0)
    if not np.any(ok):
        return float("nan")
    return float((values[ok] * weights[ok]).sum() / weights[ok].sum())


class _ThreadLocal:
    def __init__(self):
        import threading

        self._local = threading.local()

    def get(self):
        return getattr(self._local, "value", None)

    def set(self, value):
        self._local.value = value


_SESSIONS = _ThreadLocal()
