from __future__ import annotations

import os
import time
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np

from .grids import RegularLatLonGrid
from .products import AuthenticationRequired
from .reanalysis_config import ReanalysisModelSpec, ReanalysisRunConfig


@dataclass(frozen=True)
class MonthlyModelField:
    model_id: str
    dates: tuple[date, ...]
    values: np.ndarray

    def for_date(self, day: date) -> np.ndarray:
        try:
            index = self.dates.index(day)
        except ValueError as exc:
            raise KeyError(f"{self.model_id} field does not contain {day}") from exc
        return self.values[index]


def authenticated_cds_client() -> Any:
    """Create a CDS client without accepting or exposing credentials in the CLI."""

    try:
        import cdsapi
    except ImportError as exc:
        raise AuthenticationRequired(
            "cdsapi is required for ERA5 access; install the project dependencies"
        ) from exc

    key = os.environ.get("CDSAPI_KEY")
    config_path = Path(os.environ.get("CDSAPI_RC", Path.home() / ".cdsapirc"))
    if not key and not config_path.is_file():
        raise AuthenticationRequired(
            "Copernicus CDS authentication is required. Configure ~/.cdsapirc "
            "or CDSAPI_KEY after accepting the ERA5 and ERA5-Land licences; "
            "credentials are never accepted as command-line arguments."
        )
    try:
        if key:
            client = cdsapi.Client(
                url=os.environ.get(
                    "CDSAPI_URL", "https://cds.climate.copernicus.eu/api"
                ),
                key=key,
                quiet=True,
                progress=False,
            )
        else:
            client = cdsapi.Client(quiet=True, progress=False)
        return client
    except Exception as exc:
        raise AuthenticationRequired(
            "Copernicus CDS authentication failed; check ~/.cdsapirc or "
            "CDSAPI_KEY and confirm both dataset licences were accepted."
        ) from exc


def build_cds_request(
    spec: ReanalysisModelSpec,
    days: tuple[date, ...],
    config: ReanalysisRunConfig,
) -> dict[str, object]:
    if not days:
        raise ValueError("a CDS request needs at least one date")
    periods = {(day.year, day.month) for day in days}
    if len(periods) != 1:
        raise ValueError("each CDS request must stay within one calendar month")
    year, month = next(iter(periods))
    if len(set(days)) != len(days):
        raise ValueError("CDS request dates must be unique")
    request: dict[str, object] = {
        "variable": list(spec.cds_variables),
        "year": [f"{year:04d}"],
        "month": [f"{month:02d}"],
        "day": [f"{day.day:02d}" for day in sorted(days)],
        "time": [f"{spec.time_hour_utc:02d}:00"],
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": [config.north, config.west, config.south, config.east],
    }
    if spec.product_type is not None:
        request["product_type"] = [spec.product_type]
    return request


def _resolve_download(destination: Path) -> Path:
    if not destination.is_file() or destination.stat().st_size < 100:
        raise OSError(f"CDS returned no usable file at {destination}")
    if not zipfile.is_zipfile(destination):
        return destination
    extraction_directory = destination.parent / f"{destination.name}.unzipped"
    extraction_directory.mkdir()
    with zipfile.ZipFile(destination) as archive:
        unsafe = [
            member
            for member in archive.infolist()
            if Path(member.filename).is_absolute()
            or ".." in Path(member.filename).parts
        ]
        if unsafe:
            raise ValueError("CDS archive contains an unsafe member path")
        archive.extractall(extraction_directory)
    candidates = sorted(
        path
        for path in extraction_directory.rglob("*")
        if path.is_file() and path.suffix.lower() in {".nc", ".nc4"}
    )
    if len(candidates) != 1:
        raise ValueError(
            f"expected one CDS NetCDF member, found {len(candidates)}"
        )
    return candidates[0]


