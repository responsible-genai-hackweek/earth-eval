from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from pyproj import CRS, Transformer


class SpatialGrid(Protocol):
    """Model-grid interface used by regridding, checkpoints, and statistics."""

    model_id: str

    @property
    def shape(self) -> tuple[int, ...]: ...

    @property
    def size(self) -> int: ...

    @property
    def geographic_bounds(self) -> tuple[float, float, float, float]: ...

    @property
    def fingerprint_payload(self) -> dict[str, object]: ...

    @property
    def resolution_label(self) -> str: ...

    def assign_points(
        self, longitudes: np.ndarray, latitudes: np.ndarray
    ) -> np.ndarray: ...

    def cell_metadata(self, slot: int) -> dict[str, object]: ...


@dataclass(frozen=True)
class RegularLatLonGrid:
    """A globally aligned regular latitude/longitude target-grid subset.

    Coordinates are stored south-to-north and west-to-east so flattened arrays
    always use stable row-major order, even when a source NetCDF file stores
    latitude in descending order.
    """

    model_id: str
    lons: tuple[float, ...]
    lats: tuple[float, ...]
    longitude_step: float
    latitude_step: float

    def __post_init__(self) -> None:
        if not self.model_id:
            raise ValueError("model_id cannot be empty")
        if not self.lons or not self.lats:
            raise ValueError("a target grid must contain at least one cell")
        if self.longitude_step <= 0 or self.latitude_step <= 0:
            raise ValueError("grid spacing must be positive")
        if len(self.lons) > 1 and not np.allclose(
            np.diff(self.lons), self.longitude_step, rtol=0, atol=1e-10
        ):
            raise ValueError("longitude centers do not match the configured spacing")
        if len(self.lats) > 1 and not np.allclose(
            np.diff(self.lats), self.latitude_step, rtol=0, atol=1e-10
        ):
            raise ValueError("latitude centers do not match the configured spacing")

    @classmethod
    def from_domain(
        cls,
        model_id: str,
        west: float,
        east: float,
        south: float,
        north: float,
        longitude_step: float,
        latitude_step: float,
    ) -> "RegularLatLonGrid":
        """Select globally zero-anchored cell centers inside the domain bounds."""

        tolerance = 1e-10
        first_lon = int(np.ceil(west / longitude_step - tolerance))
        last_lon = int(np.floor(east / longitude_step + tolerance))
        first_lat = int(np.ceil(south / latitude_step - tolerance))
        last_lat = int(np.floor(north / latitude_step + tolerance))
        if first_lon > last_lon or first_lat > last_lat:
            raise ValueError(f"domain contains no {model_id} grid-cell centers")
        lons = tuple(
            float(round(index * longitude_step, 10))
            for index in range(first_lon, last_lon + 1)
        )
        lats = tuple(
            float(round(index * latitude_step, 10))
            for index in range(first_lat, last_lat + 1)
        )
        return cls(
            model_id=model_id,
            lons=lons,
            lats=lats,
            longitude_step=longitude_step,
            latitude_step=latitude_step,
        )

    @property
    def shape(self) -> tuple[int, int]:
        return (len(self.lats), len(self.lons))

    @property
    def size(self) -> int:
        return len(self.lats) * len(self.lons)

    @property
    def lon_edges(self) -> np.ndarray:
        centers = np.asarray(self.lons, dtype=np.float64)
        return np.concatenate(
            ([centers[0] - self.longitude_step / 2], centers + self.longitude_step / 2)
        )

    @property
    def lat_edges(self) -> np.ndarray:
        centers = np.asarray(self.lats, dtype=np.float64)
        return np.concatenate(
            ([centers[0] - self.latitude_step / 2], centers + self.latitude_step / 2)
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
        return {"lons": self.lons, "lats": self.lats}

    @property
    def resolution_label(self) -> str:
        return f"{self.longitude_step:g}° × {self.latitude_step:g}°"

    def assign_points(
        self, longitudes: np.ndarray, latitudes: np.ndarray
    ) -> np.ndarray:
        if longitudes.shape != latitudes.shape:
            raise ValueError("longitude and latitude point arrays must match")
        finite = np.isfinite(longitudes) & np.isfinite(latitudes)
        lon_bin = np.full(longitudes.shape, -1, dtype=np.int64)
        lat_bin = np.full(latitudes.shape, -1, dtype=np.int64)
        lon_bin[finite] = np.floor(
            (longitudes[finite] - self.lon_edges[0]) / self.longitude_step
        ).astype(np.int64)
        lat_bin[finite] = np.floor(
            (latitudes[finite] - self.lat_edges[0]) / self.latitude_step
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
        latitude = self.lats[row]
        longitude = self.lons[column]
        prefix = self.model_id.upper().replace("-", "_")
        return {
            "cell_id": f"{prefix}_lat{latitude:+.2f}_lon{longitude:+.2f}",
            "target_latitude": latitude,
            "target_longitude": longitude,
            "target_row": row,
            "target_column": column,
        }


@dataclass(frozen=True)
class LambertConformalGrid:
    """A center-selected subset of a native Lambert conformal model grid."""

    model_id: str
    lons: tuple[float, ...]
    lats: tuple[float, ...]
    source_rows: tuple[int, ...]
    source_columns: tuple[int, ...]
    x_origin: float
    y_origin: float
    x_step: float
    y_step: float
    full_width: int
    full_height: int
    latitude_of_projection_origin: float
    longitude_of_central_meridian: float
    standard_parallel: tuple[float, float]
    false_easting: float
    false_northing: float
    earth_radius: float

    def __post_init__(self) -> None:
        lengths = {
            len(self.lons),
            len(self.lats),
            len(self.source_rows),
            len(self.source_columns),
        }
        if lengths == {0} or len(lengths) != 1:
            raise ValueError("Lambert-grid cell coordinate arrays must be nonempty")
        if self.x_step <= 0 or self.y_step <= 0:
            raise ValueError("Lambert-grid spacing must be positive")
        if self.full_width < 1 or self.full_height < 1:
            raise ValueError("Lambert-grid full dimensions must be positive")
        if any(not 0 <= row < self.full_height for row in self.source_rows):
            raise ValueError("Lambert-grid source row is outside the full grid")
        if any(not 0 <= column < self.full_width for column in self.source_columns):
            raise ValueError("Lambert-grid source column is outside the full grid")
        pairs = tuple(zip(self.source_rows, self.source_columns, strict=True))
        if len(set(pairs)) != len(pairs):
            raise ValueError("Lambert-grid source cells must be unique")

    @classmethod
    def from_domain(
        cls,
        model_id: str,
        west: float,
        east: float,
        south: float,
        north: float,
        *,
        x_origin: float,
        y_origin: float,
        x_step: float,
        y_step: float,
        full_width: int,
        full_height: int,
        latitude_of_projection_origin: float,
        longitude_of_central_meridian: float,
        standard_parallel: tuple[float, float],
        false_easting: float,
        false_northing: float,
        earth_radius: float,
    ) -> "LambertConformalGrid":
        crs = cls._build_crs(
            latitude_of_projection_origin,
            longitude_of_central_meridian,
            standard_parallel,
            false_easting,
            false_northing,
            earth_radius,
        )
        transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        x = x_origin + np.arange(full_width, dtype=np.float64) * x_step
        y = y_origin + np.arange(full_height, dtype=np.float64) * y_step
        xx, yy = np.meshgrid(x, y)
        longitudes, latitudes = transformer.transform(xx, yy)
        selected = (
            (longitudes >= west)
            & (longitudes <= east)
            & (latitudes >= south)
            & (latitudes <= north)
        )
        rows, columns = np.nonzero(selected)
        if rows.size == 0:
            raise ValueError(f"domain contains no {model_id} Lambert-grid centers")
        return cls(
            model_id=model_id,
            lons=tuple(float(round(value, 6)) for value in longitudes[selected]),
            lats=tuple(float(round(value, 6)) for value in latitudes[selected]),
            source_rows=tuple(int(value) for value in rows),
            source_columns=tuple(int(value) for value in columns),
            x_origin=x_origin,
            y_origin=y_origin,
            x_step=x_step,
            y_step=y_step,
            full_width=full_width,
            full_height=full_height,
            latitude_of_projection_origin=latitude_of_projection_origin,
            longitude_of_central_meridian=longitude_of_central_meridian,
            standard_parallel=standard_parallel,
            false_easting=false_easting,
            false_northing=false_northing,
            earth_radius=earth_radius,
        )

    @staticmethod
    def _build_crs(
        latitude_of_projection_origin: float,
        longitude_of_central_meridian: float,
        standard_parallel: tuple[float, float],
        false_easting: float,
        false_northing: float,
        earth_radius: float,
    ) -> CRS:
        return CRS.from_proj4(
            "+proj=lcc "
            f"+lat_1={standard_parallel[0]} +lat_2={standard_parallel[1]} "
            f"+lat_0={latitude_of_projection_origin} "
            f"+lon_0={longitude_of_central_meridian} "
            f"+x_0={false_easting} +y_0={false_northing} "
            f"+R={earth_radius} +units=m +no_defs"
        )

    @property
    def crs(self) -> CRS:
        return self._build_crs(
            self.latitude_of_projection_origin,
            self.longitude_of_central_meridian,
            self.standard_parallel,
            self.false_easting,
            self.false_northing,
            self.earth_radius,
        )

    @property
    def shape(self) -> tuple[int, ...]:
        return (self.size,)

    @property
    def size(self) -> int:
        return len(self.lons)

    @property
    def source_window(self) -> tuple[int, int, int, int]:
        return (
            min(self.source_rows),
            max(self.source_rows) + 1,
            min(self.source_columns),
            max(self.source_columns) + 1,
        )

    @property
    def geographic_bounds(self) -> tuple[float, float, float, float]:
        rows = np.asarray(self.source_rows, dtype=np.float64)
        columns = np.asarray(self.source_columns, dtype=np.float64)
        center_x = self.x_origin + columns * self.x_step
        center_y = self.y_origin + rows * self.y_step
        x = np.concatenate(
            (
                center_x - self.x_step / 2,
                center_x - self.x_step / 2,
                center_x + self.x_step / 2,
                center_x + self.x_step / 2,
            )
        )
        y = np.concatenate(
            (
                center_y - self.y_step / 2,
                center_y + self.y_step / 2,
                center_y - self.y_step / 2,
                center_y + self.y_step / 2,
            )
        )
        longitude, latitude = Transformer.from_crs(
            self.crs, "EPSG:4326", always_xy=True
        ).transform(x, y)
        return (
            float(np.min(longitude)),
            float(np.min(latitude)),
            float(np.max(longitude)),
            float(np.max(latitude)),
        )

    @property
    def fingerprint_payload(self) -> dict[str, object]:
        return {
            "grid_kind": "lambert_conformal",
            "lons": self.lons,
            "lats": self.lats,
            "source_rows": self.source_rows,
            "source_columns": self.source_columns,
            "x_origin": self.x_origin,
            "y_origin": self.y_origin,
            "x_step": self.x_step,
            "y_step": self.y_step,
            "full_width": self.full_width,
            "full_height": self.full_height,
            "latitude_of_projection_origin": self.latitude_of_projection_origin,
            "longitude_of_central_meridian": self.longitude_of_central_meridian,
            "standard_parallel": self.standard_parallel,
            "false_easting": self.false_easting,
            "false_northing": self.false_northing,
            "earth_radius": self.earth_radius,
        }

    @property
    def resolution_label(self) -> str:
        return f"{self.x_step / 1000:g} km native Lambert"

    def assign_points(
        self, longitudes: np.ndarray, latitudes: np.ndarray
    ) -> np.ndarray:
        if longitudes.shape != latitudes.shape:
            raise ValueError("longitude and latitude point arrays must match")
        x, y = Transformer.from_crs(
            "EPSG:4326", self.crs, always_xy=True
        ).transform(longitudes, latitudes)
        finite = np.isfinite(x) & np.isfinite(y)
        rows = np.full(longitudes.shape, -1, dtype=np.int64)
        columns = np.full(longitudes.shape, -1, dtype=np.int64)
        rows[finite] = np.floor(
            (y[finite] - (self.y_origin - self.y_step / 2)) / self.y_step
        ).astype(np.int64)
        columns[finite] = np.floor(
            (x[finite] - (self.x_origin - self.x_step / 2)) / self.x_step
        ).astype(np.int64)
        inside = (
            finite
            & (rows >= 0)
            & (rows < self.full_height)
            & (columns >= 0)
            & (columns < self.full_width)
        )
        lookup = np.full((self.full_height, self.full_width), -1, dtype=np.int32)
        lookup[self.source_rows, self.source_columns] = np.arange(
            self.size, dtype=np.int32
        )
        target = np.full(longitudes.shape, -1, dtype=np.int32)
        target[inside] = lookup[rows[inside], columns[inside]]
        return target

    def cell_metadata(self, slot: int) -> dict[str, object]:
        if not 0 <= slot < self.size:
            raise IndexError(f"cell slot {slot} is outside a {self.size}-cell grid")
        row = self.source_rows[slot]
        column = self.source_columns[slot]
        prefix = self.model_id.upper().replace("-", "_")
        return {
            "cell_id": f"{prefix}_y{row:03d}_x{column:03d}",
            "target_latitude": self.lats[slot],
            "target_longitude": self.lons[slot],
            "target_row": row,
            "target_column": column,
        }
