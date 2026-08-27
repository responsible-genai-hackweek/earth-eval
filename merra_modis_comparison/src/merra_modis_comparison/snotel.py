"""NRCS SNOTEL daily snow water equivalent over the Colorado domain.

Product research, including every trap below, is in
``research/SNOTEL_PRODUCT_NOTES.md``. The methodology this serves is in
``plan/SEASON_SHAPE_PLAN.md``.

**This network measures timing, never magnitude, in this domain.** Every Colorado
SNOTEL station sits above the model domain's median cell elevation: the network
samples the high country inside the domain, not the domain. A raw network
statistic placed beside a raw domain statistic measures station siting and
reports it as model error.

Three behaviours of the archive that produce a wrong answer rather than an error:

- The station's ``beginDate`` is not the element's. Berthoud Summit reports a
  station begin of 1963-09-01 and a ``WTEQ`` begin of 1978-10-01.
- An empty ``data`` array is usually a real absence, not a failure. A station
  rebuilt in 2025 returns ``[]`` with HTTP 200 for 2023. It is typed
  ``no_record`` here so it can never be read as a broken fetch.
- ``WTEQ`` is stored in inches, which is already this project's display unit. No
  conversion is applied anywhere; adding one would double-convert.
"""

from __future__ import annotations

import concurrent.futures as cf
import csv
import json
import os
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

__all__ = [
    "AWDB_BASE",
    "FetchReport",
    "Station",
    "fetch_all",
    "list_stations",
    "load_station",
    "open_session",
]

AWDB_BASE = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"
#: Complete-cell envelope of the target grid, as used throughout this project.
ENVELOPE = (-109.0625, -104.0625, 36.75, 41.25)
#: Retried with backoff. A 404 is an addressing fault and is never retried:
#: four attempts cannot fix a wrong URL, they only slow the diagnosis down.
RETRYABLE = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class Station:
    """One SNOTEL site. ``elevation_ft`` is the archive's own unit."""

    triplet: str
    name: str
    elevation_ft: float
    latitude: float
    longitude: float

    @property
    def filename(self) -> str:
        return self.triplet.replace(":", "_") + ".csv"


@dataclass(frozen=True)
class FetchReport:
    """What the run intended against what reached disk."""

    by_status: dict[str, list[str]]
    missing: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.missing

    def summary(self) -> str:
        counts = ", ".join(f"{k} {len(v)}" for k, v in sorted(self.by_status.items()))
        tail = "" if self.complete else f"; MISSING {len(self.missing)}: {self.missing[:5]}"
        return f"{counts}{tail}"


def open_session() -> requests.Session:
    """One pool for the process. A pool per unit repeats every handshake."""
    session = requests.Session()
    session.headers["User-Agent"] = "earth-eval snowpack comparison (research)"
    return session


def list_stations(session: requests.Session | None = None) -> list[Station]:
    """Every Colorado SNOTEL station whose coordinates fall in the envelope.

    Sorted longest-record-first, so an interrupted run holds the stations a
    46-year climatology needs rather than an arbitrary alphabetical prefix.
    """
    session = session or open_session()
    payload = session.get(
        f"{AWDB_BASE}/stations",
        params={"stationTriplets": "*:CO:SNTL", "activeOnly": "false"},
        timeout=60,
    )
    payload.raise_for_status()
    west, east, south, north = ENVELOPE
    rows = [
        s for s in payload.json()
        if west <= s["longitude"] <= east and south <= s["latitude"] <= north
    ]
    rows.sort(key=lambda s: s.get("beginDate") or "9999")
    return [
        Station(s["stationTriplet"], s["name"], float(s["elevation"]),
                float(s["latitude"]), float(s["longitude"]))
        for s in rows
    ]


def _get(session, params, attempts: int = 4):
    """Retry only what a retry can fix, and name the fault actually seen."""
    last = None
    for attempt in range(attempts):
        try:
            response = session.get(f"{AWDB_BASE}/data", params=params, timeout=180)
        except (requests.ConnectionError, requests.Timeout) as exc:
            # A dropped connection is not a missing record; treating it as one
            # silently shortens the record.
            last = f"connection:{type(exc).__name__}"
            time.sleep(2 ** attempt)
            continue
        if response.status_code == 200:
            return response.json(), "ok"
        if response.status_code == 404:
            return None, "http_404_addressing"
        if response.status_code in RETRYABLE:
            last = f"http_{response.status_code}"
            time.sleep(2 ** attempt)
            continue
        return None, f"http_{response.status_code}"
    return None, f"exhausted_after_{attempts}:{last}"


def _write_atomic(path: Path, rows: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp{os.getpid()}")
    with tmp.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("date", "swe_in"))
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


def fetch_all(
    cache: Path,
    *,
    begin: date = date(1980, 10, 1),
    end: date = date(2026, 9, 30),
    workers: int = 4,
    session: requests.Session | None = None,
) -> FetchReport:
    """Fetch daily ``WTEQ`` for every envelope station, resumably.

    A station already on disk is skipped. The report reconciles what was
    requested against what is present, because a zero exit status and per-unit
    logging together still cannot tell you a station is absent.
    """
    session = session or open_session()
    stations = list_stations(session)
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "stations.json").write_text(json.dumps(
        [s.__dict__ for s in stations], indent=1
    ))

    def one(station: Station) -> tuple[str, str]:
        target = cache / station.filename
        if target.exists():
            return station.triplet, "cached"
        payload, status = _get(session, {
            "stationTriplets": station.triplet, "elements": "WTEQ",
            "duration": "DAILY", "beginDate": begin.isoformat(),
            "endDate": end.isoformat(),
        })
        if status != "ok":
            return station.triplet, status
        if not payload or not payload[0].get("data"):
            # A real absence, typed as one so it is never read as a failure.
            _write_atomic(target, [])
            return station.triplet, "no_record"
        values = payload[0]["data"][0]["values"]
        _write_atomic(target, [
            (v["date"], "" if v.get("value") is None else v["value"]) for v in values
        ])
        return station.triplet, "ok"

    by_status: dict[str, list[str]] = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for triplet, status in pool.map(one, stations):
            by_status.setdefault(status, []).append(triplet)

    present = {p.name for p in cache.glob("*_CO_SNTL.csv")}
    missing = tuple(s.triplet for s in stations if s.filename not in present)
    return FetchReport(by_status=by_status, missing=missing)


def load_station(path: Path) -> tuple[list[date], list[float]]:
    """Read one cached station. A blank value stays NaN rather than becoming 0."""
    days: list[date] = []
    values: list[float] = []
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            days.append(date.fromisoformat(row["date"]))
            values.append(float(row["swe_in"]) if row["swe_in"] else float("nan"))
    return days, values