def retrieve_reanalysis_field(
    client: Any,
    spec: ReanalysisModelSpec,
    days: tuple[date, ...],
    config: ReanalysisRunConfig,
    directory: Path,
    retries: int,
) -> Path:
    request = build_cds_request(spec, days, config)
    destination = directory / (
        f"{spec.model_id}_{days[0]:%Y%m}_{spec.time_hour_utc:02d}Z.download"
    )
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            client.retrieve(spec.dataset_id, request, str(destination))
            return _resolve_download(destination)
        except Exception as exc:
            last_error = exc
            destination.unlink(missing_ok=True)
            if attempt + 1 < retries:
                time.sleep(min(2**attempt, 8))
    raise RuntimeError(
        f"failed to retrieve {spec.display_name} fSCA source fields for "
        f"{days[0]:%Y-%m} after {retries} attempts"
    ) from last_error


def _coordinate_name(data_array: Any, candidates: tuple[str, ...]) -> str:
    for name in candidates:
        if name in data_array.dims or name in data_array.coords:
            return name
    raise ValueError(f"NetCDF field lacks a {candidates[0]} coordinate")


def _source_variable(
    dataset: Any,
    spec: ReanalysisModelSpec,
    source_index: int,
) -> Any:
    lower_lookup = {str(name).lower(): name for name in dataset.data_vars}
    candidates = spec.source_variable_candidates[source_index]
    for candidate in candidates:
        key = lower_lookup.get(candidate.lower())
        if key is not None:
            return dataset[key]
    if len(spec.source_variable_candidates) == 1 and len(dataset.data_vars) == 1:
        return dataset[next(iter(dataset.data_vars))]
    raise ValueError(
        f"{spec.display_name} NetCDF lacks expected source variable "
        f"{spec.cds_variables[source_index]!r}; "
        f"found {tuple(dataset.data_vars)}"
    )


@dataclass(frozen=True)
class _DecodedSource:
    values: np.ndarray
    units: str
    latitudes: np.ndarray
    longitudes: np.ndarray
    times: np.ndarray


def _decode_source(
    dataset: Any,
    spec: ReanalysisModelSpec,
    source_index: int,
) -> _DecodedSource:
    field = _source_variable(dataset, spec, source_index)
    time_name = _coordinate_name(field, ("valid_time", "time"))
    latitude_name = _coordinate_name(field, ("latitude", "lat"))
    longitude_name = _coordinate_name(field, ("longitude", "lon"))
    required = {time_name, latitude_name, longitude_name}
    for dimension in tuple(field.dims):
        if dimension in required:
            continue
        if field.sizes[dimension] != 1:
            raise ValueError(
                f"unexpected non-singleton {dimension} dimension in "
                f"{spec.display_name} {spec.cds_variables[source_index]}"
            )
        field = field.isel({dimension: 0}, drop=True)
    field = field.transpose(time_name, latitude_name, longitude_name).load()
    values = np.asarray(field.values, dtype=np.float64)
    units = str(field.attrs.get("units", "")).strip().lower()
    latitudes = np.asarray(field[latitude_name].values, dtype=np.float64)
    longitudes = np.asarray(field[longitude_name].values, dtype=np.float64)
    times = np.asarray(field[time_name].values).astype("datetime64[ns]")

    normalized_longitudes = (longitudes + 180.0) % 360.0 - 180.0
    latitude_order = np.argsort(latitudes)
    longitude_order = np.argsort(normalized_longitudes)
    return _DecodedSource(
        values=values[:, latitude_order, :][:, :, longitude_order],
        units=units,
        latitudes=latitudes[latitude_order],
        longitudes=normalized_longitudes[longitude_order],
        times=times,
    )


def _validate_source_inventory(
    source: _DecodedSource,
    spec: ReanalysisModelSpec,
    grid: RegularLatLonGrid,
    expected_times: np.ndarray,
) -> None:
    if source.values.shape[1:] != grid.shape:
        raise ValueError(
            f"unexpected {spec.display_name} grid shape {source.values.shape[1:]}; "
            f"expected {grid.shape}"
        )
    coordinate_tolerance = min(spec.longitude_step, spec.latitude_step) * 1e-5
    if not np.allclose(
        source.latitudes, grid.lats, rtol=0, atol=coordinate_tolerance
    ):
        raise ValueError(f"{spec.display_name} latitudes do not match target grid")
    if not np.allclose(
        source.longitudes, grid.lons, rtol=0, atol=coordinate_tolerance
    ):
        raise ValueError(f"{spec.display_name} longitudes do not match target grid")
    if (
        source.times.shape != expected_times.shape
        or not np.array_equal(source.times, expected_times)
    ):
        rendered = tuple(
            np.datetime_as_string(value, unit="m") for value in source.times[:3]
        )
        raise ValueError(
            f"{spec.display_name} timestamps differ from requested daily 15Z "
            f"inventory; first returned values={rendered}"
        )


