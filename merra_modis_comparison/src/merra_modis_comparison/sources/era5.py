"""ERA5 access via ARCO-ERA5, the analysis-ready Zarr store on Google Cloud.

Public, anonymous, no credentials. Three properties of this store cause silent
wrong answers rather than errors, so each is guarded here:

* **The time axis is padded.** It runs 1900-01-01 to 2050-12-31 hourly, but data
  exists only from 1940 to a moving recent boundary. Chunks outside that range
  are simply absent and read back as NaN, with no error and no warning.
* **Longitude is 0..360.** Slicing Colorado with a negative western longitude
  returns an empty array, which looks exactly like missing data.
* **Latitude descends** from 90 to -90, so a slice must be given high-to-low.
  MERRA-2's latitude ascends, so no slicing helper is safe to share between them.
"""

from __future__ import annotations

from datetime import date, timedelta

__all__ = [
    "ERA5_STORE",
    "classify_stream",
    "colorado_lat_slice",
    "colorado_lon_bounds",
    "ensure_covered",
    "hour_index_range",
    "open_store",
]

#: The rolling ARCO-ERA5 store. Sibling stores carry frozen date prefixes; this
#: one has none and is updated daily.
ERA5_STORE = "gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"

#: The MERRA-2 complete-cell envelope, which both models are averaged over.
DOMAIN_LON_WEST = -109.0625
DOMAIN_LON_EAST = -104.0625
DOMAIN_LAT_SOUTH = 36.75
DOMAIN_LAT_NORTH = 41.25


def colorado_lat_slice() -> tuple[float, float]:
    """Latitude bounds ordered north-to-south, matching the descending axis."""
    return (DOMAIN_LAT_NORTH, DOMAIN_LAT_SOUTH)


def colorado_lon_bounds() -> tuple[float, float]:
    """Longitude bounds in the 0..360 convention, west first."""
    return (DOMAIN_LON_WEST % 360.0, DOMAIN_LON_EAST % 360.0)


def ensure_covered(day: date, data_start: date, data_stop: date) -> None:
    """Raise unless ``day`` lies inside the store's actual data range.

    Without this a request outside the range returns NaN rather than failing,
    and a whole water year of NaN averages to NaN silently.
    """
    if day < data_start:
        raise ValueError(
            f"{day.isoformat()} is before ERA5 data begins ({data_start.isoformat()})"
        )
    if day > data_stop:
        raise ValueError(
            f"{day.isoformat()} is beyond the last ERA5 data "
            f"({data_stop.isoformat()}); the time axis extends further but the "
            "chunks are absent and would read back as NaN"
        )


def classify_stream(day: date, final_stop: date, era5t_stop: date) -> str:
    """Return ``"final"`` or ``"era5t"`` for ``day``.

    ERA5T values are preliminary and can be revised when final ERA5 replaces
    them. The store gives both the same variable names with no per-value flag,
    so the distinction has to be carried explicitly by the caller.
    """
    if day <= final_stop:
        return "final"
    if day <= era5t_stop:
        return "era5t"
    raise ValueError(f"{day.isoformat()} is beyond ERA5T ({era5t_stop.isoformat()})")


def hour_index_range(day: date, epoch: date) -> tuple[int, int]:
    """Return the half-open hourly index range covering ``day``.

    Indexing positionally avoids a label-based time slice, which on an hourly
    axis silently returns every hour in the range rather than a daily value.
    """
    start = (day - epoch).days * 24
    return start, start + 24


def open_store(store: str = ERA5_STORE):
    """Open the ARCO-ERA5 store anonymously.

    One filesystem and one opened dataset are reusable for the lifetime of a
    process; the anonymous token does not expire.
    """
    import xarray as xr

    return xr.open_zarr(store, chunks=None, storage_options={"token": "anon"})
