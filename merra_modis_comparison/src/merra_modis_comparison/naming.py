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

#: Contiguous production-stream runs, established by listing every month
#: directory from 1999 through 2026 and parsing all 10,075 granule names, plus
#: spot checks at 1980-01, 1991-12 and 1992-01. Ordered; the first run whose
#: span contains the date wins.
#:
#: The two 401 reprocessing windows are deliberately written out rather than
#: derived: they are not the same shape. September 2020 is a single month, while
#: June through September 2021 is four, and stream 400 resumes in between. A rule
#: that treats them symmetrically silently misses August and September 2021.
_STREAM_RUNS: tuple[tuple[date, date, int], ...] = (
    (date(1980, 1, 1), date(1991, 12, 31), 100),
    (date(1992, 1, 1), date(2000, 12, 31), 200),
    (date(2001, 1, 1), date(2010, 12, 31), 300),
    (date(2011, 1, 1), date(2020, 8, 31), 400),
    (date(2020, 9, 1), date(2020, 9, 30), 401),
    (date(2020, 10, 1), date(2021, 5, 31), 400),
    (date(2021, 6, 1), date(2021, 9, 30), 401),
    (date(2021, 10, 1), date(9999, 12, 31), 400),
)

#: First date the collection publishes.
MERRA2_FIRST_DATE = date(1980, 1, 1)


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

    The stream is load-bearing, not cosmetic: requesting the right date with the
    wrong stream returns HTTP 404 carrying a small XML error document rather
    than raising, so a caller that writes response bytes straight to disk
    produces a directory of tiny corrupt files that only fail later, at decode.
    """
    if day < MERRA2_FIRST_DATE:
        raise ValueError(
            f"MERRA-2 begins {MERRA2_FIRST_DATE.isoformat()}; got {day.isoformat()}"
        )
    for start, end, stream in _STREAM_RUNS:
        if start <= day <= end:
            return stream
    raise ValueError(f"no MERRA-2 production stream covers {day.isoformat()}")


def merra2_granule(day: date) -> Granule:
    """Resolve the MERRA-2 land granule for ``day``."""
    stamp = day.strftime("%Y%m%d")
    return Granule(
        filename=f"MERRA2_{merra2_stream(day)}.tavg1_2d_lnd_Nx.{stamp}.nc4",
        archive_path=f"data/MERRA2/{MERRA2_COLLECTION}/{day.year:04d}/{day.month:02d}",
    )
