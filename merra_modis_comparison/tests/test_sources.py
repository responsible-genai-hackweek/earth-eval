"""Source-layer logic that does not need the network.

Protects the silent-failure modes: ERA5's padded time axis, its 0..360 longitude
and descending latitude, the final/ERA5T boundary, and MERRA-2 DAP4 constraint
encoding where an unencoded bracket returns HTTP 400 before the server parses it.
"""
from datetime import date

import numpy as np
import pytest

from merra_modis_comparison.sources.era5 import (
    ERA5_STORE,
    classify_stream,
    colorado_lat_slice,
    colorado_lon_bounds,
    ensure_covered,
    hour_index_range,
)
from merra_modis_comparison.sources.merra2 import (
    MERRA2_LAT_SLICE,
    MERRA2_LON_SLICE,
    dap4_constraint,
    granule_url,
    validate_subset,
)


class TestEra5Window:
    def test_latitude_slice_is_descending_to_match_the_axis(self):
        lo, hi = colorado_lat_slice()
        assert lo > hi, "ERA5 latitude descends; an ascending slice returns nothing"
        assert (lo, hi) == (41.25, 36.75)

    def test_longitude_bounds_use_the_zero_to_360_convention(self):
        west, east = colorado_lon_bounds()
        assert west == pytest.approx(250.9375)
        assert east == pytest.approx(255.9375)
        assert 0.0 <= west < east <= 360.0

    def test_a_negative_longitude_would_not_appear_in_the_bounds(self):
        assert all(v >= 0 for v in colorado_lon_bounds())

    def test_store_path_is_the_rolling_one(self):
        assert ERA5_STORE.endswith("full_37-1h-0p25deg-chunk-1.zarr-v3")


class TestEra5Coverage:
    START = date(1940, 1, 1)
    FINAL = date(2026, 4, 30)
    T_STOP = date(2026, 8, 20)

    def test_a_date_inside_final_era5_is_final(self):
        assert classify_stream(date(2026, 4, 1), self.FINAL, self.T_STOP) == "final"

    def test_a_date_after_the_final_boundary_is_era5t(self):
        assert classify_stream(date(2026, 5, 1), self.FINAL, self.T_STOP) == "era5t"

    def test_the_boundary_day_itself_is_final(self):
        assert classify_stream(self.FINAL, self.FINAL, self.T_STOP) == "final"

    def test_the_april_benchmark_does_not_rest_on_provisional_data(self):
        assert classify_stream(date(2026, 4, 1), self.FINAL, self.T_STOP) == "final"

    def test_a_date_past_the_data_is_refused_rather_than_read_as_nan(self):
        """The axis runs to 2050 but the data stops; absent chunks read as NaN."""
        with pytest.raises(ValueError, match="beyond"):
            ensure_covered(date(2030, 1, 1), self.START, self.T_STOP)

    def test_a_date_before_the_data_is_refused(self):
        with pytest.raises(ValueError, match="before"):
            ensure_covered(date(1930, 1, 1), self.START, self.T_STOP)

    def test_a_covered_date_passes(self):
        ensure_covered(date(2026, 3, 7), self.START, self.T_STOP)


class TestEra5HourIndex:
    def test_a_day_is_twenty_four_consecutive_hours(self):
        start, stop = hour_index_range(date(2026, 3, 15), date(1900, 1, 1))
        assert stop - start == 24

    def test_indices_count_hours_since_the_epoch(self):
        start, _ = hour_index_range(date(1900, 1, 2), date(1900, 1, 1))
        assert start == 24

    def test_consecutive_days_are_contiguous(self):
        _, stop = hour_index_range(date(2026, 3, 15), date(1900, 1, 1))
        nxt, _ = hour_index_range(date(2026, 3, 16), date(1900, 1, 1))
        assert stop == nxt


