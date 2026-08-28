import inspect
import os
from datetime import date

import numpy as np
import pytest
import xarray as xr

from fsca_eval import checkpoint, config, dates, earthdata, examples, metrics, pipeline, regrid, worker


def _build_full_domain_mapping(n_per_cell=2):
    lons, lats = [], []
    for lon_idx in range(config.N_LON_CELLS):
        for lat_idx in range(config.N_LAT_CELLS):
            lons.extend([config.CELL_LON_CENTERS[lon_idx]] * n_per_cell)
            lats.extend([config.CELL_LAT_CENTERS[lat_idx]] * n_per_cell)
    lon = np.array(lons)
    lat = np.array(lats)
    mapping = regrid.build_mapping(lon, lat)
    return mapping, len(lon)


class FakeTransport:
    def __init__(self, n_pixels, snow_fraction=40.0, merra_value=0.5, merra_grid=None):
        self.n_pixels = n_pixels
        self.snow_fraction = snow_fraction
        self.merra_value = merra_value
        self.merra_grid = merra_grid

    def fetch_merra_subset(self, d, stream):
        if self.merra_grid is not None:
            frsno = self.merra_grid
        else:
            frsno = np.full((config.N_LAT_CELLS, config.N_LON_CELLS), self.merra_value)
        return earthdata.MerraSubset(
            frsno=frsno,
            lon_centers=np.array(config.CELL_LON_CENTERS),
            lat_centers=np.array(config.CELL_LAT_CENTERS),
            stream=stream,
        )

    def fetch_modscag_tiles(self, d, tmp_dir):
        snow = np.full(self.n_pixels, self.snow_fraction)
        days_without_obs = np.zeros(self.n_pixels)
        tile = earthdata.ModscagTile(
            pixel_x_sinusoidal=np.zeros(self.n_pixels),
            pixel_y_sinusoidal=np.zeros(self.n_pixels),
            snow_fraction=snow,
            days_without_observation=days_without_obs,
        )
        return [tile]


def _setup(tmp_path, transport, n_per_cell=2):
    mapping, _ = _build_full_domain_mapping(n_per_cell=n_per_cell)
    results_dir = str(tmp_path / "results")
    tmp_dir_root = str(tmp_path / "tmp")
    os.makedirs(tmp_dir_root, exist_ok=True)
    return mapping, results_dir, tmp_dir_root


def test_generate_example_cross_check_passes_against_matching_checkpoint(tmp_path):
    mapping, results_dir, tmp_dir_root = _setup(tmp_path, None, n_per_cell=4)
    transport = FakeTransport(mapping.pixel_cell_id.shape[0], snow_fraction=40.0, merra_value=0.5)
    d = date(2020, 2, 15)
    water_year = dates.water_year_of(d)

    first = pipeline.run_month_task(water_year, d.year, d.month, transport, mapping, results_dir, tmp_dir_root)
    assert first.ok

    result = examples.generate_example(d, "test_label", transport, mapping, results_dir, tmp_dir_root)

    assert result.cross_check_ok, result.cross_check_errors
    assert result.date == d
    assert result.label == "test_label"
    # error sign is MERRA (0.5 -> 50pp) minus MODSCAG (0.4 -> 40pp) = +10pp everywhere
    assert np.allclose(result.r_grid, 40.0)
    assert np.allclose(result.m_grid, 50.0)
    assert np.allclose(result.diff_grid, 10.0)


def test_generate_example_cross_check_fails_when_no_existing_checkpoint(tmp_path):
    mapping, results_dir, tmp_dir_root = _setup(tmp_path, None, n_per_cell=4)
    transport = FakeTransport(mapping.pixel_cell_id.shape[0])
    d = date(2020, 2, 15)

    result = examples.generate_example(d, "label", transport, mapping, results_dir, tmp_dir_root)

    assert not result.cross_check_ok
    assert any("no existing checkpoint" in e for e in result.cross_check_errors)


def test_generate_example_cross_check_fails_when_checkpoint_tampered(tmp_path):
    mapping, results_dir, tmp_dir_root = _setup(tmp_path, None, n_per_cell=4)
    transport = FakeTransport(mapping.pixel_cell_id.shape[0], snow_fraction=40.0, merra_value=0.5)
    d = date(2020, 2, 15)
    water_year = dates.water_year_of(d)

    first = pipeline.run_month_task(water_year, d.year, d.month, transport, mapping, results_dir, tmp_dir_root)
    assert first.ok

    path = pipeline.month_checkpoint_path(results_dir, d.year, d.month)
    metadata, rows = checkpoint.read_checkpoint(path)
    rows[0]["sum_w"] = rows[0]["sum_w"] + 1000.0
    checkpoint.write_checkpoint(path, rows, metadata)

    result = examples.generate_example(d, "label", transport, mapping, results_dir, tmp_dir_root)

    assert not result.cross_check_ok
    assert any("sum_w" in e for e in result.cross_check_errors)


