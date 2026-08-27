"""Sufficient statistics and error metrics.

Protects: the error sign, pixel-count weighting, percentage-point units, the
combine-sums-before-deriving rule, and the distinction between combining over
time and combining over space.
"""
import numpy as np
import pytest

from merra_modis_comparison.metrics import (
    SufficientStats,
    accumulate_cell_days,
    bias_pp,
    combine_over_cells,
    combine_over_time,
    direct_observation_fraction,
    mae_pp,
    nmae_pct,
    nmb_pct,
    support_fraction,
)


def stats(model, reference, weights, **kw) -> SufficientStats:
    return accumulate_cell_days(
        np.asarray(model, float), np.asarray(reference, float), np.asarray(weights, float), **kw
    )


class TestErrorSign:
    def test_model_snowier_than_reference_gives_positive_bias(self):
        s = stats([0.8], [0.5], [100])
        assert bias_pp(s) == pytest.approx(30.0)

    def test_model_less_snowy_than_reference_gives_negative_bias(self):
        s = stats([0.2], [0.5], [100])
        assert bias_pp(s) == pytest.approx(-30.0)

    def test_mae_is_never_negative(self):
        s = stats([0.2, 0.8], [0.5, 0.5], [100, 100])
        assert mae_pp(s) == pytest.approx(30.0)


class TestUnits:
    def test_bias_and_mae_are_in_fsca_percentage_points(self):
        s = stats([1.0], [0.0], [1])
        assert bias_pp(s) == pytest.approx(100.0)
        assert mae_pp(s) == pytest.approx(100.0)

    def test_nmb_is_a_percentage_of_the_reference_signal(self):
        # model 0.6 vs reference 0.5 -> +0.1 on a 0.5 signal -> +20 %
        s = stats([0.6], [0.5], [10])
        assert nmb_pct(s) == pytest.approx(20.0)
        assert nmae_pct(s) == pytest.approx(20.0)

    def test_nmae_uses_absolute_error(self):
        s = stats([0.6, 0.4], [0.5, 0.5], [10, 10])
        assert nmb_pct(s) == pytest.approx(0.0)
        assert nmae_pct(s) == pytest.approx(20.0)


class TestWeighting:
    def test_weights_are_valid_pixel_counts(self):
        # a cell-day backed by 900 pixels must outweigh one backed by 100
        s = stats([1.0, 0.0], [0.0, 0.0], [900, 100])
        assert bias_pp(s) == pytest.approx(90.0)

    def test_zero_weight_pairs_do_not_contribute(self):
        a = stats([1.0, 0.5], [0.0, 0.5], [100, 0])
        b = stats([1.0], [0.0], [100])
        assert bias_pp(a) == pytest.approx(bias_pp(b))

    def test_unweighted_mean_would_differ(self):
        s = stats([1.0, 0.0], [0.0, 0.0], [900, 100])
        unweighted = float(np.mean([1.0, 0.0]) * 100)
        assert bias_pp(s) != pytest.approx(unweighted)


class TestNullMetrics:
    def test_empty_group_yields_nan_not_an_error(self):
        s = SufficientStats.zero()
        assert np.isnan(bias_pp(s))
        assert np.isnan(mae_pp(s))
        assert np.isnan(nmb_pct(s))

    def test_zero_reference_signal_yields_nan_normalized_metrics(self):
        s = stats([0.3], [0.0], [50])
        assert bias_pp(s) == pytest.approx(30.0)
        assert np.isnan(nmb_pct(s))
        assert np.isnan(nmae_pct(s))

    def test_non_finite_pairs_are_excluded(self):
        s = stats([0.5, np.nan, 0.5], [0.25, 0.25, np.nan], [10, 10, 10])
        assert s.n_cell_days == 1
        assert bias_pp(s) == pytest.approx(25.0)


class TestInvariants:
    @pytest.mark.parametrize("seed", range(8))
    def test_abs_bias_never_exceeds_mae(self, seed):
        rng = np.random.default_rng(seed)
        n = 200
        s = stats(rng.uniform(0, 1, n), rng.uniform(0, 1, n), rng.integers(1, 1000, n))
        assert abs(bias_pp(s)) <= mae_pp(s) + 1e-9

    def test_identical_fields_give_zero_bias_and_zero_mae(self):
        rng = np.random.default_rng(0)
        v = rng.uniform(0, 1, 50)
        s = stats(v, v, rng.integers(1, 500, 50))
        assert bias_pp(s) == pytest.approx(0.0)
        assert mae_pp(s) == pytest.approx(0.0)


