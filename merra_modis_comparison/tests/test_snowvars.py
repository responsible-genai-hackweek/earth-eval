"""Snow variable conversions and area weighting.

Protects the two traps that would silently corrupt the headline number: MERRA-2
SNODP being a snow-covered-fraction depth rather than a grid-cell mean, and
latitude/longitude cells not being equal area.
"""
import numpy as np
import pytest

from merra_modis_comparison.snowvars import (
    FRESH_SNOW_DENSITY_KG_M3,
    WATER_DENSITY_KG_M3,
    cos_latitude_weights,
    domain_mean,
    geometric_depth_m,
    grid_mean_depth_m,
    implied_density_kg_m3,
    latitude_band_weights,
    swe_from_water_equivalent_m,
)


class TestGridMeanDepth:
    def test_depth_is_scaled_by_the_snow_covered_fraction(self):
        """SNODP is depth over the snow-covered fraction, not over the cell."""
        assert grid_mean_depth_m(frsno=0.5, snodp=0.4) == pytest.approx(0.2)

    def test_full_cover_leaves_depth_unchanged(self):
        assert grid_mean_depth_m(frsno=1.0, snodp=0.4) == pytest.approx(0.4)

    def test_no_cover_gives_no_depth(self):
        assert grid_mean_depth_m(frsno=0.0, snodp=0.4) == pytest.approx(0.0)

    def test_raw_snodp_overstates_a_patchy_cell(self):
        frsno, snodp = 0.06, 0.30
        assert grid_mean_depth_m(frsno, snodp) < snodp / 5

    def test_vectorised(self):
        frsno = np.array([0.0, 0.25, 1.0])
        snodp = np.array([0.4, 0.4, 0.4])
        np.testing.assert_allclose(grid_mean_depth_m(frsno, snodp), [0.0, 0.1, 0.4])

    def test_rejects_a_fraction_outside_zero_to_one(self):
        with pytest.raises(ValueError, match="frsno"):
            grid_mean_depth_m(frsno=1.4, snodp=0.4)

    def test_a_low_snow_year_is_not_flattered_by_the_wrong_formula(self):
        """The trap in numbers: raw SNODP makes a bare year look four tenths of a deep one."""
        deep = {"frsno": 0.90, "snodp": 0.45}
        bare = {"frsno": 0.06, "snodp": 0.19}
        wrong = bare["snodp"] / deep["snodp"]
        right = grid_mean_depth_m(**bare) / grid_mean_depth_m(**deep)
        assert wrong > 0.40
        assert right < 0.04
        assert wrong / right > 10


class TestImpliedDensity:
    def test_uses_grid_mean_depth_and_is_physical(self):
        rho = implied_density_kg_m3(swe_kg_m2=47.6, frsno=0.9, snodp=0.20)
        assert FRESH_SNOW_DENSITY_KG_M3 <= rho <= 600

    def test_using_raw_depth_gives_an_unphysical_value(self):
        """This asymmetry is how the convention mismatch was detected."""
        correct = implied_density_kg_m3(swe_kg_m2=4.9, frsno=0.06, snodp=0.19)
        naive = 4.9 / 0.19
        assert correct >= FRESH_SNOW_DENSITY_KG_M3
        assert naive < 30

    def test_snow_free_cell_has_undefined_density(self):
        assert np.isnan(implied_density_kg_m3(swe_kg_m2=0.0, frsno=0.0, snodp=0.0))


class TestUnitConversions:
    def test_water_equivalent_metres_convert_to_kilograms_per_square_metre(self):
        assert swe_from_water_equivalent_m(0.1) == pytest.approx(100.0)
        assert swe_from_water_equivalent_m(1.0) == pytest.approx(WATER_DENSITY_KG_M3)

    def test_geometric_depth_from_swe_and_density(self):
        assert geometric_depth_m(swe_kg_m2=100.0, density_kg_m3=250.0) == pytest.approx(0.4)

    def test_depth_exceeds_water_equivalent_because_snow_is_less_dense(self):
        swe_m = 0.1
        depth = geometric_depth_m(swe_from_water_equivalent_m(swe_m), 250.0)
        assert depth > swe_m
        assert depth == pytest.approx(swe_m * WATER_DENSITY_KG_M3 / 250.0)

    def test_zero_density_is_undefined_not_infinite(self):
        assert np.isnan(geometric_depth_m(swe_kg_m2=100.0, density_kg_m3=0.0))

    def test_round_trip(self):
        swe = swe_from_water_equivalent_m(0.25)
        depth = geometric_depth_m(swe, 300.0)
        assert depth * 300.0 == pytest.approx(swe)


class TestAreaWeights:
    def test_band_weights_are_exact_sine_differences(self):
        edges = np.array([36.75, 37.25, 37.75])
        w = latitude_band_weights(edges)
        expected = np.diff(np.sin(np.radians(edges)))
        np.testing.assert_allclose(w / w.sum(), expected / expected.sum())

    def test_southern_bands_are_larger_than_northern_ones(self):
        edges = np.linspace(36.75, 41.25, 10)
        w = latitude_band_weights(edges)
        assert w[0] > w[-1]

    def test_cos_approximation_is_close_to_the_exact_weights(self):
        edges = np.linspace(36.75, 41.25, 10)
        centers = (edges[:-1] + edges[1:]) / 2
        exact = latitude_band_weights(edges)
        approx = cos_latitude_weights(centers)
        np.testing.assert_allclose(
            exact / exact.sum(), approx / approx.sum(), rtol=2e-4
        )

    def test_weights_are_positive(self):
        assert np.all(latitude_band_weights(np.linspace(-90, 90, 20)) > 0)


class TestDomainMean:
    def test_weights_by_latitude_so_southern_cells_count_more(self):
        lat = np.array([37.0, 41.0])
        values = np.array([[1.0], [0.0]])
        assert domain_mean(values, lat) > 0.5

    def test_matches_the_plain_mean_when_all_rows_are_equal(self):
        lat = np.array([37.0, 38.0, 39.0])
        values = np.full((3, 4), 2.5)
        assert domain_mean(values, lat) == pytest.approx(2.5)

    def test_differs_from_an_unweighted_mean(self):
        lat = np.linspace(37.0, 41.0, 9)
        rng = np.random.default_rng(0)
        values = rng.uniform(0, 1, (9, 8))
        assert domain_mean(values, lat) != pytest.approx(values.mean(), abs=1e-9)

    def test_missing_cells_are_excluded_not_zeroed(self):
        lat = np.array([37.0, 41.0])
        values = np.array([[2.0], [np.nan]])
        assert domain_mean(values, lat) == pytest.approx(2.0)

    def test_all_missing_gives_nan(self):
        lat = np.array([37.0, 41.0])
        assert np.isnan(domain_mean(np.full((2, 1), np.nan), lat))

    def test_a_descending_latitude_axis_is_handled_not_silently_mismatched(self):
        lat_up = np.array([37.0, 38.0, 39.0])
        values_up = np.array([[1.0], [2.0], [3.0]])
        lat_down = lat_up[::-1]
        values_down = values_up[::-1]
        assert domain_mean(values_up, lat_up) == pytest.approx(
            domain_mean(values_down, lat_down)
        )

    def test_rejects_a_latitude_length_mismatch(self):
        with pytest.raises(ValueError, match="latitude"):
            domain_mean(np.zeros((3, 4)), np.array([37.0, 38.0]))
