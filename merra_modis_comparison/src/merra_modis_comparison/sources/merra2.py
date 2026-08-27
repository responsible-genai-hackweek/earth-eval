"""MERRA-2 access via NASA Cloud OPeNDAP.

The archive-path OPeNDAP endpoint was retired and returns HTTP 410. Its
replacement is addressed by CMR concept id and GranuleUR rather than by path,
and the DAP4 constraint expression must be percent-encoded: an unencoded
bracket is rejected with HTTP 400 by the front-end server before the OPeNDAP
service ever parses it.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from ..naming import merra2_granule
from ..snowvars import MERRA2_FILL_THRESHOLD

__all__ = [
    "MERRA2_COLLECTION_UR",
    "MERRA2_CONCEPT_ID",
    "MERRA2_LAT_SLICE",
    "MERRA2_LON_SLICE",
    "SNOW_VARIABLES",
    "dap4_constraint",
    "granule_url",
    "validate_subset",
]

OPENDAP_HOST = "https://opendap.earthdata.nasa.gov"
MERRA2_CONCEPT_ID = "C1276812861-GES_DISC"
MERRA2_COLLECTION_UR = "M2T1NXLND.5.12.4"

#: Global grid indices of the 72-cell domain, as NumPy half-open slices.
#: DAP4 ranges are inclusive, so the constraint expression uses 254:262 and
#: 114:121 while these slices use 263 and 122.
MERRA2_LAT_SLICE = slice(254, 263)
MERRA2_LON_SLICE = slice(114, 122)

#: The three variables the snowpack comparison needs.
SNOW_VARIABLES = ("FRSNO", "SNODP", "SNOMAS")

_LAT0, _LAT1 = MERRA2_LAT_SLICE.start, MERRA2_LAT_SLICE.stop - 1
_LON0, _LON1 = MERRA2_LON_SLICE.start, MERRA2_LON_SLICE.stop - 1


def _encode(expression: str) -> str:
    return expression.replace("/", "%2F").replace("[", "%5B").replace("]", "%5D").replace(":", "%3A")


def dap4_constraint(
    variables: tuple[str, ...] = SNOW_VARIABLES, hours: tuple[int, int] = (0, 23)
) -> str:
    """Build the percent-encoded DAP4 constraint expression.

    Requesting all twenty-four hours costs only about 1.8 times a single hour,
    because a fixed netCDF4/DAP4 header dominates the response. Asking for one
    hour to save bandwidth saves almost nothing and forfeits a true daily mean.

    The coordinate variables are always requested so the returned subset can be
    checked against the domain rather than trusted.
    """
    if not variables:
        raise ValueError("at least one variable must be requested")
    first, last = hours
    parts = [
        f"/{name}[{first}:{last}][{_LAT0}:{_LAT1}][{_LON0}:{_LON1}]"
        for name in variables
    ]
    parts += [f"/lat[{_LAT0}:{_LAT1}]", f"/lon[{_LON0}:{_LON1}]", f"/time[{first}:{last}]"]
    return "dap4.ce=" + _encode(";".join(parts))


def granule_url(day: date, variables: tuple[str, ...] = SNOW_VARIABLES, **kwargs) -> str:
    """Return the full Cloud OPeNDAP URL for one day's subset."""
    filename = merra2_granule(day).filename
    granule_ur = _encode(f"{MERRA2_COLLECTION_UR}:{filename}")
    return (
        f"{OPENDAP_HOST}/collections/{MERRA2_CONCEPT_ID}/granules/"
        f"{granule_ur}.dap.nc4?{dap4_constraint(variables, **kwargs)}"
    )


def validate_subset(
    values: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    day: date,
    time_units: str,
    expected_hours: int = 24,
) -> None:
    """Check a decoded subset against the domain before it is used.

    These assertions cost nothing and catch the two failures that would
    otherwise be invisible: a mis-built URL that returned a different day, and a
    subset shifted off the domain.
    """
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    expected = (expected_hours, 9, 8)
    if values.shape != expected:
        raise ValueError(f"subset shape {values.shape} is not the expected {expected}")
    if not np.allclose(lat, np.arange(37.0, 41.5, 0.5), atol=1e-6):
        raise ValueError(f"latitude coordinates {lat} are not the target domain")
    if not np.allclose(lon, np.arange(-108.75, -104.0, 0.625), atol=1e-6):
        raise ValueError(f"longitude coordinates {lon} are not the target domain")
    if day.isoformat() not in time_units:
        raise ValueError(
            f"time units {time_units!r} do not refer to {day.isoformat()}; "
            "the URL probably resolved to a different granule"
        )
    if np.any(np.abs(np.asarray(values)) >= MERRA2_FILL_THRESHOLD):
        raise ValueError(
            "subset contains fill values; they must be masked before averaging, "
            "never treated as zero snow"
        )
