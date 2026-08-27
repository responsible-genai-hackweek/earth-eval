from pathlib import Path

import numpy as np

from merra_modis_comparison.reanalysis_config import (
    MODEL_SPECS,
    ReanalysisRunConfig,
)
from merra_modis_comparison.reanalysis_metrics import (
    ReanalysisStatsBlock,
    update_reanalysis_stats,
)
from merra_modis_comparison.reanalysis_spatial_plotting import (
    MIN_MODIS_FSCA_PCT,
    load_reanalysis_elevation_grid,
    reanalysis_cell_metric_grid,
    reanalysis_modis_fsca_grid,
    reanalysis_normalized_metric_grid,
    write_reanalysis_elevation_dependency_plot,
    write_reanalysis_spatial_monthly_plot,
)


def _stats(config: ReanalysisRunConfig, error: float) -> ReanalysisStatsBlock:
    grid = config.target_grid("era5-land")
    stats = ReanalysisStatsBlock.empty(grid.size)
    update_reanalysis_stats(
        stats,
        np.full(grid.shape, 0.5 + error),
        np.full(grid.shape, 0.5),
        np.full(grid.shape, 9),
        np.full(grid.shape, 10),
        np.full(grid.shape, 7),
    )
    return stats


def test_reanalysis_cell_metric_grid_preserves_shape_and_sign():
    config = ReanalysisRunConfig(
        start_water_year=2023,
        end_water_year=2023,
        model_ids=("era5-land",),
        west=-109,
        east=-108.8,
        south=37,
        north=37.2,
    )
    grid = config.target_grid("era5-land")
    stats = _stats(config, -0.1)
    bias = reanalysis_cell_metric_grid(stats, "bias_pp", grid.shape)
    mae = reanalysis_cell_metric_grid(stats, "mae_pp", grid.shape)
    assert bias.shape == (3, 3)
    assert np.allclose(bias, -10)
    assert np.allclose(mae, 10)


def test_normalized_metrics_use_paired_modscag_denominator_and_five_pct_mask():
    config = ReanalysisRunConfig(
        start_water_year=2023,
        end_water_year=2023,
        model_ids=("era5-land",),
        west=-109,
        east=-108.8,
        south=37,
        north=37.2,
    )
    grid = config.target_grid("era5-land")
    stats = _stats(config, -0.1)
    nmb = reanalysis_normalized_metric_grid(stats, "nmb_pct", grid.shape)
    nmae = reanalysis_normalized_metric_grid(stats, "nmae_pct", grid.shape)
    assert np.allclose(nmb, -20)
    assert np.allclose(nmae, 20)
    assert MIN_MODIS_FSCA_PCT == 5.0

    low_snow = ReanalysisStatsBlock.empty(grid.size)
    update_reanalysis_stats(
        low_snow,
        np.full(grid.shape, 0.06),
        np.full(grid.shape, 0.04),
        np.full(grid.shape, 9),
        np.full(grid.shape, 10),
        np.full(grid.shape, 7),
    )
    masked = reanalysis_normalized_metric_grid(
        low_snow, "nmb_pct", grid.shape
    )
    assert np.isnan(masked).all()


def test_reanalysis_modis_fsca_grid_uses_paired_pixel_day_weights():
    config = ReanalysisRunConfig(
        start_water_year=2023,
        end_water_year=2023,
        model_ids=("era5-land",),
        west=-109,
        east=-108.8,
        south=37,
        north=37.2,
    )
    grid = config.target_grid("era5-land")
    values = reanalysis_modis_fsca_grid(_stats(config, -0.1), grid.shape)
    assert values.shape == grid.shape
    assert np.allclose(values, 50)

    low_snow = ReanalysisStatsBlock.empty(grid.size)
    update_reanalysis_stats(
        low_snow,
        np.full(grid.shape, 0.12),
        np.full(grid.shape, 0.08),
        np.full(grid.shape, 9),
        np.full(grid.shape, 10),
        np.full(grid.shape, 7),
    )
    masked = reanalysis_modis_fsca_grid(
        low_snow, grid.shape, minimum_modis_fsca_pct=10
    )
    assert np.isnan(masked).all()


def test_era5_land_fourteen_panel_spatial_plot(tmp_path):
    config = ReanalysisRunConfig(
        start_water_year=2023,
        end_water_year=2023,
        model_ids=("era5-land",),
        west=-109,
        east=-108.8,
        south=37,
        north=37.2,
    )
    grid = config.target_grid("era5-land")
    months = [
        (label, _stats(config, error))
        for label, error in zip(
            (
                "November 2022",
                "December 2022",
                "January 2023",
                "February 2023",
                "March 2023",
                "April 2023",
                "May 2023",
            ),
            (-0.12, -0.10, -0.08, -0.06, -0.04, -0.02, 0.01),
            strict=True,
        )
    ]
    elevation = load_reanalysis_elevation_grid(
        Path("data/usgs_3dep_era5_land_coarse_dem.tif"), grid
    )
    output = tmp_path / "era5-land-spatial.png"
    write_reanalysis_spatial_monthly_plot(
        months, config, MODEL_SPECS["era5-land"], output, elevation
    )
    assert output.stat().st_size > 10_000
    assert not list(tmp_path.glob("*.tmp"))

    elevation_output = tmp_path / "era5-land-apr-may-elevation.png"
    write_reanalysis_elevation_dependency_plot(
        months[-2:],
        config,
        MODEL_SPECS["era5-land"],
        elevation_output,
        elevation,
    )
    assert elevation_output.stat().st_size > 10_000
    assert not list(tmp_path.glob("*.tmp"))