def test_merra_extraction_is_exact_no_interpolation_blending(tmp_path):
    mapping, results_dir, tmp_dir_root = _setup(tmp_path, None, n_per_cell=2)
    n_pixels = mapping.pixel_cell_id.shape[0]

    total = config.N_LAT_CELLS * config.N_LON_CELLS
    frsno = (np.arange(total, dtype=np.float64) / total).reshape(config.N_LAT_CELLS, config.N_LON_CELLS)
    transport = FakeTransport(n_pixels, snow_fraction=40.0, merra_grid=frsno)

    d = date(2020, 2, 15)
    water_year = dates.water_year_of(d)
    first = pipeline.run_month_task(water_year, d.year, d.month, transport, mapping, results_dir, tmp_dir_root)
    assert first.ok

    result = examples.generate_example(d, "label", transport, mapping, results_dir, tmp_dir_root)
    assert result.cross_check_ok, result.cross_check_errors

    for lon_idx in range(config.N_LON_CELLS):
        for lat_idx in range(config.N_LAT_CELLS):
            expected = frsno[lat_idx, lon_idx] * 100.0
            assert result.m_grid[lat_idx, lon_idx] == pytest.approx(expected)


def test_write_example_netcdf_round_trip(tmp_path):
    mapping, results_dir, tmp_dir_root = _setup(tmp_path, None, n_per_cell=4)
    transport = FakeTransport(mapping.pixel_cell_id.shape[0], snow_fraction=40.0, merra_value=0.5)
    d = date(2020, 2, 15)
    water_year = dates.water_year_of(d)
    pipeline.run_month_task(water_year, d.year, d.month, transport, mapping, results_dir, tmp_dir_root)
    result = examples.generate_example(d, "label", transport, mapping, results_dir, tmp_dir_root)

    out_path = str(tmp_path / "example.nc")
    examples.write_example_netcdf(result, out_path)

    with xr.open_dataset(out_path) as ds:
        assert ds.attrs["cross_check_ok"] == 1
        assert ds.attrs["illustrative_only"] == 1
        assert ds.attrs["resampling"].startswith("none")
        assert ds.attrs["error_sign"] == config.ERROR_SIGN
        assert np.allclose(ds["merra_raw"].values, 50.0)
        assert np.allclose(ds["modis_aggregated_to_merra"].values, 40.0)
        assert np.allclose(ds["merra_minus_modis_aggregated"].values, 10.0)


def test_render_example_figure_writes_png(tmp_path):
    mapping, results_dir, tmp_dir_root = _setup(tmp_path, None, n_per_cell=4)
    transport = FakeTransport(mapping.pixel_cell_id.shape[0], snow_fraction=40.0, merra_value=0.5)
    d = date(2020, 2, 15)
    water_year = dates.water_year_of(d)
    pipeline.run_month_task(water_year, d.year, d.month, transport, mapping, results_dir, tmp_dir_root)
    result = examples.generate_example(d, "label", transport, mapping, results_dir, tmp_dir_root)

    out_path = tmp_path / "example.png"
    examples.render_example_figure(result, str(out_path))
    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_render_example_figure_writes_png_with_dem_overlay(tmp_path):
    from fsca_eval import terrain

    mapping, results_dir, tmp_dir_root = _setup(tmp_path, None, n_per_cell=4)
    transport = FakeTransport(mapping.pixel_cell_id.shape[0], snow_fraction=40.0, merra_value=0.5)
    d = date(2020, 2, 15)
    water_year = dates.water_year_of(d)
    pipeline.run_month_task(water_year, d.year, d.month, transport, mapping, results_dir, tmp_dir_root)
    result = examples.generate_example(d, "label", transport, mapping, results_dir, tmp_dir_root)

    dem = terrain.DemGrid(
        elevation_m=np.linspace(1000.0, 4000.0, 12).reshape(3, 4),
        lon_edges=np.linspace(config.DOMAIN_LON_EDGE_MIN, config.DOMAIN_LON_EDGE_MAX, 5),
        lat_edges=np.linspace(config.DOMAIN_LAT_EDGE_MIN, config.DOMAIN_LAT_EDGE_MAX, 4),
    )

    out_path = tmp_path / "example_dem.png"
    examples.render_example_figure(result, str(out_path), dem=dem)
    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_generate_example_works_for_last_day_of_month(tmp_path):
    mapping, results_dir, tmp_dir_root = _setup(tmp_path, None, n_per_cell=4)
    transport = FakeTransport(mapping.pixel_cell_id.shape[0])

    d = date(2020, 2, 29)  # last day of Feb 2020 (leap year)
    result = examples.generate_example(d, "label", transport, mapping, results_dir, tmp_dir_root)
    assert result.date == d


# --- no bilinear/other resampling in the fSCA aggregation path -----------------


def test_no_resampling_functions_referenced_in_aggregation_path():
    # Actual API call surfaces only -- docstrings legitimately mention "bilinear"
    # in prose to document that it is *not* used, so that word itself is not a
    # useful token here.
    forbidden_tokens = (
        "griddata", "zoom(", ".resize(", "interp2d", "RectBivariateSpline",
        "cv2", "PIL", "scipy.ndimage",
    )
    for module in (worker, regrid, pipeline, examples, metrics):
        src = inspect.getsource(module)
        for token in forbidden_tokens:
            assert token not in src, f"{module.__name__} references forbidden resampling token {token!r}"
