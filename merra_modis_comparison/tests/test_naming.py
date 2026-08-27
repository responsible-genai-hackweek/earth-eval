"""Granule filename and path resolution.

Protects: the MERRA-2 production-stream boundaries, which silently change the
filename mid-record, and the reference archive layout per era.
"""
from datetime import date

import pytest

from merra_modis_comparison.naming import merra2_granule, merra2_stream


class TestMerraStreams:
    """Boundaries from an exhaustive scan of every month directory 1999-2026."""

    @pytest.mark.parametrize(
        "day,stream",
        [
            (date(1980, 1, 1), 100),
            (date(1991, 12, 31), 100),
            (date(1992, 1, 1), 200),
            (date(1999, 10, 1), 200),
            (date(2000, 1, 1), 200),
            (date(2000, 9, 15), 200),
            (date(2000, 12, 31), 200),
            (date(2001, 1, 1), 300),
            (date(2001, 2, 15), 300),
            (date(2008, 12, 1), 300),
            (date(2009, 10, 1), 300),
            (date(2010, 12, 31), 300),
            (date(2011, 1, 1), 400),
            (date(2019, 6, 15), 400),
            (date(2023, 9, 30), 400),
            (date(2025, 3, 15), 400),
            (date(2026, 5, 31), 400),
        ],
    )
    def test_stream_by_date(self, day, stream):
        assert merra2_stream(day) == stream

    @pytest.mark.parametrize(
        "day",
        [date(2020, 9, 1), date(2020, 9, 30), date(2021, 6, 1), date(2021, 9, 30)],
    )
    def test_reprocessed_months_use_stream_401(self, day):
        assert merra2_stream(day) == 401

    @pytest.mark.parametrize(
        "day", [date(2020, 8, 31), date(2020, 10, 1), date(2021, 5, 31), date(2021, 10, 1)]
    )
    def test_dates_bracketing_the_reprocessed_months_do_not(self, day):
        assert merra2_stream(day) == 400

    def test_the_stream_boundary_is_the_2011_new_year(self):
        assert merra2_stream(date(2010, 12, 31)) == 300
        assert merra2_stream(date(2011, 1, 1)) == 400

    def test_the_200_to_300_changeover_is_the_2001_new_year(self):
        """Not mid-2000, which is the tempting guess. All 366 days of 2000 are 200."""
        assert merra2_stream(date(2000, 12, 31)) == 200
        assert merra2_stream(date(2001, 1, 1)) == 300

    def test_the_100_to_200_changeover_is_the_1992_new_year(self):
        assert merra2_stream(date(1991, 12, 31)) == 100
        assert merra2_stream(date(1992, 1, 1)) == 200

    def test_the_two_401_windows_are_different_lengths(self):
        """2020 is one month; 2021 is four. A symmetric rule misses Aug and Sep 2021."""
        assert [merra2_stream(date(2020, m, 15)) for m in (8, 9, 10)] == [400, 401, 400]
        assert [merra2_stream(date(2021, m, 15)) for m in (5, 6, 7, 8, 9, 10)] == [
            400, 401, 401, 401, 401, 400,
        ]

    def test_stream_400_resumes_between_the_two_401_windows(self):
        assert merra2_stream(date(2020, 10, 1)) == 400
        assert merra2_stream(date(2021, 5, 31)) == 400

    def test_every_day_of_the_analysis_period_resolves_to_a_known_stream(self):
        from datetime import timedelta

        day, last = date(1980, 10, 1), date(2026, 8, 1)
        while day <= last:
            assert merra2_stream(day) in (100, 200, 300, 400, 401)
            day += timedelta(days=1)


class TestMerraGranule:
    def test_filename_matches_the_archive(self):
        g = merra2_granule(date(2023, 1, 15))
        assert g.filename == "MERRA2_400.tavg1_2d_lnd_Nx.20230115.nc4"

    def test_path_is_year_and_zero_padded_month(self):
        g = merra2_granule(date(2009, 10, 1))
        assert g.filename == "MERRA2_300.tavg1_2d_lnd_Nx.20091001.nc4"
        assert g.archive_path.endswith("M2T1NXLND.5.12.4/2009/10")

    def test_reprocessed_month_filename(self):
        g = merra2_granule(date(2021, 7, 4))
        assert g.filename == "MERRA2_401.tavg1_2d_lnd_Nx.20210704.nc4"

    def test_an_early_granule_uses_stream_200(self):
        g = merra2_granule(date(2000, 11, 15))
        assert g.filename == "MERRA2_200.tavg1_2d_lnd_Nx.20001115.nc4"

    def test_url_is_absolute_and_https(self):
        g = merra2_granule(date(2026, 2, 14))
        assert g.url.startswith("https://")
        assert g.url.endswith("/MERRA2_400.tavg1_2d_lnd_Nx.20260214.nc4")
