import calendar

import numpy as np
import pytest

from merra_modis_comparison.checkpoints import (
    InvalidCheckpoint,
    load_month_checkpoint,
    write_month_checkpoint,
)
from merra_modis_comparison.config import RunConfig
from merra_modis_comparison.metrics import StatsBlock, update_stats


def _complete_month(config: RunConfig, year: int, month: int) -> StatsBlock:
    stats = StatsBlock.empty(config.target_grid.size)
    shape = config.target_grid.shape
    for _ in range(calendar.monthrange(year, month)[1]):
        update_stats(
            stats,
            np.full(shape, 0.6),
            np.full(shape, 0.5),
            np.full(shape, 8),
            np.full(shape, 10),
            np.full(shape, 4),
        )
    return stats


def test_atomic_checkpoint_round_trip(tmp_path):
    config = RunConfig()
    stats = _complete_month(config, 2009, 10)
    path = tmp_path / "2009-10.csv"
    write_month_checkpoint(stats, 2009, 10, config, path)
    loaded = load_month_checkpoint(path, 2009, 10, config)
    for name in stats.__dataclass_fields__:
        assert np.array_equal(getattr(loaded, name), getattr(stats, name))
    assert not list(tmp_path.glob("*.tmp"))


def test_checkpoint_rejects_changed_scientific_configuration(tmp_path):
    config = RunConfig()
    path = tmp_path / "2009-10.csv"
    write_month_checkpoint(
        _complete_month(config, 2009, 10), 2009, 10, config, path
    )
    changed = RunConfig(support_threshold=0.9)
    with pytest.raises(InvalidCheckpoint, match="configuration differs"):
        load_month_checkpoint(path, 2009, 10, changed)


def test_checkpoint_reuse_is_independent_of_execution_concurrency(tmp_path):
    config = RunConfig()
    path = tmp_path / "2009-10.csv"
    write_month_checkpoint(
        _complete_month(config, 2009, 10), 2009, 10, config, path
    )
    changed_execution = RunConfig(workers=4, ftp_connections=4)
    loaded = load_month_checkpoint(path, 2009, 10, changed_execution)
    assert loaded.n_calendar_days[-1] == 31
