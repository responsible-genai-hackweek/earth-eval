"""STC-MODSCAG reference access for the WY2023 satellite validation.

Two facts shape this module.

**Every 2-D variable is stored as one zlib chunk covering the whole 2400x2400
tile.** There is no cheap spatial subset: reading one pixel costs the whole
compressed slab. The saving comes from reading *one variable* instead of eleven,
which cuts a granule from about 16 MB to about 2 MB. That is why this reads by
byte range rather than downloading granules.

**Earthdata's login redirect strips the Authorization header across hosts.**
A plain ``requests`` session therefore gets a bare 401 on a redirect that looks
like it should have worked, so the session below re-attaches credentials
deliberately.
"""

from __future__ import annotations

import io
from datetime import date
from urllib.parse import urlparse

import numpy as np

__all__ = [
    "MODSCAG_FILL",
    "MODSCAG_HOST",
    "MODSCAG_SCALE",
    "RangeReader",
    "granule_url",
    "open_session",
    "read_snow_fraction",
]

MODSCAG_HOST = "https://daacdata.apps.nsidc.org/pub/DATASETS/STC_MODSCGDRF_HIST_v1"
URS_HOST = "urs.earthdata.nasa.gov"

#: snow_fraction is stored as uint8 percent; values above 100 are fill.
MODSCAG_SCALE = 100.0
MODSCAG_FILL = 255

#: Bytes prefetched so the HDF5 superblock and metadata resolve in one request.
HEADER_BYTES = 163840


def granule_url(tile: str, day: date) -> str:
    """Return the HTTPS URL of one tile-day."""
    return (
        f"{MODSCAG_HOST}/{tile}/{day.year:04d}/"
        f"STC_MODSCGDRF_HIST_{tile}_{day:%Y%m%d}_v01.0.nc"
    )


def open_session():
    """An Earthdata session that survives the login redirect.

    ``requests`` drops the Authorization header when a redirect crosses hosts,
    which is exactly what the Earthdata login flow does. Re-attaching it for the
    archive and login hosts is required, not an optimisation.
    """
    import netrc

    import requests

    login, _, password = netrc.netrc().authenticators(URS_HOST)

    class _URSSession(requests.Session):
        def rebuild_auth(self, prepared, response):
            if "Authorization" not in prepared.headers:
                return
            origin = urlparse(response.request.url).hostname
            target = urlparse(prepared.url).hostname
            if origin != target and target != URS_HOST and origin != URS_HOST:
                del prepared.headers["Authorization"]

    session = _URSSession()
    session.auth = (login, password)
    return session


class RangeReader(io.RawIOBase):
    """A seekable file over HTTP that fetches only the ranges asked for.

    Emits exactly **one contiguous range per request**. A multi-range request is
    answered by some servers with the entire file and HTTP 200, which would
    silently turn a two-megabyte read into a sixteen-megabyte one - and across a
    campaign, into a hundred gigabytes.
    """

    def __init__(self, url: str, session, prefetch: int = HEADER_BYTES):
        self._url = url
        self._session = session
        self._offset = 0
        self._requests = 0
        self._bytes = 0
        self._size = self._head()
        self._head_cache = self._fetch(0, min(prefetch, self._size))

    @property
    def request_count(self) -> int:
        return self._requests

    @property
    def bytes_read(self) -> int:
        return self._bytes

    def _head(self) -> int:
        """Total size, from a one-byte ranged GET rather than a HEAD.

        HEAD does not trigger the Earthdata login redirect: it returns a bare
        401 with no redirect history, while the same URL fetched with GET
        completes the OAuth hop and returns 206. Content-Range on that GET
        carries the total length, so this costs one request either way.
        """
        response = self._session.get(
            self._url, headers={"Range": "bytes=0-0"}, timeout=120
        )
        response.raise_for_status()
        content_range = response.headers.get("Content-Range", "")
        if "/" not in content_range:
            raise RuntimeError(
                f"no Content-Range in the response for {self._url}; got status "
                f"{response.status_code} and {len(response.content)} bytes"
            )
        self._requests += 1
        self._bytes += len(response.content)
        return int(content_range.rsplit("/", 1)[1])

    def _fetch(self, start: int, length: int) -> bytes:
        end = min(start + length, self._size) - 1
        if end < start:
            return b""
        response = self._session.get(
            self._url, headers={"Range": f"bytes={start}-{end}"}, timeout=180
        )
        if response.status_code != 206:
            raise RuntimeError(
                f"expected HTTP 206 for a range request, got {response.status_code} "
                f"with {len(response.content)} bytes; a 200 means the server "
                "ignored the range and sent the whole file"
            )
        payload = response.content
        expected = end - start + 1
        if len(payload) != expected:
            raise RuntimeError(
                f"range {start}-{end} returned {len(payload)} bytes, expected {expected}"
            )
        self._requests += 1
        self._bytes += len(payload)
        return payload

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self._offset = offset
        elif whence == io.SEEK_CUR:
            self._offset += offset
        else:
            self._offset = self._size + offset
        return self._offset

    def tell(self) -> int:
        return self._offset

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = self._size - self._offset
        if size == 0 or self._offset >= self._size:
            return b""
        stop = self._offset + size
        if stop <= len(self._head_cache):
            chunk = self._head_cache[self._offset : stop]
        else:
            chunk = self._fetch(self._offset, size)
        self._offset += len(chunk)
        return chunk

    def readinto(self, buffer) -> int:
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


def read_snow_fraction(
    tile: str, day: date, session, rows: slice, cols: slice, attempts: int = 4
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(fraction, valid)`` for a tile-day crop, fraction in 0..1.

    Fill is an elevation and land screen, not an observation of bare ground, so
    it is returned as an explicit validity mask rather than folded into zeros.

    Retries transient transport failures. The archive drops connections
    sporadically under load - a dropped connection is not a missing granule, and
    conflating the two silently shortens the record.
    """
    import time

    import h5py

    last: Exception | None = None
    for attempt in range(attempts):
        try:
            reader = RangeReader(granule_url(tile, day), session)
            with h5py.File(reader, "r") as handle:
                raw = np.asarray(handle["snow_fraction"][0, rows, cols])
            valid = raw <= MODSCAG_SCALE
            return np.where(valid, raw / MODSCAG_SCALE, np.nan), valid
        except Exception as exc:  # transport, not science
            last = exc
            if attempt < attempts - 1:
                time.sleep(2**attempt)
    raise RuntimeError(f"{tile} {day.isoformat()} failed after {attempts} attempts: {last}")
