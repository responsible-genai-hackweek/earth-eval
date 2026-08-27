import numpy as np

from merra_modis_comparison.reanalysis_metrics import (
    ReanalysisStatsBlock,
    reanalysis_metrics_for_slot,
    update_reanalysis_stats,
)


def test_reanalysis_stats_retain_normalization_sums_without_daily_fields():
    stats = ReanalysisStatsBlock.empty(2)
    assert update_reanalysis_stats(
        stats,
        np.array([[0.6, 0.3]]),
        np.array([[0.5, 0.5]]),
        np.array([[3, 1]]),
        np.array([[3, 1]]),
        np.array([[2, 1]]),
    )
    metrics = reanalysis_metrics_for_slot(stats, stats.domain_slot)
    assert np.isclose(metrics["bias_pp"], 2.5)
    assert np.isclose(metrics["mae_pp"], 12.5)
    assert np.isclose(metrics["modscag_fsca_mean"], 0.5)
    assert np.isclose(metrics["model_fsca_mean"], 0.525)
    assert np.isclose(metrics["normalized_mean_bias_pct"], 5.0)
    assert np.isclose(metrics["normalized_mae_pct"], 25.0)
    stats.validate(expected_calendar_days=1)
