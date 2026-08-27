from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any, Callable

import numpy as np

from .era_products import MonthlyModelField
from .grids import LambertConformalGrid
from .reanalysis_config import ReanalysisModelSpec


NARR_TIME_ORIGIN = datetime(1800, 1, 1)
NARR_ANALYSES_PER_DAY = 8


def narr_opendap_url(spec: ReanalysisModelSpec, year: int) -> str:
    if spec.access_backend != "noaa_psl_opendap" or spec.source_url_template is None:
        raise ValueError(f"{spec.display_name} is not configured for NOAA OPeNDAP")
    return spec.source_url_template.format(year=year)


def narr_time_indices(
    days: tuple[date, ...], hour_utc: int = 15
) -> np.ndarray:
    if not days:
        raise ValueError("a NARR request needs at least one date")
    if len(set(days)) != len(days) or tuple(sorted(days)) != days:
        raise ValueError("NARR request dates must be unique and sorted")
    if len({day.year for day in days}) != 1:
        raise ValueError("each NARR request must stay within one calendar year")
    if hour_utc not in range(0, 24, 3):
        raise ValueError("NARR analysis hours occur every three hours")
    year_start = date(days[0].year, 1, 1)
    return np.asarray(
        [
            (day - year_start).days * NARR_ANALYSES_PER_DAY + hour_utc // 3
            for day in days
        ],
        dtype=np.int64,
    )


def _materialize(value: Any) -> np.ndarray:
    if isinstance(value, np.ndarray):
        return value
    return np.asarray(getattr(value, "data", value))


def _variable_attributes(variable: Any) -> dict[str, object]:
    attributes = getattr(variable, "attributes", {})
    return dict(attributes) if attributes is not None else {}


def _expected_time_hours(days: tuple[date, ...], hour_utc: int) -> np.ndarray:
    return np.asarray(
        [
            (
                datetime(day.year, day.month, day.day, hour_utc)
                - NARR_TIME_ORIGIN
            ).total_seconds()
            / 3600.0
            for day in days
        ],
        dtype=np.float64,
    )


def _validate_remote_grid(dataset: Any, grid: LambertConformalGrid) -> None:
    row_start, row_stop, column_start, column_stop = grid.source_window
    remote_x = np.asarray(
        _materialize(dataset["x"][column_start:column_stop]), dtype=np.float64
    ).squeeze()
    remote_y = np.asarray(
        _materialize(dataset["y"][row_start:row_stop]), dtype=np.float64
    ).squeeze()
    expected_x = grid.x_origin + np.arange(
        column_start, column_stop, dtype=np.float64
    ) * grid.x_step
    expected_y = grid.y_origin + np.arange(
        row_start, row_stop, dtype=np.float64
    ) * grid.y_step
    if not np.allclose(remote_x, expected_x, rtol=0, atol=1e-3):
        raise ValueError("remote NARR x coordinates differ from the target grid")
    if not np.allclose(remote_y, expected_y, rtol=0, atol=1e-3):
        raise ValueError("remote NARR y coordinates differ from the target grid")

    remote_latitudes = np.asarray(
        _materialize(
            dataset["lat"][row_start:row_stop, column_start:column_stop]
        ),
        dtype=np.float64,
    )
    remote_longitudes = np.asarray(
        _materialize(
            dataset["lon"][row_start:row_stop, column_start:column_stop]
        ),
        dtype=np.float64,
    )
    local_rows = np.asarray(grid.source_rows) - row_start
    local_columns = np.asarray(grid.source_columns) - column_start
    if not np.allclose(
        remote_latitudes[local_rows, local_columns],
        grid.lats,
        rtol=0,
        atol=2e-3,
    ):
        raise ValueError("remote NARR latitudes differ from selected cell centers")
    if not np.allclose(
        remote_longitudes[local_rows, local_columns],
        grid.lons,
        rtol=0,
        atol=2e-3,
    ):
        raise ValueError("remote NARR longitudes differ from selected cell centers")


