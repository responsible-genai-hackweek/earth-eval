"""Granule filename and path resolution.

Protects: the MERRA-2 production-stream boundaries, which silently change the
filename mid-record, and the reference archive layout per era.
"""
from datetime import date

import pytest

from merra_modis_comparison.naming import merra2_granule, merra2_stream


class TestMerraStreams:
    @pytest.mark.parametrize(
        "day,stream",
        [
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

    def test_url_is_absolute_and_https(self):
        g = merra2_granule(date(2026, 2, 14))
        assert g.url.startswith("https://")
        assert g.url.endswith("/MERRA2_400.tavg1_2d_lnd_Nx.20260214.nc4")
