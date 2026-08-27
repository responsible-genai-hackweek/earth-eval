import calendar

import numpy as np
import pytest

from merra_modis_comparison.reanalysis_checkpoints import (
    InvalidReanalysisCheckpoint,
    load_month_checkpoint,
    write_month_checkpoint,
)
from merra_modis_comparison.reanalysis_config import (
    MODEL_SPECS,
    ReanalysisRunConfig,
)
from merra_modis_comparison.reanalysis_metrics import (
    ReanalysisStatsBlock,
    update_reanalysis_stats,
)


def _complete_month(config, model_id, year, month):
    grid = config.target_grid(model_id)
    stats = ReanalysisStatsBlock.empty(grid.size)
    for _ in range(calendar.monthrange(year, month)[1]):
        update_reanalysis_stats(
            stats,
            np.full(grid.shape, 0.6),
            np.full(grid.shape, 0.5),
            np.full(grid.shape, 8),
            np.full(grid.shape, 10),
            np.full(grid.shape, 4),
        )
    return stats


def test_reanalysis_checkpoint_round_trip_and_contract_validation(tmp_path):
    config = ReanalysisRunConfig(
        start_water_year=2023,
        end_water_year=2023,
        model_ids=("era5",),
        west=-109,
        east=-108.5,
        south=37,
        north=37.5,
    )
    spec = MODEL_SPECS["era5"]
    stats = _complete_month(config, "era5", 2022, 10)
    path = tmp_path / "2022-10.csv"
    write_month_checkpoint(stats, 2022, 10, config, spec, path)
    loaded = load_month_checkpoint(path, 2022, 10, config, spec)
    for name in stats.__dataclass_fields__:
        assert np.array_equal(getattr(loaded, name), getattr(stats, name))
    changed = ReanalysisRunConfig(
        start_water_year=2023,
        end_water_year=2023,
        model_ids=("era5",),
        west=-109,
        east=-108.5,
        south=37,
        north=37.5,
        support_threshold=0.9,
    )
    with pytest.raises(InvalidReanalysisCheckpoint, match="configuration differs"):
        load_month_checkpoint(path, 2022, 10, changed, spec)


def test_narr_checkpoint_round_trip_uses_native_cell_identity(tmp_path):
    config = ReanalysisRunConfig(
        start_water_year=2023,
        end_water_year=2023,
        model_ids=("narr",),
    )
    spec = MODEL_SPECS["narr"]
    grid = config.target_grid("narr")
    stats = _complete_month(config, "narr", 2022, 10)
    path = tmp_path / "2022-10.csv"

    write_month_checkpoint(stats, 2022, 10, config, spec, path)
    loaded = load_month_checkpoint(path, 2022, 10, config, spec)

    assert grid.size == 185
    assert grid.cell_metadata(0)["cell_id"].startswith("NARR_y")
    for name in stats.__dataclass_fields__:
        assert np.array_equal(getattr(loaded, name), getattr(stats, name))
