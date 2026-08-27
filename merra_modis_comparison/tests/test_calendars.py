"""Water-year calendar rules. Protects the contract's period definitions."""
from datetime import date

import pytest

from merra_modis_comparison.calendars import (
    NOV_MAY,
    WATER_YEAR_MONTH_ORDER,
    calendar_year_of,
    dates_in_month,
    enumerate_dates,
    month_tasks,
    season_of,
    water_year,
    water_year_month_position,
)


class TestWaterYear:
    def test_october_starts_the_next_water_year(self):
        assert water_year(date(2024, 10, 1)) == 2025

    def test_september_ends_the_current_water_year(self):
        assert water_year(date(2024, 9, 30)) == 2024

    def test_spring_belongs_to_the_water_year_of_its_calendar_year(self):
        assert water_year(date(2025, 5, 31)) == 2025

    @pytest.mark.parametrize("month,expected", [(10, 2025), (12, 2025)])
    def test_autumn_months_roll_forward(self, month, expected):
        assert water_year(date(2024, month, 15)) == expected


class TestCalendarYearOf:
    def test_autumn_month_of_a_water_year_is_the_previous_calendar_year(self):
        assert calendar_year_of(2025, 11) == 2024

    def test_spring_month_of_a_water_year_is_the_same_calendar_year(self):
        assert calendar_year_of(2025, 5) == 2025

    def test_round_trips_with_water_year(self):
        for wy in (2025, 2026):
            for month in WATER_YEAR_MONTH_ORDER:
                cy = calendar_year_of(wy, month)
                assert water_year(date(cy, month, 15)) == wy


class TestSeasons:
    @pytest.mark.parametrize(
        "d,expected",
        [
            (date(2024, 12, 1), "DJF"),
            (date(2025, 1, 31), "DJF"),
            (date(2025, 2, 28), "DJF"),
            (date(2025, 3, 1), "MAM"),
            (date(2025, 5, 31), "MAM"),
            (date(2025, 6, 1), "JJA"),
            (date(2025, 8, 31), "JJA"),
            (date(2024, 9, 1), "SON"),
            (date(2024, 11, 30), "SON"),
        ],
    )
    def test_meteorological_seasons(self, d, expected):
        assert season_of(d) == expected

    def test_every_month_maps_to_exactly_one_season(self):
        seen = {season_of(date(2025, m, 15)) for m in range(1, 13)}
        assert seen == {"DJF", "MAM", "JJA", "SON"}


class TestWaterYearMonthOrder:
    def test_october_is_first(self):
        assert WATER_YEAR_MONTH_ORDER[0] == 10
        assert water_year_month_position(10) == 1

    def test_september_is_last(self):
        assert WATER_YEAR_MONTH_ORDER[-1] == 9
        assert water_year_month_position(9) == 12

    def test_january_is_fourth(self):
        assert water_year_month_position(1) == 4

    def test_order_is_a_permutation_of_the_calendar(self):
        assert sorted(WATER_YEAR_MONTH_ORDER) == list(range(1, 13))


class TestNovMay:
    def test_is_the_snow_season_in_water_year_order(self):
        assert NOV_MAY == (11, 12, 1, 2, 3, 4, 5)

    def test_has_seven_months(self):
        assert len(NOV_MAY) == 7


class TestEnumeration:
    def test_month_tasks_are_calendar_year_month_pairs(self):
        tasks = month_tasks((2025,), NOV_MAY)
        assert tasks == [
            (2024, 11),
            (2024, 12),
            (2025, 1),
            (2025, 2),
            (2025, 3),
            (2025, 4),
            (2025, 5),
        ]

    def test_month_tasks_are_chronological_across_water_years(self):
        tasks = month_tasks((2025, 2026), NOV_MAY)
        assert tasks == sorted(tasks)
        assert len(tasks) == 14

    def test_dates_in_month_handles_month_length(self):
        assert len(dates_in_month(2025, 2)) == 28
        assert len(dates_in_month(2024, 2)) == 29
        assert len(dates_in_month(2024, 11)) == 30
        assert len(dates_in_month(2025, 1)) == 31

    def test_nov_may_water_year_has_212_days(self):
        assert len(enumerate_dates((2025,), NOV_MAY)) == 212
        assert len(enumerate_dates((2026,), NOV_MAY)) == 212

    def test_two_water_years_of_nov_may_is_424_days(self):
        dates = enumerate_dates((2025, 2026), NOV_MAY)
        assert len(dates) == 424
        assert dates == sorted(dates)
        assert len(set(dates)) == 424

    def test_enumerated_dates_stay_inside_their_water_years(self):
        for d in enumerate_dates((2025, 2026), NOV_MAY):
            assert water_year(d) in (2025, 2026)
            assert d.month in NOV_MAY

    def test_full_water_year_is_365_or_366_days(self):
        assert len(enumerate_dates((2025,), WATER_YEAR_MONTH_ORDER)) == 365
        # WY2024 contains 29 February 2024
        assert len(enumerate_dates((2024,), WATER_YEAR_MONTH_ORDER)) == 366
