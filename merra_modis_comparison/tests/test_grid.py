"""Target-grid construction and pixel-center binning.

Protects: the 72-cell domain, complete-cell edge derivation, the pixel-center
membership rule, and the stable row order that checkpoints depend on.
"""
import numpy as np
import pytest

from merra_modis_comparison.grid import TargetGrid, build_target_grid


@pytest.fixture(scope="module")
def grid() -> TargetGrid:
    return build_target_grid()


class TestDomainSelection:
    def test_has_72_cells(self, grid):
        assert grid.n_cells == 72
        assert (grid.n_lat, grid.n_lon) == (9, 8)

    def test_latitude_centers_match_the_contract(self, grid):
        np.testing.assert_allclose(
            grid.lat_centers, [37.0, 37.5, 38.0, 38.5, 39.0, 39.5, 40.0, 40.5, 41.0]
        )

    def test_longitude_centers_match_the_contract(self, grid):
        np.testing.assert_allclose(
            grid.lon_centers,
            [-108.75, -108.125, -107.5, -106.875, -106.25, -105.625, -105.0, -104.375],
        )

    def test_global_merra_indices_match_the_published_grid(self, grid):
        np.testing.assert_array_equal(grid.lat_indices, np.arange(254, 263))
        np.testing.assert_array_equal(grid.lon_indices, np.arange(114, 122))

    def test_selection_is_by_center_not_by_overlap(self, grid):
        # every selected center lies inside the requested bounds ...
        assert grid.lon_centers.min() >= -109.0
        assert grid.lon_centers.max() <= -104.0
        # ... while the complete cells extend beyond them
        assert grid.lon_edges.min() < -109.0


class TestCompleteCellEdges:
    def test_envelope_matches_the_contract(self, grid):
        assert grid.lon_edges[0] == pytest.approx(-109.0625)
        assert grid.lon_edges[-1] == pytest.approx(-104.0625)
        assert grid.lat_edges[0] == pytest.approx(36.75)
        assert grid.lat_edges[-1] == pytest.approx(41.25)

    def test_edges_bracket_every_center(self, grid):
        assert np.all(grid.lon_edges[:-1] < grid.lon_centers)
        assert np.all(grid.lon_centers < grid.lon_edges[1:])
        assert np.all(grid.lat_edges[:-1] < grid.lat_centers)
        assert np.all(grid.lat_centers < grid.lat_edges[1:])

    def test_edges_are_contiguous_with_no_gaps(self, grid):
        np.testing.assert_allclose(np.diff(grid.lon_edges), 0.625)
        np.testing.assert_allclose(np.diff(grid.lat_edges), 0.5)

    def test_edges_are_derived_from_spacing_not_from_data_extent(self, grid):
        # half a cell beyond the outermost centers, in both directions
        assert grid.lon_edges[0] == pytest.approx(grid.lon_centers[0] - 0.3125)
        assert grid.lat_edges[-1] == pytest.approx(grid.lat_centers[-1] + 0.25)


class TestStableRowOrder:
    def test_cell_ids_are_unique(self, grid):
        assert len(set(grid.cell_ids)) == 72

    def test_cell_ids_encode_global_indices(self, grid):
        assert grid.cell_ids[0] == "j254_i114"
        assert grid.cell_ids[-1] == "j262_i121"

    def test_row_major_south_to_north_west_to_east(self, grid):
        assert grid.cell_index(0, 0) == 0
        assert grid.cell_index(0, 7) == 7
        assert grid.cell_index(1, 0) == 8
        assert grid.cell_index(8, 7) == 71

    def test_cell_centers_align_with_cell_ids(self, grid):
        lat, lon = grid.cell_center(grid.cell_index(3, 5))
        assert lat == pytest.approx(38.5)
        assert lon == pytest.approx(-105.625)


class TestPixelCenterBinning:
    def test_a_center_lands_in_its_own_cell(self, grid):
        idx = grid.assign(np.array([-105.625]), np.array([38.5]))
        assert idx[0] == grid.cell_index(3, 5)

    def test_points_outside_the_domain_are_rejected(self, grid):
        lon = np.array([-120.0, -100.0, -106.0, -106.0])
        lat = np.array([39.0, 39.0, 20.0, 60.0])
        assert np.all(grid.assign(lon, lat) == -1)

    def test_a_point_just_inside_the_envelope_is_accepted(self, grid):
        idx = grid.assign(np.array([-109.0624]), np.array([36.7501]))
        assert idx[0] == 0

    def test_a_point_just_outside_the_envelope_is_rejected(self, grid):
        idx = grid.assign(np.array([-109.0626]), np.array([36.7499]))
        assert idx[0] == -1

    def test_cells_are_half_open_so_an_edge_point_belongs_to_the_upper_cell(self, grid):
        # the shared edge between the first and second longitude columns
        edge = grid.lon_edges[1]
        idx = grid.assign(np.array([edge]), np.array([39.0]))
        lat_pos = int(np.searchsorted(grid.lat_edges, 39.0, side="right") - 1)
        assert idx[0] == grid.cell_index(lat_pos, 1)

    def test_every_cell_is_reachable(self, grid):
        lon, lat = np.meshgrid(grid.lon_centers, grid.lat_centers)
        idx = grid.assign(lon.ravel(), lat.ravel())
        assert sorted(idx.tolist()) == list(range(72))

    def test_assignment_is_vectorised_and_order_preserving(self, grid):
        lon = np.array([-108.75, -104.375, -108.75])
        lat = np.array([37.0, 41.0, 41.0])
        idx = grid.assign(lon, lat)
        assert idx.tolist() == [0, 71, 64]

    def test_non_finite_coordinates_are_rejected(self, grid):
        idx = grid.assign(np.array([np.nan, -106.0]), np.array([39.0, np.inf]))
        assert idx.tolist() == [-1, -1]


class TestModelCoordinateValidation:
    def test_accepts_the_expected_subset(self, grid):
        grid.validate_model_coordinates(grid.lat_centers, grid.lon_centers)

    def test_rejects_a_shifted_subset(self, grid):
        with pytest.raises(ValueError, match="latitude"):
            grid.validate_model_coordinates(grid.lat_centers + 0.5, grid.lon_centers)

    def test_rejects_a_wrong_shape(self, grid):
        with pytest.raises(ValueError, match="shape"):
            grid.validate_model_coordinates(grid.lat_centers[:-1], grid.lon_centers)

    def test_rejects_a_descending_latitude_axis(self, grid):
        with pytest.raises(ValueError, match="latitude"):
            grid.validate_model_coordinates(grid.lat_centers[::-1], grid.lon_centers)


class TestExpectedSupport:
    def test_expected_pixel_count_is_uniform_for_complete_cells(self, grid):
        counts = grid.expected_pixels_per_cell(fine_pixel_area_m2=463.31271653 ** 2)
        assert counts.shape == (72,)
        # a 0.625 x 0.5 degree cell shrinks with latitude, so the southern row
        # must hold more 500 m pixels than the northern row
        assert counts[0] > counts[-1]
        assert np.all(counts > 0)
