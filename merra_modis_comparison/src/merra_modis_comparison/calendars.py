"""Water-year calendar rules for the fSCA comparison.

A water year runs from 1 October through 30 September and is named for the
calendar year in which it ends. Every grouping in this analysis - monthly,
seasonal, and climatological - is anchored to that definition, so the rules
live in one place and are unit-tested against the scientific contract.
"""

from __future__ import annotations

import calendar
from datetime import date

__all__ = [
    "NOV_MAY",
    "SEASONS",
    "WATER_YEAR_MONTH_ORDER",
    "calendar_year_of",
    "dates_in_month",
    "enumerate_dates",
    "month_tasks",
    "season_of",
    "water_year",
    "water_year_month_position",
]

#: Calendar months in water-year order, October first.
WATER_YEAR_MONTH_ORDER: tuple[int, ...] = (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9)

#: The snow-season months plotted by the composite figures, in water-year order.
NOV_MAY: tuple[int, ...] = (11, 12, 1, 2, 3, 4, 5)

#: Meteorological seasons keyed by name, each holding its calendar months.
SEASONS: dict[str, tuple[int, ...]] = {
    "DJF": (12, 1, 2),
    "MAM": (3, 4, 5),
    "JJA": (6, 7, 8),
    "SON": (9, 10, 11),
}

_MONTH_TO_SEASON: dict[int, str] = {
    month: name for name, months in SEASONS.items() for month in months
}

_MONTH_POSITION: dict[int, int] = {
    month: position for position, month in enumerate(WATER_YEAR_MONTH_ORDER, start=1)
}


def water_year(day: date) -> int:
    """Return the water year containing ``day``.

    October through December belong to the water year named for the following
    calendar year.
    """
    return day.year + 1 if day.month >= 10 else day.year


def calendar_year_of(wy: int, month: int) -> int:
    """Return the calendar year in which ``month`` of water year ``wy`` falls.

    This is the inverse of :func:`water_year` at month resolution.
    """
    _check_month(month)
    return wy - 1 if month >= 10 else wy


def season_of(day: date) -> str:
    """Return the meteorological season name for ``day``."""
    return _MONTH_TO_SEASON[day.month]


def water_year_month_position(month: int) -> int:
    """Return the 1-based position of ``month`` within a water year."""
    _check_month(month)
    return _MONTH_POSITION[month]


def month_tasks(
    water_years: tuple[int, ...], months: tuple[int, ...] = WATER_YEAR_MONTH_ORDER
) -> list[tuple[int, int]]:
    """Return chronological ``(calendar_year, month)`` pairs to process.

    The month is the task unit and the minimum recomputation unit of the
    pipeline, so this list defines exactly one checkpoint each.
    """
    pairs = [
        (calendar_year_of(wy, month), month)
        for wy in water_years
        for month in months
    ]
    return sorted(pairs)


def dates_in_month(year: int, month: int) -> list[date]:
    """Return every calendar date in ``year``-``month``."""
    _check_month(month)
    n_days = calendar.monthrange(year, month)[1]
    return [date(year, month, day) for day in range(1, n_days + 1)]


def enumerate_dates(
    water_years: tuple[int, ...], months: tuple[int, ...] = WATER_YEAR_MONTH_ORDER
) -> list[date]:
    """Return every date in the requested water-year months, chronologically."""
    return [
        day
        for year, month in month_tasks(water_years, months)
        for day in dates_in_month(year, month)
    ]


def _check_month(month: int) -> None:
    if not 1 <= month <= 12:
        raise ValueError(f"month must be in 1..12, got {month!r}")
