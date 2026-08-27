"""Granule filename and archive-path resolution.

The MERRA-2 filename carries a production-stream number that changes twice
inside the published record and again for two reprocessed intervals. Getting it
wrong produces a 404 partway through a campaign, so the rule is isolated here
and tested against dates verified against the live archive.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

__all__ = ["Granule", "merra2_granule", "merra2_stream"]

MERRA2_HOST = "https://goldsmr4.gesdisc.eosdis.nasa.gov"
MERRA2_COLLECTION = "M2T1NXLND.5.12.4"

#: Calendar months reprocessed under production stream 401.
_REPROCESSED_401: frozenset[tuple[int, int]] = frozenset(
    {(2020, 9), (2021, 6), (2021, 7), (2021, 8), (2021, 9)}
)


@dataclass(frozen=True)
class Granule:
    """A resolved remote granule."""

    filename: str
    archive_path: str

    @property
    def url(self) -> str:
        return f"{MERRA2_HOST}/{self.archive_path}/{self.filename}"


def merra2_stream(day: date) -> int:
    """Return the MERRA-2 production stream number for ``day``.

    Stream 300 runs through 2010 and 400 from 2011, except for the months NASA
    reprocessed under 401.
    """
    if (day.year, day.month) in _REPROCESSED_401:
        return 401
    return 300 if day.year <= 2010 else 400


def merra2_granule(day: date) -> Granule:
    """Resolve the MERRA-2 land granule for ``day``."""
    stamp = day.strftime("%Y%m%d")
    return Granule(
        filename=f"MERRA2_{merra2_stream(day)}.tavg1_2d_lnd_Nx.{stamp}.nc4",
        archive_path=f"data/MERRA2/{MERRA2_COLLECTION}/{day.year:04d}/{day.month:02d}",
    )
