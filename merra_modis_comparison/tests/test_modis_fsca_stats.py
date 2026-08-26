import calendar

import numpy as np

from merra_modis_comparison.config import RunConfig
from merra_modis_comparison.modis_fsca_stats import (
    ModisStatsBlock,
    load_modis_checkpoint,
    mean_modis_fsca_pct,
    merge_modis_blocks,
    selected_calendar_months,
    update_modis_stats,
    write_modis_checkpoint,
)


def _complete_month(config: RunConfig, year: int, month: int) -> ModisStatsBlock:
    stats = ModisStatsBlock.empty(config.target_grid.size)
    shape = config.target_grid.shape
    for _ in range(calendar.monthrange(year, month)[1]):
        update_modis_stats(
            stats,
            np.full(shape, 0.4),
            np.full(shape, 8),
            np.full(shape, 10),
            np.full(shape, 6),
        )
    return stats


def test_modis_weighted_mean_and_merge():
    stats = ModisStatsBlock.empty(2)
    assert update_modis_stats(
        stats,
        np.array([[0.2, 0.8]]),
        np.array([[3, 1]]),
        np.array([[3, 1]]),
        np.array([[2, 1]]),
    )
    assert np.isclose(mean_modis_fsca_pct(stats, stats.domain_slot), 35)
    merged = merge_modis_blocks([stats, stats])
    assert np.isclose(mean_modis_fsca_pct(merged, merged.domain_slot), 35)
    assert merged.n_calendar_days.tolist() == [2, 2, 2]


def test_modis_checkpoint_round_trip(tmp_path):
    config = RunConfig()
    stats = _complete_month(config, 2010, 11)
    path = tmp_path / "2010-11.csv"
    write_modis_checkpoint(stats, 2010, 11, config, path)
    loaded = load_modis_checkpoint(path, 2010, 11, config)
    for name in stats.__dataclass_fields__:
        assert np.array_equal(getattr(loaded, name), getattr(stats, name))
    assert not list(tmp_path.glob("*.tmp"))


def test_selected_composite_inventory_contains_56_unique_months():
    periods = selected_calendar_months()
    assert len(periods) == 56
    assert (2010, 11) in periods
    assert (2023, 5) in periods
