import calendar

import numpy as np

from merra_modis_comparison.reanalysis_config import (
    MODEL_SPECS,
    ReanalysisRunConfig,
)
from merra_modis_comparison.reanalysis_metrics import (
    ReanalysisStatsBlock,
    update_reanalysis_stats,
)
from merra_modis_comparison.reanalysis_pipeline import _grid_mappings, build_final_rows


def test_archive_edge_is_kept_in_expected_support_but_not_downloaded():
    config = ReanalysisRunConfig()
    mappings, archive_tiles = _grid_mappings(config, MODEL_SPECS["era5-land"])
    assert "h10v05" in mappings
    assert "h10v05" not in archive_tiles


def test_reanalysis_final_rows_include_model_and_native_cell_metadata():
    config = ReanalysisRunConfig(
        start_water_year=2023,
        end_water_year=2023,
        model_ids=("era5",),
        west=-109,
        east=-108.5,
        south=37,
        north=37.5,
    )
    grid = config.target_grid("era5")
    checkpoints = {}
    for year, month in config.calendar_months:
        stats = ReanalysisStatsBlock.empty(grid.size)
        for _ in range(calendar.monthrange(year, month)[1]):
            update_reanalysis_stats(
                stats,
                np.full(grid.shape, 0.6),
                np.full(grid.shape, 0.5),
                np.full(grid.shape, 9),
                np.full(grid.shape, 10),
                np.full(grid.shape, 6),
            )
        checkpoints[(year, month)] = stats
    overall, pixels = build_final_rows(checkpoints, config, MODEL_SPECS["era5"])
    assert len(overall) == 32
    assert len(pixels) == 32 * 9
    assert overall[0]["model_id"] == "era5"
    assert np.isclose(overall[0]["bias_pp"], 10.0)
    assert np.isclose(overall[0]["normalized_mean_bias_pct"], 20.0)
    assert pixels[0]["target_latitude"] == 37.0
    assert pixels[0]["target_longitude"] == -109.0
