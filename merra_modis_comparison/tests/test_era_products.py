from datetime import date

import numpy as np
import pytest
import xarray as xr

from merra_modis_comparison.era_products import (
    build_cds_request,
    load_reanalysis_field,
)
from merra_modis_comparison.reanalysis_config import (
    MODEL_SPECS,
    ReanalysisRunConfig,
)


def test_cds_requests_match_each_official_catalogue_schema():
    config = ReanalysisRunConfig()
    days = (date(2023, 1, 1), date(2023, 1, 2))
    era5 = build_cds_request(MODEL_SPECS["era5"], days, config)
    era5_land = build_cds_request(MODEL_SPECS["era5-land"], days, config)
    assert era5["variable"] == ["snow_depth", "snow_density"]
    assert era5["time"] == ["15:00"]
    assert era5["area"] == [41.0, -109.0, 37.0, -104.0]
    assert era5["product_type"] == ["reanalysis"]
    assert "product_type" not in era5_land
    assert era5_land["variable"] == ["snow_cover"]
    assert era5_land["data_format"] == "netcdf"
    assert era5_land["download_format"] == "unarchived"


def _write_synthetic_era5(
    path,
    times,
    snow_depth=0.015,
    snow_density=300.0,
    depth_units="m of water equivalent",
    density_units="kg m**-3",
):
    dataset = xr.Dataset(
        {
            "sd": (
                ("valid_time", "latitude", "longitude"),
                np.full((len(times), 3, 3), snow_depth),
                {"units": depth_units},
            ),
            "rsn": (
                ("valid_time", "latitude", "longitude"),
                np.full((len(times), 3, 3), snow_density),
                {"units": density_units},
            ),
        },
        coords={
            "valid_time": np.asarray(times, dtype="datetime64[ns]"),
            "latitude": [37.5, 37.25, 37.0],
            "longitude": [251.0, 251.25, 251.5],
        },
    )
    dataset.to_netcdf(path, engine="h5netcdf")


def _write_synthetic_era5_land(path, times, value=0.5, units=None):
    attributes = {} if units is None else {"units": units}
    dataset = xr.Dataset(
        {
            "snowc": (
                ("valid_time", "latitude", "longitude"),
                np.full((len(times), 3, 3), value),
                attributes,
            )
        },
        coords={
            "valid_time": np.asarray(times, dtype="datetime64[ns]"),
            "latitude": [37.2, 37.1, 37.0],
            "longitude": [251.0, 251.1, 251.2],
        },
    )
    dataset.to_netcdf(path, engine="h5netcdf")


def test_load_reanalysis_field_normalizes_coordinates_and_validates_15z(tmp_path):
    config = ReanalysisRunConfig(
        model_ids=("era5",), west=-109, east=-108.5, south=37, north=37.5
    )
    spec = MODEL_SPECS["era5"]
    expected = (date(2023, 1, 1), date(2023, 1, 2))
    path = tmp_path / "era5.nc"
    _write_synthetic_era5(path, ["2023-01-01T15:00", "2023-01-02T15:00"])
    loaded = load_reanalysis_field(path, spec, config.target_grid("era5"), expected)
    assert loaded.values.shape == (2, 3, 3)
    assert np.allclose(loaded.values, 0.5)
    assert np.allclose(config.target_grid("era5").lons, [-109, -108.75, -108.5])


def test_era5_diagnostic_uses_documented_depth_density_formula_and_caps_at_one(
    tmp_path,
):
    config = ReanalysisRunConfig(
        model_ids=("era5",), west=-109, east=-108.5, south=37, north=37.5
    )
    path = tmp_path / "era5-deep-snow.nc"
    _write_synthetic_era5(
        path,
        ["2023-01-01T15:00"],
        snow_depth=0.06,
        snow_density=300.0,
    )
    loaded = load_reanalysis_field(
        path,
        MODEL_SPECS["era5"],
        config.target_grid("era5"),
        (date(2023, 1, 1),),
    )
    assert np.allclose(loaded.values, 1.0)


def test_era5_diagnostic_requires_documented_source_units(tmp_path):
    config = ReanalysisRunConfig(
        model_ids=("era5",), west=-109, east=-108.5, south=37, north=37.5
    )
    path = tmp_path / "wrong-units.nc"
    _write_synthetic_era5(
        path,
        ["2023-01-01T15:00"],
        depth_units="cm",
    )
    with pytest.raises(ValueError, match="water equivalent"):
        load_reanalysis_field(
            path,
            MODEL_SPECS["era5"],
            config.target_grid("era5"),
            (date(2023, 1, 1),),
        )


def test_load_reanalysis_field_rejects_non_15z_file(tmp_path):
    config = ReanalysisRunConfig(
        model_ids=("era5",), west=-109, east=-108.5, south=37, north=37.5
    )
    path = tmp_path / "wrong-time.nc"
    _write_synthetic_era5(path, ["2023-01-01T14:00"])
    with pytest.raises(ValueError, match="15Z"):
        load_reanalysis_field(
            path,
            MODEL_SPECS["era5"],
            config.target_grid("era5"),
            (date(2023, 1, 1),),
        )


def test_load_reanalysis_field_converts_documented_percent_units(tmp_path):
    config = ReanalysisRunConfig(
        model_ids=("era5-land",), west=-109, east=-108.8, south=37, north=37.2
    )
    path = tmp_path / "percent.nc"
    _write_synthetic_era5_land(
        path, ["2023-01-01T15:00"], value=50.0, units="%"
    )
    loaded = load_reanalysis_field(
        path,
        MODEL_SPECS["era5-land"],
        config.target_grid("era5-land"),
        (date(2023, 1, 1),),
    )
    assert np.allclose(loaded.values, 0.5)
