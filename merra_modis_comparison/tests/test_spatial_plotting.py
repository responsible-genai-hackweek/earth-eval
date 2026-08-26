import numpy as np
from pathlib import Path

from merra_modis_comparison.config import RunConfig
from merra_modis_comparison.metrics import StatsBlock, update_stats
from merra_modis_comparison.spatial_plotting import (
    ELEVATION_CONTOURS_M,
    cell_mean_elevation_grid,
    cell_metric_grid,
    hillshade_grid,
    load_elevation_grid,
    write_elevation_dependency_plot,
    write_spatial_monthly_plot,
)


def _stats(config: RunConfig, error: float) -> StatsBlock:
    stats = StatsBlock.empty(config.target_grid.size)
    shape = config.target_grid.shape
    update_stats(
        stats,
        np.full(shape, 0.5 + error),
        np.full(shape, 0.5),
        np.full(shape, 9),
        np.full(shape, 10),
        np.full(shape, 7),
    )
    return stats


def test_cell_metric_grid_preserves_target_shape_and_sign():
    config = RunConfig()
    stats = _stats(config, -0.1)
    bias = cell_metric_grid(stats, "bias_pp", config.target_grid.shape)
    mae = cell_metric_grid(stats, "mae_pp", config.target_grid.shape)
    assert bias.shape == (9, 8)
    assert np.allclose(bias, -10)
    assert np.allclose(mae, 10)


def test_coarse_dem_covers_comparison_grid():
    config = RunConfig()
    elevation = load_elevation_grid(
        Path("data/usgs_3dep_coarse_dem.tif"), config
    )
    assert elevation.elevation_m.shape == (90, 100)
    assert np.nanmin(elevation.elevation_m) > 1_000
    assert np.nanmax(elevation.elevation_m) > 3_500


def test_hillshade_and_cell_mean_elevation_cover_grid():
    config = RunConfig()
    elevation = load_elevation_grid(
        Path("data/usgs_3dep_coarse_dem.tif"), config
    )
    relief = hillshade_grid(elevation)
    cell_elevation = cell_mean_elevation_grid(elevation, config)
    assert relief.shape == elevation.elevation_m.shape
    assert np.nanmin(relief) >= 0
    assert np.nanmax(relief) <= 1
    assert cell_elevation.shape == config.target_grid.shape
    assert np.isfinite(cell_elevation).all()
    assert ELEVATION_CONTOURS_M == (2000, 3000)


def test_fourteen_panel_spatial_plot(tmp_path):
    config = RunConfig()
    months = [
        (label, _stats(config, error))
        for label, error in zip(
            ("Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May"),
            (-0.12, -0.10, -0.08, -0.06, -0.04, -0.02, 0.01),
            strict=True,
        )
    ]
    output = tmp_path / "spatial.png"
    elevation = load_elevation_grid(
        Path("data/usgs_3dep_coarse_dem.tif"), config
    )
    write_spatial_monthly_plot(months, config, output, elevation)
    assert output.stat().st_size > 10_000
    assert not list(tmp_path.glob("*.tmp"))


def test_elevation_dependency_plot(tmp_path):
    config = RunConfig()
    months = [
        (label, _stats(config, error))
        for label, error in zip(
            ("Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May"),
            (-0.12, -0.10, -0.08, -0.06, -0.04, -0.02, 0.01),
            strict=True,
        )
    ]
    elevation = load_elevation_grid(
        Path("data/usgs_3dep_coarse_dem.tif"), config
    )
    output = tmp_path / "elevation.png"
    write_elevation_dependency_plot(months, config, output, elevation)
    assert output.stat().st_size > 10_000
    assert not list(tmp_path.glob("*.tmp"))
