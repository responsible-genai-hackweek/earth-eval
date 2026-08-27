"""Fractional-overlap area weighting and conservative regridding.

Protects the requirement that both models average over the SAME geography. ERA5
cells do not align with the MERRA-2 domain envelope, so selecting whole cells
would compare two different regions and call the difference a model difference.
"""
import numpy as np
import pytest

from merra_modis_comparison.regrid import (
    conservative_matrix,
    domain_area_weights,
    edges_from_centers,
    latitude_overlap,
    longitude_overlap,
    to_zero_360,
)


class TestEdgesFromCenters:
    def test_regular_ascending_centers(self):
        e = edges_from_centers(np.array([0.0, 0.25, 0.5]))
        np.testing.assert_allclose(e, [-0.125, 0.125, 0.375, 0.625])

    def test_regular_descending_centers(self):
        e = edges_from_centers(np.array([41.0, 40.75, 40.5]))
        np.testing.assert_allclose(e, [41.125, 40.875, 40.625, 40.375])

    def test_one_more_edge_than_center(self):
        assert edges_from_centers(np.arange(9.0)).size == 10

    def test_merra_latitude_centers_reproduce_the_contract_envelope(self):
        e = edges_from_centers(np.arange(37.0, 41.5, 0.5))
        assert e[0] == pytest.approx(36.75)
        assert e[-1] == pytest.approx(41.25)

    def test_rejects_a_single_center(self):
        with pytest.raises(ValueError, match="at least two"):
            edges_from_centers(np.array([1.0]))


class TestLongitudeOverlap:
    def test_a_cell_fully_inside_contributes_its_full_width(self):
        edges = np.array([-107.0, -106.75, -106.5])
        w = longitude_overlap(edges, -108.0, -105.0)
        np.testing.assert_allclose(w, [0.25, 0.25])

    def test_a_cell_outside_contributes_nothing(self):
        edges = np.array([-100.0, -99.75])
        assert longitude_overlap(edges, -109.0, -104.0)[0] == 0.0

    def test_a_straddling_cell_contributes_only_its_inside_part(self):
        # cell spans -109.125..-108.875; the domain edge at -109.0625 cuts it,
        # leaving -109.0625..-108.875 = 0.1875 of its 0.25 degree width inside
        edges = np.array([-109.125, -108.875])
        w = longitude_overlap(edges, -109.0625, -104.0625)
        assert w[0] == pytest.approx(0.1875)

    def test_total_overlap_equals_the_domain_width(self):
        edges = np.arange(-112.0, -101.0, 0.25)
        w = longitude_overlap(edges, -109.0625, -104.0625)
        assert w.sum() == pytest.approx(5.0)


class TestLatitudeOverlap:
    def test_uses_sine_differences_not_degree_widths(self):
        edges = np.array([36.75, 37.25])
        w = latitude_overlap(edges, 36.75, 41.25)
        expected = np.sin(np.radians(37.25)) - np.sin(np.radians(36.75))
        assert w[0] == pytest.approx(expected)

    def test_total_overlap_equals_the_domain_band(self):
        edges = np.arange(30.0, 50.25, 0.25)
        w = latitude_overlap(edges, 36.75, 41.25)
        expected = np.sin(np.radians(41.25)) - np.sin(np.radians(36.75))
        assert w.sum() == pytest.approx(expected)

    def test_handles_a_descending_edge_array(self):
        asc = latitude_overlap(np.array([36.75, 37.25, 37.75]), 36.75, 41.25)
        desc = latitude_overlap(np.array([37.75, 37.25, 36.75]), 36.75, 41.25)
        np.testing.assert_allclose(asc, desc[::-1])

    def test_southern_cells_weigh_more_than_northern_ones(self):
        edges = np.arange(36.75, 41.5, 0.25)
        w = latitude_overlap(edges, 36.75, 41.25)
        assert w[0] > w[-1]


