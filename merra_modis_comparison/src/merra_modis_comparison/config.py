from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np


MERRA_LON_STEP = 0.625
MERRA_LAT_STEP = 0.5
MERRA_LONS = np.arange(-180.0, 180.0, MERRA_LON_STEP)
MERRA_LATS = np.arange(-90.0, 90.0 + MERRA_LAT_STEP, MERRA_LAT_STEP)


@dataclass(frozen=True)
class TargetGrid:
    lons: tuple[float, ...]
    lats: tuple[float, ...]
    lon_indices: tuple[int, ...]
    lat_indices: tuple[int, ...]

    @property
    def model_id(self) -> str:
        return "merra2"

    @property
    def shape(self) -> tuple[int, int]:
        return (len(self.lats), len(self.lons))

    @property
    def size(self) -> int:
        return len(self.lats) * len(self.lons)

    @property
    def lon_edges(self) -> np.ndarray:
        centers = np.asarray(self.lons)
        return np.concatenate(
            ([centers[0] - MERRA_LON_STEP / 2], centers + MERRA_LON_STEP / 2)
        )

    @property
    def lat_edges(self) -> np.ndarray:
        centers = np.asarray(self.lats)
        return np.concatenate(
            ([centers[0] - MERRA_LAT_STEP / 2], centers + MERRA_LAT_STEP / 2)
        )

    @property
    def geographic_bounds(self) -> tuple[float, float, float, float]:
        return (
            float(self.lon_edges[0]),
            float(self.lat_edges[0]),
            float(self.lon_edges[-1]),
            float(self.lat_edges[-1]),
        )

    @property
    def fingerprint_payload(self) -> dict[str, object]:
        return {
            "lons": self.lons,
            "lats": self.lats,
            "lon_indices": self.lon_indices,
            "lat_indices": self.lat_indices,
        }

    @property
    def resolution_label(self) -> str:
        return f"{MERRA_LON_STEP:g}° × {MERRA_LAT_STEP:g}°"

    @property
    def lat_slice(self) -> slice:
        return slice(self.lat_indices[0], self.lat_indices[-1] + 1)

    @property
    def lon_slice(self) -> slice:
        return slice(self.lon_indices[0], self.lon_indices[-1] + 1)

    def assign_points(
        self, longitudes: np.ndarray, latitudes: np.ndarray
    ) -> np.ndarray:
        if longitudes.shape != latitudes.shape:
            raise ValueError("longitude and latitude point arrays must match")
        finite = np.isfinite(longitudes) & np.isfinite(latitudes)
        lon_bin = np.full(longitudes.shape, -1, dtype=np.int64)
        lat_bin = np.full(latitudes.shape, -1, dtype=np.int64)
        lon_bin[finite] = np.floor(
            (longitudes[finite] - self.lon_edges[0]) / MERRA_LON_STEP
        ).astype(np.int64)
        lat_bin[finite] = np.floor(
            (latitudes[finite] - self.lat_edges[0]) / MERRA_LAT_STEP
        ).astype(np.int64)
        inside = (
            finite
            & (longitudes >= self.lon_edges[0])
            & (longitudes < self.lon_edges[-1])
            & (latitudes >= self.lat_edges[0])
            & (latitudes < self.lat_edges[-1])
            & (lon_bin >= 0)
            & (lon_bin < len(self.lons))
            & (lat_bin >= 0)
            & (lat_bin < len(self.lats))
        )
        target = np.full(longitudes.shape, -1, dtype=np.int32)
        target[inside] = lat_bin[inside] * len(self.lons) + lon_bin[inside]
        return target

    def cell_metadata(self, slot: int) -> dict[str, object]:
        if not 0 <= slot < self.size:
            raise IndexError(f"cell slot {slot} is outside a {self.size}-cell grid")
        row, column = divmod(slot, len(self.lons))
        latitude_index = self.lat_indices[row]
        longitude_index = self.lon_indices[column]
        return {
            "cell_id": f"MERRA2_i{latitude_index:03d}_j{longitude_index:03d}",
            "merra_latitude": self.lats[row],
            "merra_longitude": self.lons[column],
            "merra_latitude_index": latitude_index,
            "merra_longitude_index": longitude_index,
        }


