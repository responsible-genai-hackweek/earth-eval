"""Fractional-overlap area weighting and conservative regridding.

The two models are on different grids, and neither the domain mean nor a
difference map is meaningful unless both sides cover the same geography.

ERA5's 0.25 degree cells do not align with the MERRA-2 domain envelope - the
envelope edges fall on ERA5 *cell centers*, not cell edges. Selecting whole ERA5
cells would therefore average a slightly different region and attribute the
difference to the models. Every weight here is a fractional overlap instead, so
both grids integrate over exactly the same area.

Latitude overlap is a difference of sines, not of degrees, because a degree of
latitude subtends less area the further it is from the equator.
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "conservative_matrix",
    "domain_area_weights",
    "edges_from_centers",
    "latitude_overlap",
    "longitude_overlap",
    "to_zero_360",
]


def edges_from_centers(centers: np.ndarray) -> np.ndarray:
    """Derive cell edges from evenly spaced cell centers.

    Works for an ascending or descending axis, and returns edges in the same
    direction as the input so that edge ``i`` and ``i+1`` bracket center ``i``.
    """
    centers = np.asarray(centers, dtype=np.float64)
    if centers.ndim != 1 or centers.size < 2:
        raise ValueError("centers must be a 1-D array of at least two values")
    inner = (centers[:-1] + centers[1:]) / 2.0
    first = centers[0] - (inner[0] - centers[0])
    last = centers[-1] + (centers[-1] - inner[-1])
    return np.concatenate([[first], inner, [last]])


def to_zero_360(lon: np.ndarray) -> np.ndarray:
    """Convert longitudes to the 0..360 convention ERA5 uses.

    ERA5's longitude axis ascends from 0 to 359.75. Slicing it with a negative
    western longitude silently returns an empty array rather than an error,
    which looks exactly like missing data.
    """
    return np.asarray(lon, dtype=np.float64) % 360.0


def _clipped_spans(edges: np.ndarray, lo: float, hi: float) -> tuple[np.ndarray, np.ndarray]:
    """Return each cell's lower and upper bound clipped to ``[lo, hi]``."""
    edges = np.asarray(edges, dtype=np.float64)
    if edges.ndim != 1 or edges.size < 2:
        raise ValueError("edges must be a 1-D array of at least two values")
    lower = np.minimum(edges[:-1], edges[1:])
    upper = np.maximum(edges[:-1], edges[1:])
    return np.clip(lower, lo, hi), np.clip(upper, lo, hi)


def longitude_overlap(edges: np.ndarray, lon_min: float, lon_max: float) -> np.ndarray:
    """Degrees of longitude each cell contributes inside the domain."""
    lower, upper = _clipped_spans(edges, lon_min, lon_max)
    return upper - lower


def latitude_overlap(edges: np.ndarray, lat_min: float, lat_max: float) -> np.ndarray:
    """Relative area each latitude band contributes inside the domain.

    Expressed as a difference of sines, so the result is proportional to true
    spherical area rather than to degrees.
    """
    lower, upper = _clipped_spans(edges, lat_min, lat_max)
    return np.sin(np.radians(upper)) - np.sin(np.radians(lower))


def domain_area_weights(
    lat_centers: np.ndarray,
    lon_centers: np.ndarray,
    lon_min: float,
    lon_max: float,
    lat_min: float,
    lat_max: float,
) -> np.ndarray:
    """Area of each cell that lies inside the domain envelope.

    Returns a ``(n_lat, n_lon)`` array of relative areas, zero for cells wholly
    outside. Two different grids weighted this way integrate over identical
    geography, which is what makes a cross-model domain mean a comparison of
    models rather than of regions.

    Longitudes may be supplied in either convention; both the axis and the
    domain bounds are normalised to 0..360 before overlap is computed.
    """
    lat_w = latitude_overlap(edges_from_centers(lat_centers), lat_min, lat_max)
    lon_edges = edges_from_centers(to_zero_360(lon_centers))
    lon_w = longitude_overlap(lon_edges, *sorted(to_zero_360(np.array([lon_min, lon_max]))))
    return np.outer(lat_w, lon_w)


def conservative_matrix(src_edges: np.ndarray, dst_edges: np.ndarray) -> np.ndarray:
    """Overlap length of every source cell with every destination cell.

    The building block of conservative regridding in one dimension: entry
    ``(i, j)`` is how much of source cell ``i`` falls inside destination cell
    ``j``. A field regridded with these weights and renormalised by the column
    sums preserves a constant field exactly, and weighting by cell size
    preserves total mass.
    """
    src = np.asarray(src_edges, dtype=np.float64)
    dst = np.asarray(dst_edges, dtype=np.float64)
    if src.ndim != 1 or src.size < 2 or dst.ndim != 1 or dst.size < 2:
        raise ValueError("edges must be 1-D arrays of at least two values")

    src_lo = np.minimum(src[:-1], src[1:])[:, None]
    src_hi = np.maximum(src[:-1], src[1:])[:, None]
    dst_lo = np.minimum(dst[:-1], dst[1:])[None, :]
    dst_hi = np.maximum(dst[:-1], dst[1:])[None, :]

    return np.maximum(0.0, np.minimum(src_hi, dst_hi) - np.maximum(src_lo, dst_lo))
