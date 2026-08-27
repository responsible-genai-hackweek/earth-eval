"""Water-year snowpack statistics and ranking.

Protects the definitions the headline claim rests on: peak and its date, the
1 April benchmark, melt-out, and rank within a distribution.
"""
from datetime import date, timedelta

import numpy as np
import pytest

from merra_modis_comparison.snowseason import (
    DailySeries,
    april_first,
    mean_over,
    melt_out_date,
    peak,
    rank_ascending,
    spearman_rho,
    standardized_anomaly,
    water_year_slice,
)


def ramp(start: date, values) -> DailySeries:
    days = tuple(start + timedelta(days=i) for i in range(len(values)))
    return DailySeries(dates=days, values=np.asarray(values, dtype=float))


class TestPeak:
    def test_finds_the_maximum_and_its_date(self):
        s = ramp(date(2026, 1, 1), [1.0, 5.0, 3.0])
        p = peak(s)
        assert p.value == pytest.approx(5.0)
        assert p.day == date(2026, 1, 2)

    def test_ties_resolve_to_the_earliest_date(self):
        s = ramp(date(2026, 1, 1), [4.0, 4.0, 1.0])
        assert peak(s).day == date(2026, 1, 1)

    def test_missing_values_are_ignored(self):
        s = ramp(date(2026, 1, 1), [1.0, np.nan, 3.0])
        assert peak(s).value == pytest.approx(3.0)

    def test_an_all_missing_series_has_no_peak(self):
        s = ramp(date(2026, 1, 1), [np.nan, np.nan])
        assert np.isnan(peak(s).value)
        assert peak(s).day is None

    def test_daily_resolution_can_change_which_year_is_lowest(self):
        """Weekly sampling can miss a narrow peak and invert the ranking."""
        daily_a = ramp(date(2026, 1, 1), [10.0] * 3 + [60.0] + [10.0] * 3)
        daily_b = ramp(date(2026, 1, 1), [30.0] * 7)
        assert peak(daily_a).value > peak(daily_b).value
        weekly_a = ramp(date(2026, 1, 1), [10.0])
        assert peak(weekly_a).value < peak(daily_b).value


class TestAprilFirst:
    def test_reads_the_benchmark_date(self):
        s = ramp(date(2026, 3, 30), [1.0, 2.0, 3.0, 4.0])
        assert april_first(s, 2026) == pytest.approx(3.0)

    def test_missing_benchmark_day_is_nan(self):
        s = ramp(date(2026, 3, 1), [1.0, 2.0])
        assert np.isnan(april_first(s, 2026))


class TestMeltOut:
    def test_first_day_after_the_peak_below_the_threshold(self):
        s = ramp(date(2026, 1, 1), [5.0, 50.0, 30.0, 4.0, 1.0])
        assert melt_out_date(s, threshold=5.0) == date(2026, 1, 4)

    def test_low_values_before_the_peak_do_not_count(self):
        s = ramp(date(2026, 1, 1), [0.0, 1.0, 50.0, 0.5])
        assert melt_out_date(s, threshold=5.0) == date(2026, 1, 4)

    def test_a_pack_that_never_melts_out_returns_none(self):
        s = ramp(date(2026, 1, 1), [50.0, 60.0, 55.0])
        assert melt_out_date(s, threshold=5.0) is None

    def test_threshold_is_exclusive_below(self):
        s = ramp(date(2026, 1, 1), [50.0, 5.0, 4.9])
        assert melt_out_date(s, threshold=5.0) == date(2026, 1, 3)


class TestMeanOver:
    def test_averages_the_requested_span(self):
        s = ramp(date(2026, 1, 1), [1.0, 2.0, 3.0, 4.0])
        assert mean_over(s, date(2026, 1, 2), date(2026, 1, 3)) == pytest.approx(2.5)

    def test_ignores_missing_days(self):
        s = ramp(date(2026, 1, 1), [1.0, np.nan, 3.0])
        assert mean_over(s, date(2026, 1, 1), date(2026, 1, 3)) == pytest.approx(2.0)

    def test_an_empty_span_is_nan(self):
        s = ramp(date(2026, 1, 1), [1.0, 2.0])
        assert np.isnan(mean_over(s, date(2027, 1, 1), date(2027, 2, 1)))


class TestWaterYearSlice:
    def test_selects_october_through_september(self):
        s = ramp(date(2025, 9, 29), [0.0] * 370)
        wy = water_year_slice(s, 2026)
        assert wy.dates[0] == date(2025, 10, 1)
        assert wy.dates[-1] == date(2026, 9, 30)

    def test_a_year_with_no_data_is_empty(self):
        s = ramp(date(2026, 1, 1), [1.0, 2.0])
        assert len(water_year_slice(s, 1990).dates) == 0


class TestRanking:
    def test_rank_one_is_the_lowest(self):
        r = rank_ascending(np.array([30.0, 10.0, 20.0]))
        assert r.tolist() == [3, 1, 2]

    def test_a_record_low_gets_rank_one(self):
        values = np.array([80.0, 90.0, 32.5, 70.0])
        assert rank_ascending(values)[2] == 1

    def test_missing_values_do_not_take_a_rank(self):
        r = rank_ascending(np.array([30.0, np.nan, 10.0]))
        assert np.isnan(r[1])
        assert r[2] == 1

    def test_standardized_anomaly_is_zero_mean(self):
        values = np.array([1.0, 2.0, 3.0, 4.0])
        assert float(np.nanmean(standardized_anomaly(values))) == pytest.approx(0.0)

    def test_a_low_year_has_a_negative_anomaly(self):
        values = np.array([80.0, 90.0, 32.5, 70.0])
        assert standardized_anomaly(values)[2] < -1.0


class TestSpearman:
    def test_perfect_agreement(self):
        rho, p = spearman_rho(np.array([1.0, 2.0, 3.0]), np.array([10.0, 20.0, 30.0]))
        assert rho == pytest.approx(1.0)

    def test_perfect_disagreement(self):
        rho, _ = spearman_rho(np.array([1.0, 2.0, 3.0]), np.array([30.0, 20.0, 10.0]))
        assert rho == pytest.approx(-1.0)

    def test_rank_agreement_survives_a_magnitude_difference(self):
        """The models differ by 3x in magnitude but may still agree on order."""
        a = np.array([10.0, 20.0, 30.0, 40.0])
        rho, _ = spearman_rho(a, a * 3.12)
        assert rho == pytest.approx(1.0)

    def test_pairs_with_missing_values_are_dropped(self):
        rho, _ = spearman_rho(
            np.array([1.0, np.nan, 3.0, 4.0]), np.array([10.0, 20.0, 30.0, 40.0])
        )
        assert rho == pytest.approx(1.0)