class TestCombineOverTime:
    def test_addition_is_exact_for_a_split_batch(self):
        rng = np.random.default_rng(1)
        m, r, w = rng.uniform(0, 1, 60), rng.uniform(0, 1, 60), rng.integers(1, 900, 60)
        whole = stats(m, r, w)
        halves = combine_over_time([stats(m[:25], r[:25], w[:25]), stats(m[25:], r[25:], w[25:])])
        assert bias_pp(halves) == pytest.approx(bias_pp(whole))
        assert mae_pp(halves) == pytest.approx(mae_pp(whole))
        assert halves.n_cell_days == whole.n_cell_days

    def test_addition_is_order_independent(self):
        a = stats([0.9], [0.1], [10], n_days=1, n_calendar_days=1)
        b = stats([0.2], [0.6], [90], n_days=1, n_calendar_days=1)
        assert combine_over_time([a, b]) == combine_over_time([b, a])

    def test_day_counts_add_over_time(self):
        a = stats([0.9], [0.1], [10], n_days=1, n_calendar_days=31)
        b = stats([0.2], [0.6], [90], n_days=1, n_calendar_days=28)
        c = combine_over_time([a, b])
        assert (c.n_days, c.n_calendar_days) == (2, 59)

    def test_combining_an_empty_sequence_is_the_zero_element(self):
        assert combine_over_time([]) == SufficientStats.zero()


class TestCombineOverCells:
    def test_weighted_sums_add_across_cells(self):
        a = stats([0.9], [0.1], [10], n_days=1, n_calendar_days=31)
        b = stats([0.2], [0.6], [90], n_days=1, n_calendar_days=31)
        domain = combine_over_cells([a, b], n_days=1, n_calendar_days=31)
        assert domain.sum_w == pytest.approx(100.0)
        assert domain.n_cell_days == 2

    def test_day_counts_do_not_add_across_cells(self):
        # two cells each paired on the same single day is one day, not two
        a = stats([0.9], [0.1], [10], n_days=1, n_calendar_days=31)
        b = stats([0.2], [0.6], [90], n_days=1, n_calendar_days=31)
        domain = combine_over_cells([a, b], n_days=1, n_calendar_days=31)
        assert domain.n_days == 1
        assert domain.n_calendar_days == 31

    def test_domain_metric_pools_weighted_cell_days(self):
        a = stats([1.0], [0.0], [900], n_days=1, n_calendar_days=1)
        b = stats([0.0], [0.0], [100], n_days=1, n_calendar_days=1)
        domain = combine_over_cells([a, b], n_days=1, n_calendar_days=1)
        assert bias_pp(domain) == pytest.approx(90.0)


class TestCombineSumsNotMetrics:
    def test_pooling_sums_differs_from_averaging_derived_metrics(self):
        """The contract's central arithmetic rule, made visible."""
        heavy = stats([1.0], [0.0], [1000])   # +100 pp on 1000 pixels
        light = stats([0.0], [0.5], [10])     # -50 pp on 10 pixels
        pooled = bias_pp(combine_over_time([heavy, light]))
        averaged = (bias_pp(heavy) + bias_pp(light)) / 2
        assert pooled == pytest.approx(100.0 * (1000 * 1.0 + 10 * -0.5) / 1010)
        assert averaged == pytest.approx(25.0)
        assert abs(pooled - averaged) > 70


class TestDiagnosticFractions:
    def test_support_is_valid_over_expected_pixels(self):
        s = stats([0.5], [0.5], [800], expected_pixels=1000)
        assert support_fraction(s) == pytest.approx(0.8)

    def test_direct_observation_fraction_is_observed_over_valid(self):
        s = stats([0.5], [0.5], [800], observed_pixels=200)
        assert direct_observation_fraction(s) == pytest.approx(0.25)

    def test_fractions_are_nan_when_undefined(self):
        assert np.isnan(support_fraction(SufficientStats.zero()))
        assert np.isnan(direct_observation_fraction(SufficientStats.zero()))
