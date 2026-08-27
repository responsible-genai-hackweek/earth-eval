"""Unit conversions for presentation.

Everything is stored in SI - millimetres of water equivalent, metres of depth,
metres of elevation - and converted only when a number is shown. Storing the
display unit would mean re-deriving the whole record to change it, which is the
mistake this project already made once with derived quantities.

The display units are the ones this audience works in: western-US snow is
reported in inches of water equivalent and inches of depth, and Colorado terrain
is discussed in feet. Depth is deliberately *not* in feet - a record-low April
reads as 0.32 ft, which buries the signal behind a leading zero, against 3.8 in.
"""

from __future__ import annotations

__all__ = [
    "FT_PER_M",
    "IN_PER_M",
    "IN_PER_MM",
    "m_to_ft",
    "m_to_in",
    "mm_to_in",
]

IN_PER_MM = 1.0 / 25.4
IN_PER_M = 1.0 / 0.0254
FT_PER_M = 1.0 / 0.3048


def mm_to_in(value):
    """Millimetres of water equivalent to inches."""
    return value * IN_PER_MM


def m_to_in(value):
    """Metres to inches - used for snow depth."""
    return value * IN_PER_M


def m_to_ft(value):
    """Metres to feet - used for elevation only."""
    return value * FT_PER_M
