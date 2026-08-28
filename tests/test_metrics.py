import math

import pytest

from fsca_eval import metrics


def test_sufficient_stats_addition():
    a = metrics.SufficientStats(sum_w=10, sum_w_error=2, sum_w_abs_error=4, sum_w_r=6, valid_pixels=10,
                                 expected_pixels=12, observed_pixels=9, n_cell_days=1, n_days=1, n_calendar_days=1)
    b = metrics.SufficientStats(sum_w=5, sum_w_error=-1, sum_w_abs_error=1, sum_w_r=3, valid_pixels=5,
                                 expected_pixels=6, observed_pixels=4, n_cell_days=1, n_days=1, n_calendar_days=1)
    c = a + b
    assert c.sum_w == 15
    assert c.sum_w_error == 1
    assert c.sum_w_abs_error == 5
    assert c.sum_w_r == 9
    assert c.valid_pixels == 15
    assert c.expected_pixels == 18
    assert c.observed_pixels == 13
    assert c.n_cell_days == 2
    assert c.n_days == 2
    assert c.n_calendar_days == 2


def test_cell_day_contribution_missing_reference_returns_zero_weight():
    stat = metrics.cell_day_contribution(
        m_fraction=0.5, r_fraction=float("nan"), weight=10,
        expected_pixels=12, observed_pixels=8, support_fraction=0.83, support_threshold=0.8,
    )
    assert stat.sum_w == 0
    assert stat.n_days == 0
    assert stat.n_cell_days == 0
    assert stat.n_calendar_days == 1
    assert stat.expected_pixels == 12
    assert stat.observed_pixels == 8


def test_cell_day_contribution_below_support_threshold_excluded_from_sums():
    stat = metrics.cell_day_contribution(
        m_fraction=0.5, r_fraction=0.3, weight=10,
        expected_pixels=20, observed_pixels=8, support_fraction=0.5, support_threshold=0.8,
    )
    assert stat.sum_w == 0
    assert stat.sum_w_error == 0
    assert stat.n_cell_days == 0
    assert stat.n_days == 0
    assert stat.n_calendar_days == 1
    # pixel tallies are still recorded even when the cell-day fails support
    assert stat.valid_pixels == 10
    assert stat.expected_pixels == 20
    assert stat.observed_pixels == 8


def test_cell_day_contribution_valid_day_populates_sums_with_error_sign_m_minus_r():
    stat = metrics.cell_day_contribution(
        m_fraction=0.7, r_fraction=0.5, weight=10,
        expected_pixels=10, observed_pixels=10, support_fraction=1.0, support_threshold=0.8,
    )
    assert stat.sum_w == 10
    assert stat.sum_w_error == pytest.approx(10 * (0.7 - 0.5))
    assert stat.sum_w_abs_error == pytest.approx(10 * abs(0.7 - 0.5))
    assert stat.sum_w_r == pytest.approx(10 * 0.5)
    assert stat.n_cell_days == 1
    assert stat.n_days == 1


def test_bias_and_mae_from_sufficient_stats():
    stats = metrics.SufficientStats(sum_w=10, sum_w_error=2, sum_w_abs_error=4, sum_w_r=5)
    assert metrics.bias_pp(stats) == pytest.approx(20.0)  # 100 * 2/10
    assert metrics.mae_pp(stats) == pytest.approx(40.0)  # 100 * 4/10


def test_bias_and_mae_nan_with_zero_weight():
    stats = metrics.SufficientStats()
    assert math.isnan(metrics.bias_pp(stats))
    assert math.isnan(metrics.mae_pp(stats))
    assert math.isnan(metrics.nmb(stats))
    assert math.isnan(metrics.nmae(stats))
    assert math.isnan(metrics.composite_fsca(stats))


def test_nmb_and_nmae_normalize_by_paired_reference_signal():
    stats = metrics.SufficientStats(sum_w=10, sum_w_error=2, sum_w_abs_error=4, sum_w_r=8)
    assert metrics.nmb(stats) == pytest.approx(100 * 2 / 8)
    assert metrics.nmae(stats) == pytest.approx(100 * 4 / 8)


def test_composite_fsca_is_weighted_mean_reference():
    stats = metrics.SufficientStats(sum_w=10, sum_w_r=6)
    assert metrics.composite_fsca(stats) == pytest.approx(0.6)


def test_support_and_direct_observation_fraction():
    stats = metrics.SufficientStats(valid_pixels=8, expected_pixels=10, observed_pixels=6)
    assert metrics.support_fraction(stats) == pytest.approx(0.8)
    assert metrics.direct_observation_fraction(stats) == pytest.approx(0.75)


def test_support_fraction_zero_expected_is_zero_not_nan():
    stats = metrics.SufficientStats(valid_pixels=0, expected_pixels=0, observed_pixels=0)
    assert metrics.support_fraction(stats) == 0.0
    assert metrics.direct_observation_fraction(stats) == 0.0


def test_sufficient_stat_combination_differs_from_averaging_pre_derived_metrics():
    """Sanity check for the sufficient-statistic-first design: combining two
    unequal-weight days via sums gives a different (correct) bias than
    naively averaging their two bias_pp values.
    """
    day1 = metrics.SufficientStats(sum_w=100, sum_w_error=10, sum_w_abs_error=10, sum_w_r=50)  # bias=10pp
    day2 = metrics.SufficientStats(sum_w=1, sum_w_error=-1, sum_w_abs_error=1, sum_w_r=0.5)  # bias=-100pp

    combined = day1 + day2
    correct_bias = metrics.bias_pp(combined)
    naive_average = (metrics.bias_pp(day1) + metrics.bias_pp(day2)) / 2

    assert correct_bias != pytest.approx(naive_average)
    # weight-dominated by day1, so the correct combined bias stays close to day1's
    assert correct_bias == pytest.approx(100 * 9 / 101)