def _direct_snow_cover(source: _DecodedSource, spec: ReanalysisModelSpec) -> np.ndarray:
    values = source.values.copy()
    finite = np.isfinite(values)
    percent_units = (
        source.units in {"%", "percent", "percentage"} or "%" in source.units
    )
    if finite.any() and percent_units:
        values[finite] /= 100.0
    if finite.any():
        minimum = float(values[finite].min())
        maximum = float(values[finite].max())
        if minimum < -1e-4 or maximum > 1.0001:
            raise ValueError(
                f"{spec.display_name} snow cover falls outside 0-1 after "
                f"units-aware conversion (units={source.units!r}): "
                f"[{minimum}, {maximum}]"
            )
        values[finite] = np.clip(values[finite], 0.0, 1.0)
    values[~finite] = np.nan
    return values


def _diagnose_era5_snow_cover(
    snow_depth: _DecodedSource,
    snow_density: _DecodedSource,
) -> np.ndarray:
    """Apply ECMWF's ERA5 gridbox snow-cover diagnostic in fraction units."""

    accepted_depth_units = {"m of water equivalent", "m water equivalent", "mwe"}
    if snow_depth.units not in accepted_depth_units:
        raise ValueError(
            "ERA5 snow_depth must be in metres of water equivalent; "
            f"received units={snow_depth.units!r}"
        )
    compact_density_units = snow_density.units.replace(" ", "")
    if compact_density_units not in {"kgm**-3", "kgm^-3", "kgm-3", "kg/m^3"}:
        raise ValueError(
            "ERA5 snow_density must be in kg m^-3; "
            f"received units={snow_density.units!r}"
        )

    depth = snow_depth.values
    density = snow_density.values
    finite_depth = np.isfinite(depth)
    if np.any(depth[finite_depth] < -1e-8):
        raise ValueError("ERA5 snow_depth contains materially negative values")
    positive_depth = finite_depth & (depth > 1e-12)
    valid_density = np.isfinite(density) & (density > 0.0)
    if np.any(positive_depth & ~valid_density):
        raise ValueError("ERA5 positive snow_depth has missing or nonpositive density")

    values = np.full(depth.shape, np.nan, dtype=np.float64)
    values[finite_depth & ~positive_depth] = 0.0
    diagnosed = 1000.0 * depth[positive_depth] / density[positive_depth] / 0.1
    values[positive_depth] = np.minimum(1.0, diagnosed)
    return values


def load_reanalysis_field(
    path: Path,
    spec: ReanalysisModelSpec,
    grid: RegularLatLonGrid,
    expected_dates: tuple[date, ...],
) -> MonthlyModelField:
    try:
        import xarray as xr
    except ImportError as exc:
        raise RuntimeError("xarray is required to read CDS NetCDF output") from exc

    with xr.open_dataset(path) as dataset:
        sources = tuple(
            _decode_source(dataset, spec, source_index)
            for source_index in range(len(spec.cds_variables))
        )

    expected_times = np.asarray(
        [
            np.datetime64(
                datetime(day.year, day.month, day.day, spec.time_hour_utc), "ns"
            )
            for day in expected_dates
        ]
    )
    for source in sources:
        _validate_source_inventory(source, spec, grid, expected_times)
    if spec.fsca_method == "direct_snow_cover":
        if len(sources) != 1:
            raise ValueError("direct snow-cover products require one source field")
        values = _direct_snow_cover(sources[0], spec)
    elif spec.fsca_method == "era5_depth_density_diagnostic":
        if len(sources) != 2:
            raise ValueError("ERA5 diagnostic requires snow depth and density")
        values = _diagnose_era5_snow_cover(sources[0], sources[1])
    else:
        raise ValueError(f"unknown fSCA method: {spec.fsca_method}")
    return MonthlyModelField(
        model_id=spec.model_id,
        dates=expected_dates,
        values=values,
    )