def _read_narr_dataset(
    dataset: Any,
    spec: ReanalysisModelSpec,
    grid: LambertConformalGrid,
    days: tuple[date, ...],
    *,
    validate_coordinates: bool,
) -> MonthlyModelField:
    indices = narr_time_indices(days, spec.time_hour_utc)
    if indices.size > 1 and not np.all(np.diff(indices) == NARR_ANALYSES_PER_DAY):
        raise ValueError("a NARR monthly request must contain consecutive dates")
    row_start, row_stop, column_start, column_stop = grid.source_window
    first = int(indices[0])
    stop = int(indices[-1] + 1)
    variable = dataset[spec.variable]
    attributes = _variable_attributes(variable)
    units = str(attributes.get("units", "")).strip()
    if units != "1":
        raise ValueError(f"NARR snowc must use fraction units '1'; received {units!r}")
    values = np.asarray(
        _materialize(
            variable[
                first:stop:NARR_ANALYSES_PER_DAY,
                row_start:row_stop,
                column_start:column_stop,
            ]
        ),
        dtype=np.float64,
    )
    expected_shape = (
        len(days),
        row_stop - row_start,
        column_stop - column_start,
    )
    if values.shape != expected_shape:
        raise ValueError(
            f"unexpected NARR subset shape {values.shape}; expected {expected_shape}"
        )
    missing = (values < -1e20) | (values > 1e20) | ~np.isfinite(values)
    values[missing] = np.nan
    finite = np.isfinite(values)
    if finite.any() and (
        float(values[finite].min()) < -1e-6
        or float(values[finite].max()) > 1.000001
    ):
        raise ValueError("NARR snowc falls outside its documented 0-1 range")
    values[finite] = np.clip(values[finite], 0.0, 1.0)

    remote_time = np.asarray(
        _materialize(dataset["time"][first:stop:NARR_ANALYSES_PER_DAY]),
        dtype=np.float64,
    ).squeeze()
    remote_time = np.atleast_1d(remote_time)
    expected_time = _expected_time_hours(days, spec.time_hour_utc)
    if remote_time.shape != expected_time.shape or not np.allclose(
        remote_time, expected_time, rtol=0, atol=1e-6
    ):
        raise ValueError("NARR timestamps differ from the requested daily 15Z inventory")
    if validate_coordinates:
        _validate_remote_grid(dataset, grid)

    local_rows = np.asarray(grid.source_rows) - row_start
    local_columns = np.asarray(grid.source_columns) - column_start
    selected = values[:, local_rows, local_columns]
    return MonthlyModelField(
        model_id=spec.model_id,
        dates=days,
        values=selected,
    )


def load_narr_monthly_field(
    spec: ReanalysisModelSpec,
    grid: LambertConformalGrid,
    days: tuple[date, ...],
    retries: int = 4,
    *,
    validate_coordinates: bool = False,
    opener: Callable[..., Any] | None = None,
) -> MonthlyModelField:
    """Read one month of exact-15Z NARR snow cover without caching raw data."""

    if not days:
        raise ValueError("a NARR monthly request needs at least one date")
    if retries < 1:
        raise ValueError("NARR retries must be at least 1")
    if opener is None:
        try:
            from pydap.client import open_url
        except ImportError as exc:
            raise RuntimeError("pydap is required for NOAA PSL NARR access") from exc
        opener = open_url
    url = narr_opendap_url(spec, days[0].year)
    dap_url = "dap2://" + url.removeprefix("https://").removeprefix("http://")
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            dataset = opener(dap_url, timeout=120)
            return _read_narr_dataset(
                dataset,
                spec,
                grid,
                days,
                validate_coordinates=validate_coordinates,
            )
        except Exception as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(min(2**attempt, 8))
    raise RuntimeError(
        f"failed to read NARR snowc for {days[0]:%Y-%m} after {retries} attempts"
    ) from last_error