@dataclass(frozen=True)
class RunConfig:
    start_water_year: int = 2010
    end_water_year: int = 2023
    west: float = -109.0
    east: float = -104.0
    south: float = 37.0
    north: float = 41.0
    workers: int = 16
    ftp_connections: int = 8
    support_threshold: float = 0.8
    merra_time_index: int = 15
    retries: int = 4
    month_attempts: int = 2

    def validate(self) -> None:
        if self.start_water_year < 2001:
            raise ValueError("STC-MODSCAG water years begin after 2000-03-01")
        if self.end_water_year < self.start_water_year:
            raise ValueError("end water year must be at least the start water year")
        if self.end_water_year > 2023:
            raise ValueError(
                "STC_MODSCGDRF_HIST v1 ends 2023-09-30; end water year must be <= 2023"
            )
        if not (-180 <= self.west < self.east <= 180):
            raise ValueError("expected -180 <= west < east <= 180")
        if not (-90 <= self.south < self.north <= 90):
            raise ValueError("expected -90 <= south < north <= 90")
        if not (1 <= self.workers <= 20):
            raise ValueError("workers must be between 1 and 20")
        if not (1 <= self.ftp_connections <= 9):
            raise ValueError(
                "FTP connections must be between 1 and 9 to remain below "
                "the MODSCAG archive's 10-connection per-IP limit"
            )
        if not (0 < self.support_threshold <= 1):
            raise ValueError("support threshold must be in (0, 1]")
        if self.merra_time_index != 15:
            raise ValueError("the reviewed daily contract requires MERRA time index 15")
        if self.retries < 1:
            raise ValueError("retries must be at least 1")
        if self.month_attempts < 1:
            raise ValueError("month attempts must be at least 1")

    @property
    def water_years(self) -> tuple[int, ...]:
        return tuple(range(self.start_water_year, self.end_water_year + 1))

    @property
    def start_date(self) -> date:
        return date(self.start_water_year - 1, 10, 1)

    @property
    def end_date(self) -> date:
        return date(self.end_water_year, 9, 30)

    @property
    def dates(self) -> tuple[date, ...]:
        n = (self.end_date - self.start_date).days + 1
        return tuple(self.start_date + timedelta(days=i) for i in range(n))

    @property
    def calendar_months(self) -> tuple[tuple[int, int], ...]:
        months: list[tuple[int, int]] = []
        year, month = self.start_date.year, self.start_date.month
        end = (self.end_date.year, self.end_date.month)
        while (year, month) <= end:
            months.append((year, month))
            if month == 12:
                year, month = year + 1, 1
            else:
                month += 1
        return tuple(months)

    @property
    def target_grid(self) -> TargetGrid:
        lon_idx = np.flatnonzero((MERRA_LONS >= self.west) & (MERRA_LONS <= self.east))
        lat_idx = np.flatnonzero((MERRA_LATS >= self.south) & (MERRA_LATS <= self.north))
        if lon_idx.size == 0 or lat_idx.size == 0:
            raise ValueError("domain contains no MERRA-2 grid-cell centers")
        if np.any(np.diff(lon_idx) != 1) or np.any(np.diff(lat_idx) != 1):
            raise ValueError("target grid must be contiguous")
        return TargetGrid(
            lons=tuple(float(v) for v in MERRA_LONS[lon_idx]),
            lats=tuple(float(v) for v in MERRA_LATS[lat_idx]),
            lon_indices=tuple(int(v) for v in lon_idx),
            lat_indices=tuple(int(v) for v in lat_idx),
        )

    @property
    def domain_label(self) -> str:
        return (
            f"centers:{self.west:g},{self.east:g}E;"
            f"{self.south:g},{self.north:g}N"
        )


def water_year_for_date(day: date) -> int:
    return day.year + 1 if day.month >= 10 else day.year


def season_for_month(month: int) -> str:
    if month in (12, 1, 2):
        return "DJF"
    if month in (3, 4, 5):
        return "MAM"
    if month in (6, 7, 8):
        return "JJA"
    return "SON"
