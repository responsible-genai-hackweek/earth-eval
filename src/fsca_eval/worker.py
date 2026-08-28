"""Per-date processing: fetch (I/O) then reduce (pure aggregation).

Split into two functions so that both `pipeline.py` (which discards raw
arrays immediately after reduction) and `examples.py` (which keeps the raw
arrays for illustration) go through the identical aggregation code path in
regrid.py/metrics.py. Do not reimplement aggregation elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from . import config, dates, earthdata, metrics, regrid


@dataclass(frozen=True)
class RawDayInputs:
    """Everything fetched for one date, before any aggregation."""

    date: date
    merra: earthdata.MerraSubset
    modscag_tiles: list[earthdata.ModscagTile]


@dataclass(frozen=True)
class DayCellRecord:
    """One date's aggregation result, per cell, in stable cell_id order."""

    date: date
    m_fraction: np.ndarray  # shape (N_CELLS,), MERRA fraction, native grid
    aggregate: regrid.CellDayAggregate  # R (reference_fraction) and pixel accounting
    stats: list[metrics.SufficientStats]  # length N_CELLS


def fetch_day(d: date, transport: earthdata.Transport, tmp_dir: str) -> RawDayInputs:
    """Thin I/O wrapper: no numeric logic. Tiles are deleted by the caller
    immediately after `reduce_day` extracts what it needs.
    """
    stream = dates.merra_stream_for_date(d)
    merra = transport.fetch_merra_subset(d, stream)
    tiles = transport.fetch_modscag_tiles(d, tmp_dir)
    return RawDayInputs(date=d, merra=merra, modscag_tiles=tiles)


def _merra_fraction_by_cell_id(merra: earthdata.MerraSubset) -> np.ndarray:
    """Extract MERRA fraction (M) into stable cell_id order. No aggregation:
    MERRA is already on the native 72-cell grid.
    """
    m_fraction = np.empty(config.N_CELLS, dtype=np.float64)
    for lon_idx in range(config.N_LON_CELLS):
        for lat_idx in range(config.N_LAT_CELLS):
            cell_id = int(regrid.cell_id_from_indices(lon_idx, lat_idx))
            m_fraction[cell_id] = merra.frsno[lat_idx, lon_idx]
    return m_fraction


def reduce_day(raw: RawDayInputs, mapping: regrid.PixelCellMapping) -> DayCellRecord:
    """Pure aggregation: MODSCAG pixels -> per-cell R via regrid.apply_mapping,
    MERRA -> per-cell M via direct extraction (no resampling), then one
    sufficient-stat contribution per cell via metrics.cell_day_contribution.
    """
    snow_fraction = np.concatenate([t.snow_fraction for t in raw.modscag_tiles])
    days_without_observation = np.concatenate(
        [t.days_without_observation for t in raw.modscag_tiles]
    )

    aggregate = regrid.apply_mapping(mapping, snow_fraction, days_without_observation)
    m_fraction = _merra_fraction_by_cell_id(raw.merra)

    stats = [
        metrics.cell_day_contribution(
            m_fraction=float(m_fraction[cell_id]),
            r_fraction=float(aggregate.reference_fraction[cell_id]),
            weight=int(aggregate.valid_pixels[cell_id]),
            expected_pixels=int(aggregate.expected_pixels[cell_id]),
            observed_pixels=int(aggregate.observed_pixels[cell_id]),
            support_fraction=float(aggregate.support_fraction[cell_id]),
            support_threshold=config.SUPPORT_THRESHOLD,
        )
        for cell_id in range(config.N_CELLS)
    ]

    return DayCellRecord(date=raw.date, m_fraction=m_fraction, aggregate=aggregate, stats=stats)
