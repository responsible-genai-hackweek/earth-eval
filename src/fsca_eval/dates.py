"""Water-year/calendar-month iteration and MERRA-2 filename-stream boundaries.

Pure functions only -- no I/O, no network. See scientific-contract.md for the
water-year range, stream boundary rule, and the two 401-reprocessing
exceptions this module encodes.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Iterator

from . import config

# (year_offset_from_wy, month) pairs in water-year order: Oct, Nov, ..., Sep.
# year_offset is 0 for Oct-Dec (belongs to wy - 1) and 1 for Jan-Sep (belongs to wy).
_WATER_YEAR_MONTH_ORDER: tuple[tuple[int, int], ...] = (
    (0, 10),
    (0, 11),
    (0, 12),
    (1, 1),
    (1, 2),
    (1, 3),
    (1, 4),
    (1, 5),
    (1, 6),
    (1, 7),
    (1, 8),
    (1, 9),
)


def water_year_of(d: date) -> int:
    """Water year containing a given calendar date (Oct 1 - Sep 30)."""
    return d.year + 1 if d.month >= 10 else d.year


def water_year_start_date(wy: int) -> date:
    return date(wy - 1, 10, 1)


def water_year_end_date(wy: int) -> date:
    return date(wy, 9, 30)


def iter_water_years() -> Iterator[int]:
    return iter(range(config.WY_START, config.WY_END + 1))


def calendar_month_for_water_year(wy: int, month_index: int) -> tuple[int, int]:
    """month_index is 0-11 in water-year order (0=Oct, ..., 11=Sep)."""
    year_offset, month = _WATER_YEAR_MONTH_ORDER[month_index]
    return (wy - 1 + year_offset, month)


def iter_calendar_months() -> Iterator[tuple[int, int, int]]:
    """Yield (water_year, calendar_year, calendar_month) for all 168 months."""
    for wy in iter_water_years():
        for year_offset, month in _WATER_YEAR_MONTH_ORDER:
            yield (wy, wy - 1 + year_offset, month)


def n_calendar_days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def iter_dates_in_month(year: int, month: int) -> Iterator[date]:
    n_days = n_calendar_days_in_month(year, month)
    d = date(year, month, 1)
    for _ in range(n_days):
        yield d
        d += timedelta(days=1)


def iter_all_dates() -> Iterator[date]:
    """Every date from WY start through WY end, inclusive, in order."""
    d = water_year_start_date(config.WY_START)
    end = water_year_end_date(config.WY_END)
    while d <= end:
        yield d
        d += timedelta(days=1)


def merra_stream_for_date(d: date) -> int:
    """MERRA-2 filename stream number for a given date.

    Rule: stream 300 through calendar year 2010, stream 400 from calendar
    year 2011 onward, except stream 401 for September 2020 and June-September
    2021 (a documented reprocessing exception).
    """
    if (d.year, d.month) in config.MERRA_STREAM_REPROCESSED_MONTHS:
        return config.MERRA_STREAM_REPROCESSED
    if d.year <= 2010:
        return config.MERRA_STREAM_EARLY
    return config.MERRA_STREAM_LATE
