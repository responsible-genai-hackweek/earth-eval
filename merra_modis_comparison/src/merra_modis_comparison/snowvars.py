"""Snow quantities in common units, and area weighting.

Two conventions in this module exist because getting them wrong produces a
plausible-looking answer rather than an error.

**MERRA-2 ``SNODP`` is not a grid-cell mean.** It is snow depth over the
snow-covered fraction of the cell, so the grid-cell mean depth is
``FRSNO * SNODP``. ``SNOMAS`` in the same file *is* a grid-cell mean, in
kg m-2. Two variables, one granule, different area conventions. The tell is the
implied density: dividing snow mass by the grid-mean depth gives physical
densities that bottom out at exactly the model's fresh-snow constant, while
dividing by raw ``SNODP`` gives values an order of magnitude too low.

**Latitude/longitude cells are not equal area.** A domain mean over such a grid
must be weighted, and the exact weight for a band is the difference of the sines
of its edge latitudes - not the cosine of its center, though that is a close
approximation.
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "ERA5_CRITICAL_DEPTH_M",
    "FRESH_SNOW_DENSITY_KG_M3",
    "MERRA2_FILL_THRESHOLD",
    "MERRA2_WEMIN_KG_M2",
    "WATER_DENSITY_KG_M3",
    "era5_snow_cover",
    "mask_merra2_fill",
    "merra2_snow_cover",
    "cos_latitude_weights",
    "domain_mean",
    "geometric_depth_m",
    "grid_mean_depth_m",
    "implied_density_kg_m3",
    "latitude_band_weights",
    "swe_from_water_equivalent_m",
]

#: Density of liquid water, for water-equivalent conversions.
WATER_DENSITY_KG_M3 = 1000.0

#: The fresh-snow density constant MERRA-2's land model floors new snowpack at.
#: Implied densities computed from grid-mean depth bottom out exactly here,
#: which is what identifies the correct depth convention.
FRESH_SNOW_DENSITY_KG_M3 = 150.0

#: MERRA-2's minimum snow water equivalent for full grid-cell cover, kg m-2.
#: FRSNO = min(1, SNOMAS / WEMIN), which also explains why SNODP saturates at
#: WEMIN / FRESH_SNOW_DENSITY = 0.173333 m.
MERRA2_WEMIN_KG_M2 = 26.0

#: ERA5's critical geometric snow depth for full cover, metres (IFS scheme).
ERA5_CRITICAL_DEPTH_M = 0.10

#: Values at or above this are MERRA-2 fill. The published ``valid_range`` is
#: useless as a bound because it *equals* the fill value, so it admits fill.
MERRA2_FILL_THRESHOLD = 1e14


def mask_merra2_fill(values):
    """Replace MERRA-2 fill values with NaN.

    Fill is a missing observation, not a zero. The granule's own ``valid_range``
    cannot be used to detect it, so the sentinel magnitude is used instead.
    """
    values = np.asarray(values, dtype=np.float64)
    return np.where(np.abs(values) >= MERRA2_FILL_THRESHOLD, np.nan, values)


def merra2_snow_cover(swe_kg_m2, wemin_kg_m2: float = MERRA2_WEMIN_KG_M2):
    """MERRA-2's diagnosed fractional snow cover, ``min(1, SWE / WEMIN)``."""
    swe = np.asarray(swe_kg_m2, dtype=np.float64)
    return np.minimum(1.0, np.maximum(0.0, swe) / float(wemin_kg_m2))


def era5_snow_cover(
    swe_kg_m2, density_kg_m3, critical_depth_m: float = ERA5_CRITICAL_DEPTH_M
):
    """ERA5's diagnosed fractional snow cover from the IFS scheme.

    ERA5 does not archive a fractional snow cover field, so it must be diagnosed
    as ``min(1, geometric_depth / critical_depth)``. This is a *different*
    sub-grid scheme from MERRA-2's, so the two are compared, never substituted
    for one another.
    """
    depth = geometric_depth_m(swe_kg_m2, density_kg_m3)
    return np.minimum(1.0, np.maximum(0.0, depth) / float(critical_depth_m))


