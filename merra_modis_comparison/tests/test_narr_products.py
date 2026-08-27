from datetime import date, datetime

import numpy as np
import pytest
from pyproj import Transformer

from merra_modis_comparison.grids import LambertConformalGrid
from merra_modis_comparison.narr_products import (
    NARR_TIME_ORIGIN,
    load_narr_monthly_field,
    narr_opendap_url,
    narr_time_indices,
)
from merra_modis_comparison.reanalysis_config import (
    MODEL_SPECS,
    ReanalysisRunConfig,
)


class _Result:
    def __init__(self, data):
        self.data = np.asarray(data)


class _ArrayVariable:
    def __init__(self, data, attributes=None):
        self._data = np.asarray(data)
        self.attributes = {} if attributes is None else attributes

    def __getitem__(self, key):
        return _Result(self._data[key])


class _GeneratedSnowVariable:
    attributes = {"units": "1"}

    def __getitem__(self, key):
        time_slice, row_slice, column_slice = key
        times = np.arange(2920)[time_slice]
        rows = np.arange(277)[row_slice]
        columns = np.arange(349)[column_slice]
        return _Result(np.full((times.size, rows.size, columns.size), 0.4))


def _fake_narr_dataset(grid: LambertConformalGrid):
    x = grid.x_origin + np.arange(grid.full_width) * grid.x_step
    y = grid.y_origin + np.arange(grid.full_height) * grid.y_step
    xx, yy = np.meshgrid(x, y)
    lon, lat = Transformer.from_crs(
        grid.crs, "EPSG:4326", always_xy=True
    ).transform(xx, yy)
    start = (
        datetime(2023, 1, 1) - NARR_TIME_ORIGIN
    ).total_seconds() / 3600.0
    return {
        "snowc": _GeneratedSnowVariable(),
        "time": _ArrayVariable(start + np.arange(2920) * 3),
        "x": _ArrayVariable(x),
        "y": _ArrayVariable(y),
        "lat": _ArrayVariable(lat),
        "lon": _ArrayVariable(lon),
    }


def test_narr_native_grid_and_time_inventory_match_product_contract():
    config = ReanalysisRunConfig(model_ids=("narr",))
    grid = config.target_grid("narr")
    assert isinstance(grid, LambertConformalGrid)
    assert grid.shape == (185,)
    assert grid.source_window == (98, 112, 168, 182)
    assert grid.cell_metadata(0) == {
        "cell_id": "NARR_y098_x168",
        "target_latitude": 37.209612,
        "target_longitude": -108.973439,
        "target_row": 98,
        "target_column": 168,
    }
    assigned = grid.assign_points(np.asarray(grid.lons), np.asarray(grid.lats))
    assert np.array_equal(assigned, np.arange(grid.size))
    assert np.array_equal(
        narr_time_indices((date(2023, 1, 1), date(2023, 1, 2))),
        [5, 13],
    )
    assert narr_opendap_url(MODEL_SPECS["narr"], 2023).endswith(
        "/snowc.2023.nc"
    )


def test_narr_loader_selects_native_cells_and_validates_15z_coordinates():
    config = ReanalysisRunConfig(model_ids=("narr",))
    grid = config.target_grid("narr")
    assert isinstance(grid, LambertConformalGrid)
    dataset = _fake_narr_dataset(grid)
    days = (date(2023, 1, 1), date(2023, 1, 2))
    loaded = load_narr_monthly_field(
        MODEL_SPECS["narr"],
        grid,
        days,
        validate_coordinates=True,
        opener=lambda *_args, **_kwargs: dataset,
    )
    assert loaded.dates == days
    assert loaded.values.shape == (2, 185)
    assert np.allclose(loaded.values, 0.4)


def test_narr_loader_rejects_non_fraction_units():
    config = ReanalysisRunConfig(model_ids=("narr",))
    grid = config.target_grid("narr")
    assert isinstance(grid, LambertConformalGrid)
    dataset = _fake_narr_dataset(grid)
    dataset["snowc"].attributes = {"units": "%"}
    with pytest.raises(RuntimeError, match="failed to read NARR"):
        load_narr_monthly_field(
            MODEL_SPECS["narr"],
            grid,
            (date(2023, 1, 1),),
            retries=1,
            opener=lambda *_args, **_kwargs: dataset,
        )