class TestMerra2Constraint:
    def test_brackets_are_percent_encoded(self):
        ce = dap4_constraint(("FRSNO",))
        assert "[" not in ce and "]" not in ce
        assert "%5B" in ce and "%5D" in ce

    def test_slashes_are_percent_encoded(self):
        assert "%2F" in dap4_constraint(("FRSNO",))

    def test_every_requested_variable_appears(self):
        ce = dap4_constraint(("FRSNO", "SNODP", "SNOMAS"))
        for name in ("FRSNO", "SNODP", "SNOMAS"):
            assert name in ce

    def test_coordinates_are_requested_so_the_subset_can_be_verified(self):
        ce = dap4_constraint(("FRSNO",))
        assert "lat" in ce and "lon" in ce and "time" in ce

    def test_index_ranges_are_the_dap4_inclusive_form(self):
        ce = dap4_constraint(("FRSNO",))
        assert "254" in ce and "262" in ce
        assert "114" in ce and "121" in ce

    def test_numpy_slices_are_the_exclusive_form(self):
        assert MERRA2_LAT_SLICE == slice(254, 263)
        assert MERRA2_LON_SLICE == slice(114, 122)

    def test_all_hours_are_requested_by_default(self):
        assert "0%3A23" in dap4_constraint(("FRSNO",))

    def test_a_single_hour_can_be_requested(self):
        assert "15%3A15" in dap4_constraint(("FRSNO",), hours=(15, 15))

    def test_rejects_an_empty_variable_list(self):
        with pytest.raises(ValueError, match="variable"):
            dap4_constraint(())


class TestMerra2Url:
    def test_url_carries_the_granule_ur_with_an_encoded_colon(self):
        url = granule_url(date(2000, 11, 15), ("FRSNO",))
        assert "M2T1NXLND.5.12.4%3AMERRA2_200" in url
        assert ".dap.nc4?" in url

    def test_url_uses_the_cloud_endpoint_not_the_retired_one(self):
        url = granule_url(date(2023, 1, 15), ("FRSNO",))
        assert "opendap.earthdata.nasa.gov" in url
        assert "goldsmr4" not in url

    def test_the_stream_changes_with_the_date(self):
        assert "MERRA2_300" in granule_url(date(2005, 1, 1), ("FRSNO",))
        assert "MERRA2_401" in granule_url(date(2021, 7, 1), ("FRSNO",))


class TestSubsetValidation:
    LAT = np.arange(37.0, 41.5, 0.5)
    LON = np.arange(-108.75, -104.0, 0.625)

    def test_a_correct_subset_passes(self):
        validate_subset(np.zeros((24, 9, 8)), self.LAT, self.LON, date(2023, 1, 15),
                        "minutes since 2023-01-15 00:30:00")

    def test_a_wrong_shape_is_rejected(self):
        with pytest.raises(ValueError, match="shape"):
            validate_subset(np.zeros((24, 9, 7)), self.LAT, self.LON[:7],
                            date(2023, 1, 15), "minutes since 2023-01-15 00:30:00")

    def test_a_mismatched_date_in_the_time_units_is_rejected(self):
        """Catches a mis-built URL that silently returned another day."""
        with pytest.raises(ValueError, match="time units"):
            validate_subset(np.zeros((24, 9, 8)), self.LAT, self.LON,
                            date(2023, 1, 15), "minutes since 2023-01-16 00:30:00")

    def test_shifted_coordinates_are_rejected(self):
        with pytest.raises(ValueError, match="latitude"):
            validate_subset(np.zeros((24, 9, 8)), self.LAT + 4.0, self.LON,
                            date(2023, 1, 15), "minutes since 2023-01-15 00:30:00")

    def test_fill_values_are_reported_not_silently_averaged(self):
        values = np.zeros((24, 9, 8))
        values[0, 0, 0] = 9.99999987e14
        with pytest.raises(ValueError, match="fill"):
            validate_subset(values, self.LAT, self.LON, date(2023, 1, 15),
                            "minutes since 2023-01-15 00:30:00")