def grid_mean_depth_m(frsno, snodp):
    """Grid-cell mean snow depth in metres, from fractional cover and snow depth.

    ``snodp`` is depth over the snow-covered fraction only. Using it directly as
    a cell mean overstates depth in every partially covered cell, and overstates
    it most in exactly the sparse, low-snow cells a drought year is made of.
    """
    frsno = np.asarray(frsno, dtype=np.float64)
    snodp = np.asarray(snodp, dtype=np.float64)
    if np.any(np.isfinite(frsno) & ((frsno < 0.0) | (frsno > 1.0))):
        raise ValueError("frsno must be a fraction in 0..1")
    return frsno * snodp


def implied_density_kg_m3(swe_kg_m2, frsno, snodp):
    """Bulk snow density implied by mass and grid-mean depth, in kg m-3.

    A diagnostic, not an input: physical values confirm the depth convention is
    right, and values far below :data:`FRESH_SNOW_DENSITY_KG_M3` mean it is not.
    """
    depth = grid_mean_depth_m(frsno, snodp)
    swe = np.asarray(swe_kg_m2, dtype=np.float64)
    return _safe_divide(swe, depth)


def swe_from_water_equivalent_m(sd_m):
    """Convert a depth of water equivalent, in metres, to kg m-2."""
    return np.asarray(sd_m, dtype=np.float64) * WATER_DENSITY_KG_M3


def geometric_depth_m(swe_kg_m2, density_kg_m3):
    """Convert snow water equivalent and bulk density to geometric depth."""
    return _safe_divide(
        np.asarray(swe_kg_m2, dtype=np.float64),
        np.asarray(density_kg_m3, dtype=np.float64),
    )


def latitude_band_weights(lat_edges: np.ndarray) -> np.ndarray:
    """Exact relative area of each latitude band on a sphere.

    The area of a band between two latitudes is proportional to the difference
    of the sines of its edges. For a regular longitude spacing the longitude
    term is constant and cancels in any weighted mean.
    """
    edges = np.asarray(lat_edges, dtype=np.float64)
    if edges.ndim != 1 or edges.size < 2:
        raise ValueError("lat_edges must be a 1-D array of at least two edges")
    return np.abs(np.diff(np.sin(np.radians(edges))))


def cos_latitude_weights(lat_centers: np.ndarray) -> np.ndarray:
    """Cosine-of-latitude weights, the standard small-cell approximation."""
    return np.cos(np.radians(np.asarray(lat_centers, dtype=np.float64)))


def domain_mean(values: np.ndarray, lat: np.ndarray) -> float:
    """Area-weighted mean of a ``(lat, lon)`` field over the whole domain.

    Cells that are not finite are excluded rather than treated as zero: a
    missing cell is unknown, not snow-free. Works for an ascending or a
    descending latitude axis, since the weight depends only on the latitude of
    each row.
    """
    values = np.asarray(values, dtype=np.float64)
    lat = np.asarray(lat, dtype=np.float64)
    if values.ndim != 2:
        raise ValueError(f"values must be 2-D (lat, lon), got shape {values.shape}")
    if lat.size != values.shape[0]:
        raise ValueError(
            f"latitude length {lat.size} does not match values rows {values.shape[0]}"
        )

    weights = np.broadcast_to(cos_latitude_weights(lat)[:, None], values.shape)
    usable = np.isfinite(values) & np.isfinite(weights)
    if not np.any(usable):
        return float("nan")
    total = float(weights[usable].sum())
    if total == 0.0:
        return float("nan")
    return float((values[usable] * weights[usable]).sum() / total)


def _safe_divide(numerator: np.ndarray, denominator: np.ndarray):
    """Divide, returning NaN where the ratio is undefined instead of raising."""
    numerator = np.asarray(numerator, dtype=np.float64)
    denominator = np.asarray(denominator, dtype=np.float64)
    ok = np.isfinite(numerator) & np.isfinite(denominator) & (denominator != 0.0)
    out = np.full(np.broadcast(numerator, denominator).shape, np.nan, dtype=np.float64)
    np.divide(numerator, denominator, out=out, where=ok)
    return out if out.ndim else float(out)
