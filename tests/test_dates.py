from datetime import date

from fsca_eval import config, dates


def test_water_year_of_boundaries():
    assert dates.water_year_of(date(2009, 9, 30)) == 2009
    assert dates.water_year_of(date(2009, 10, 1)) == 2010
    assert dates.water_year_of(date(2010, 9, 30)) == 2010
    assert dates.water_year_of(date(2010, 10, 1)) == 2011


def test_water_year_start_end():
    assert dates.water_year_start_date(2010) == date(2009, 10, 1)
    assert dates.water_year_end_date(2010) == date(2010, 9, 30)


def test_iter_water_years_range():
    years = list(dates.iter_water_years())
    assert years[0] == config.WY_START
    assert years[-1] == config.WY_END
    assert len(years) == config.N_WATER_YEARS == 14


def test_calendar_month_for_water_year_order():
    assert dates.calendar_month_for_water_year(2010, 0) == (2009, 10)
    assert dates.calendar_month_for_water_year(2010, 2) == (2009, 12)
    assert dates.calendar_month_for_water_year(2010, 3) == (2010, 1)
    assert dates.calendar_month_for_water_year(2010, 11) == (2010, 9)


def test_iter_calendar_months_count_and_uniqueness():
    months = list(dates.iter_calendar_months())
    assert len(months) == config.N_MONTHS == 168
    assert len(set((y, m) for _, y, m in months)) == 168
    # every water year appears exactly 12 times
    from collections import Counter

    counts = Counter(wy for wy, _, _ in months)
    assert set(counts.values()) == {12}


def test_iter_dates_in_month_count():
    assert len(list(dates.iter_dates_in_month(2020, 2))) == 29  # leap year
    assert len(list(dates.iter_dates_in_month(2021, 2))) == 28
    assert len(list(dates.iter_dates_in_month(2021, 1))) == 31


def test_iter_all_dates_total_count():
    # 14 water years, WY2010-2023 = 2009-10-01 through 2023-09-30
    total = len(list(dates.iter_all_dates()))
    assert total == 5113


def test_merra_stream_early_late_boundary():
    assert dates.merra_stream_for_date(date(2010, 12, 31)) == config.MERRA_STREAM_EARLY
    assert dates.merra_stream_for_date(date(2011, 1, 1)) == config.MERRA_STREAM_LATE


def test_merra_stream_reprocessed_exceptions():
    assert dates.merra_stream_for_date(date(2020, 9, 15)) == config.MERRA_STREAM_REPROCESSED
    assert dates.merra_stream_for_date(date(2021, 6, 1)) == config.MERRA_STREAM_REPROCESSED
    assert dates.merra_stream_for_date(date(2021, 9, 30)) == config.MERRA_STREAM_REPROCESSED
    # adjacent months are NOT reprocessed
    assert dates.merra_stream_for_date(date(2021, 5, 31)) == config.MERRA_STREAM_LATE
    assert dates.merra_stream_for_date(date(2021, 10, 1)) == config.MERRA_STREAM_LATE
    assert dates.merra_stream_for_date(date(2020, 8, 31)) == config.MERRA_STREAM_LATE
    assert dates.merra_stream_for_date(date(2020, 10, 1)) == config.MERRA_STREAM_LATE
