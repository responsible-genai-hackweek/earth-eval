import math

import numpy as np
import pytest

from fsca_eval import config, metrics, significance


def _stats(err, sum_w=100.0, sum_w_r=50.0):
    return metrics.SufficientStats(
        sum_w=sum_w, sum_w_error=err, sum_w_abs_error=abs(err), sum_w_r=sum_w_r,
        valid_pixels=100, expected_pixels=100, observed_pixels=100,
        n_cell_days=1, n_days=1, n_calendar_days=1,
    )


WET_ERR = {2011: 10.0, 2017: 11.0, 2019: 9.0, 2023: 10.0}
DRY_ERR = {2012: 1.0, 2013: -1.0, 2015: 2.0, 2018: -2.0}


def _build_uniform_index():
    index = {}
    for water_year, err in {**WET_ERR, **DRY_ERR}.items():
        for month in config.COMPOSITE_MONTHS:
            index[(water_year, month)] = [_stats(err) for _ in range(config.N_CELLS)]
    return index


def test_yearly_nmb_matrix_shape_and_values():
    index = _build_uniform_index()
    matrix = significance.yearly_nmb_matrix(index, config.WET_WATER_YEARS, config.COMPOSITE_MONTHS)
    assert matrix.shape == (4, config.N_CELLS)
    # sorted water years: 2011, 2017, 2019, 2023
    expected_years_nmb = [2 * WET_ERR[y] for y in sorted(config.WET_WATER_YEARS)]
    assert matrix[:, 0] == pytest.approx(expected_years_nmb)


def test_pooled_composite_nmb_is_pooled_not_averaged():
    index = _build_uniform_index()
    wet_nmb = significance.pooled_composite_nmb(index, config.WET_WATER_YEARS, config.COMPOSITE_MONTHS)
    dry_nmb = significance.pooled_composite_nmb(index, config.DRY_WATER_YEARS, config.COMPOSITE_MONTHS)

    assert wet_nmb[0] == pytest.approx(20.0)  # 100 * sum(err) / sum(sum_w_r) = 100*40/200
    assert dry_nmb[0] == pytest.approx(0.0)


def test_pooled_composite_fsca():
    index = _build_uniform_index()
    wet_fsca = significance.pooled_composite_fsca(index, config.WET_WATER_YEARS, config.COMPOSITE_MONTHS)
    assert wet_fsca[0] == pytest.approx(0.5)  # sum_w_r / sum_w = 50/100


def test_wet_dry_significance_hatch_and_pvalues():
    index = _build_uniform_index()
    sig = significance.wet_dry_significance(index)

    assert sig.wet_composite_nmb[0] == pytest.approx(20.0)
    assert sig.dry_composite_nmb[0] == pytest.approx(0.0)

    assert sig.wet_pvalues[0] < 0.001
    assert sig.dry_pvalues[0] == pytest.approx(1.0, abs=1e-6)

    assert bool(sig.wet_hatch[0]) is True
    assert bool(sig.dry_hatch[0]) is False


def test_wet_dry_significance_df_assumption_holds():
    assert len(config.WET_WATER_YEARS) - 1 == config.SIGNIFICANCE_DF == 3
    assert len(config.DRY_WATER_YEARS) - 1 == config.SIGNIFICANCE_DF == 3


def test_one_sample_pvalues_propagates_nan_and_never_hatches():
    yearly_values = np.array([[10.0], [np.nan], [10.0], [10.0]])
    pvalues = significance.one_sample_pvalues(yearly_values)
    assert math.isnan(pvalues[0])
    assert bool(pvalues[0] < config.SIGNIFICANCE_ALPHA) is False


def test_no_fdr_correction_applied_hatch_is_raw_pvalue_comparison():
    index = _build_uniform_index()
    sig = significance.wet_dry_significance(index)
    # hatch is exactly the raw two-sided p<alpha comparison, cellwise -- no
    # multiple-comparison correction of any kind.
    assert np.array_equal(sig.wet_hatch, sig.wet_pvalues < config.SIGNIFICANCE_ALPHA)
    assert np.array_equal(sig.dry_hatch, sig.dry_pvalues < config.SIGNIFICANCE_ALPHA)


def test_monthly_wet_dry_significance_returns_one_entry_per_month_matching_single_month_call():
    index = _build_uniform_index()
    per_month = significance.monthly_wet_dry_significance(index)

    assert set(per_month.keys()) == set(config.COMPOSITE_MONTHS)
    for month in config.COMPOSITE_MONTHS:
        expected = significance.wet_dry_significance(index, months=(month,))
        actual = per_month[month]
        assert actual.wet_composite_nmb == pytest.approx(expected.wet_composite_nmb)
        assert actual.dry_composite_nmb == pytest.approx(expected.dry_composite_nmb)
        assert np.array_equal(actual.wet_hatch, expected.wet_hatch)
        assert np.array_equal(actual.dry_hatch, expected.dry_hatch)


def test_monthly_composite_metric_matches_manual_single_month_pooling():
    index = _build_uniform_index()
    per_month = significance.monthly_composite_metric(index, config.WET_WATER_YEARS, metrics.nmb)

    assert set(per_month.keys()) == set(config.COMPOSITE_MONTHS)
    for month in config.COMPOSITE_MONTHS:
        expected = significance.pooled_composite_nmb(index, config.WET_WATER_YEARS, months=(month,))
        assert per_month[month] == pytest.approx(expected)
        # uniform per-month data -- single-month NMB equals the Nov-May pooled value
        assert per_month[month][0] == pytest.approx(20.0)
