import numpy as np

from merra_modis_comparison.metrics import (
    StatsBlock,
    merge_blocks,
    metrics_for_slot,
    update_stats,
)


def test_weighted_cell_and_domain_bias_mae_and_sign():
    stats = StatsBlock.empty(2)
    merra = np.array([[0.5, 0.1]])
    modscag = np.array([[0.4, 0.3]])
    valid = np.array([[3, 1]])
    expected = np.array([[3, 1]])
    observed = np.array([[2, 1]])
    assert update_stats(stats, merra, modscag, valid, expected, observed)
    domain = metrics_for_slot(stats, stats.domain_slot)
    assert np.isclose(domain["bias_pp"], 2.5)
    assert np.isclose(domain["mae_pp"], 12.5)
    assert domain["n_cell_days"] == 2
    assert domain["n_days"] == 1
    assert domain["direct_observation_pixel_days"] == 3
    assert stats.n_calendar_days.tolist() == [1, 1, 1]
    stats.validate(expected_calendar_days=1)


def test_all_fill_day_is_counted_for_every_cell_but_not_compared():
    stats = StatsBlock.empty(2)
    paired = update_stats(
        stats,
        np.array([[0.2, 0.4]]),
        np.array([[np.nan, np.nan]]),
        np.array([[0, 0]]),
        np.array([[10, 10]]),
        np.array([[0, 0]]),
    )
    assert not paired
    assert stats.n_calendar_days.tolist() == [1, 1, 1]
    assert stats.n_days.tolist() == [0, 0, 0]


def test_merge_is_additive_and_preserves_domain_reconstruction():
    left = StatsBlock.empty(1)
    right = StatsBlock.empty(1)
    arrays = (
        np.array([[0.5]]),
        np.array([[0.4]]),
        np.array([[2]]),
        np.array([[2]]),
        np.array([[1]]),
    )
    update_stats(left, *arrays)
    update_stats(right, *arrays)
    merged = merge_blocks([left, right])
    assert merged.sum_w.tolist() == [4, 4]
    assert merged.n_days.tolist() == [2, 2]
    assert merged.n_calendar_days.tolist() == [2, 2]