class TestDomainAreaWeights:
    ENVELOPE = (-109.0625, -104.0625, 36.75, 41.25)

    def test_merra_cells_tile_the_envelope_exactly(self):
        lat = np.arange(37.0, 41.5, 0.5)
        lon = np.arange(-108.75, -104.0, 0.625)
        w = domain_area_weights(lat, lon, *self.ENVELOPE)
        assert w.shape == (9, 8)
        assert np.all(w > 0), "every MERRA cell lies wholly inside its own envelope"

    def test_era5_cells_are_clipped_at_the_envelope(self):
        lat = np.arange(41.25, 36.5, -0.25)
        lon = to_zero_360(np.arange(-109.0, -104.0, 0.25))
        w = domain_area_weights(lat, lon, *self.ENVELOPE)
        assert np.any(w == 0.0) or w.min() < w.max() / 2, "edge cells partially covered"

    def test_both_grids_cover_the_same_total_area(self):
        merra = domain_area_weights(
            np.arange(37.0, 41.5, 0.5), np.arange(-108.75, -104.0, 0.625), *self.ENVELOPE
        )
        era5 = domain_area_weights(
            np.arange(41.25, 36.5, -0.25),
            to_zero_360(np.arange(-110.0, -103.0, 0.25)),
            *self.ENVELOPE,
        )
        assert era5.sum() == pytest.approx(merra.sum(), rel=1e-9)

    def test_a_constant_field_has_the_same_domain_mean_on_either_grid(self):
        """The property that makes a cross-model domain mean meaningful."""
        merra_w = domain_area_weights(
            np.arange(37.0, 41.5, 0.5), np.arange(-108.75, -104.0, 0.625), *self.ENVELOPE
        )
        era5_w = domain_area_weights(
            np.arange(41.25, 36.5, -0.25),
            to_zero_360(np.arange(-110.0, -103.0, 0.25)),
            *self.ENVELOPE,
        )
        a = (np.full(merra_w.shape, 7.5) * merra_w).sum() / merra_w.sum()
        b = (np.full(era5_w.shape, 7.5) * era5_w).sum() / era5_w.sum()
        assert a == pytest.approx(b)

    def test_weights_outside_the_envelope_are_zero(self):
        lat = np.arange(41.25, 36.5, -0.25)
        lon = to_zero_360(np.arange(-120.0, -100.0, 0.25))
        w = domain_area_weights(lat, lon, *self.ENVELOPE)
        assert w[:, 0].sum() == 0.0
        assert w[:, -1].sum() == 0.0


class TestZeroTo360:
    def test_converts_western_longitudes(self):
        np.testing.assert_allclose(to_zero_360(np.array([-109.0625])), [250.9375])

    def test_leaves_eastern_longitudes_alone(self):
        np.testing.assert_allclose(to_zero_360(np.array([12.5])), [12.5])

    def test_colorado_maps_into_the_era5_convention(self):
        lo, hi = to_zero_360(np.array([-109.0625, -104.0625]))
        assert lo == pytest.approx(250.9375)
        assert hi == pytest.approx(255.9375)
        assert lo < hi, "the domain must not wrap the prime meridian"


class TestConservativeMatrix:
    def test_rows_sum_to_the_source_cell_overlap(self):
        src = np.arange(0.0, 2.25, 0.25)
        dst = np.arange(0.0, 2.5, 0.5)
        m = conservative_matrix(src, dst)
        np.testing.assert_allclose(m.sum(axis=1), np.diff(src))

    def test_a_constant_field_regrids_to_the_same_constant(self):
        """Conservative regridding must not change a uniform field."""
        src = np.arange(0.0, 5.25, 0.25)
        dst = np.array([0.0, 0.625, 1.25, 1.875, 2.5, 3.125, 3.75, 4.375, 5.0])
        m = conservative_matrix(src, dst)
        values = np.full(src.size - 1, 3.25)
        out = (m * values[:, None]).sum(axis=0) / m.sum(axis=0)
        np.testing.assert_allclose(out, 3.25)

    def test_total_mass_is_conserved(self):
        src = np.arange(0.0, 5.25, 0.25)
        dst = np.arange(0.0, 5.5, 0.5)
        m = conservative_matrix(src, dst)
        rng = np.random.default_rng(0)
        values = rng.uniform(0, 10, src.size - 1)
        src_mass = (values * np.diff(src)).sum()
        dst_mass = (m * values[:, None]).sum()
        assert dst_mass == pytest.approx(src_mass)

    def test_non_overlapping_grids_give_a_zero_matrix(self):
        m = conservative_matrix(np.array([0.0, 1.0]), np.array([10.0, 11.0]))
        assert m.sum() == 0.0
