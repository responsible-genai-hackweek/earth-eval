from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


class SpatialGrid(Protocol):
    """Minimum regular-grid interface used by the MODSCAG reducer."""

    lons: tuple[float, ...]
    lats: tuple[float, ...]

    @property
    def shape(self) -> tuple[int, int]: ...

    @property
    def size(self) -> int: ...

    @property
    def lon_edges(self) -> np.ndarray: ...

    @property
    def lat_edges(self) -> np.ndarray: ...


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
