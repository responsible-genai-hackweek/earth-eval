"""Static pixel-to-cell mapping, expected support, and the coverage gate.

Protects the support denominator - the single number that decides whether the
80% rule can fire at all - and the tile-coverage gate that caught a cell whose
reference mean would have been computed from only its western 86%.
"""
import numpy as np
import pytest

from merra_modis_comparison.errors import DomainCoverageError
from merra_modis_comparison.grid import build_target_grid
from merra_modis_comparison.modis import tile_coordinates
from merra_modis_comparison.pixelmap import (
    assert_coverage,
    build_tile_window,
    coverage_report,
    global_expected_counts,
    reduce_tile,
)

ARCHIVED = ("h09v04", "h09v05", "h10v04")
ALL_FOUR = ("h09v04", "h09v05", "h10v04", "h10v05")


@pytest.fixture(scope="module")
def grid():
    return build_target_grid()


@pytest.fixture(scope="module")
def expected(grid):
    return global_expected_counts(grid)


class TestGlobalExpectedCounts:
    def test_total_matches_the_enumerated_envelope(self, expected):
        assert int(expected.sum()) == 1_006_923

    def test_per_cell_range(self, expected):
        assert int(expected.min()) == 13_580
        assert int(expected.max()) == 14_378

    def test_southern_cells_hold_more_equal_area_pixels(self, grid, expected):
        south = expected[grid.cell_index(0, 0)]
        north = expected[grid.cell_index(8, 0)]
        assert south > north

    def test_denominator_does_not_depend_on_the_configured_tiles(self, grid):
        """D2: a tile-derived denominator makes support 1.0 by construction."""
        three = coverage_report(grid, ARCHIVED)
        four = coverage_report(grid, ALL_FOUR)
        np.testing.assert_array_equal(three.expected, four.expected)

    def test_agrees_with_the_analytic_equal_area_count_within_a_tenth_percent(
        self, grid, expected
    ):
        analytic = grid.expected_pixels_per_cell(
            fine_pixel_area_m2=(1111950.5196666666 / 2400) ** 2
        )
        ratio = expected / analytic
        assert ratio.min() > 0.999
        assert ratio.max() < 1.001

    def test_the_analytic_count_is_not_safe_as_the_denominator(self, grid, expected):
        """It is smaller than the truth in many cells, so valid <= expected fails."""
        analytic = grid.expected_pixels_per_cell(
            fine_pixel_area_m2=(1111950.5196666666 / 2400) ** 2
        )
        assert np.any(expected > analytic)


class TestCoverageGate:
    def test_three_archived_tiles_leave_exactly_one_cell_short(self, grid):
        report = coverage_report(grid, ARCHIVED)
        assert report.deficient == (55,)

    def test_the_deficient_cell_is_identified_precisely(self, grid):
        report = coverage_report(grid, ARCHIVED)
        slot = report.deficient[0]
        assert grid.cell_ids[slot] == "j260_i121"
        assert grid.cell_center(slot) == pytest.approx((40.0, -104.375))
        assert report.available[slot] == 11_804
        assert report.expected[slot] == 13_788
        assert report.fraction[slot] == pytest.approx(0.856107, abs=1e-6)

    def test_the_deficit_would_pass_the_support_threshold_silently(self, grid):
        report = coverage_report(grid, ARCHIVED)
        assert report.fraction.min() > 0.80, "this is why the gate exists"

    def test_the_missing_pixels_live_in_the_unarchived_tile(self, grid):
        report = coverage_report(grid, ARCHIVED)
        assert "h10v05" in report.required_tiles
        assert report.missing_tiles == ("h10v05",)
        assert int((report.expected - report.available).sum()) == 1_984

    def test_all_four_tiles_cover_the_domain_completely(self, grid):
        report = coverage_report(grid, ALL_FOUR)
        assert report.deficient == ()
        np.testing.assert_array_equal(report.available, report.expected)
        assert report.missing_tiles == ()

    def test_the_gate_refuses_a_deficient_tile_set_by_default(self, grid):
        report = coverage_report(grid, ARCHIVED)
        with pytest.raises(DomainCoverageError, match="j260_i121"):
            assert_coverage(report, accept_deficit=False)

    def test_the_gate_can_be_overridden_explicitly(self, grid):
        report = coverage_report(grid, ARCHIVED)
        assert_coverage(report, accept_deficit=True)

    def test_a_complete_tile_set_passes_the_strict_gate(self, grid):
        assert_coverage(coverage_report(grid, ALL_FOUR), accept_deficit=False)


class TestTileWindow:
    def test_crops_before_transforming(self, grid):
        x, y = tile_coordinates("h09v05", 2400)
        window = build_tile_window("h09v05", grid, x, y)
        rows = window.row_stop - window.row_start
        cols = window.col_stop - window.col_start
        assert rows < 2400 and cols < 2400
        assert rows * cols < 2400 * 2400 // 2

    def test_window_indexes_the_granule_array_directly(self, grid):
        x, y = tile_coordinates("h09v04", 2400)
        window = build_tile_window("h09v04", grid, x, y)
        assert window.cell_index.shape == (
            window.row_stop - window.row_start,
            window.col_stop - window.col_start,
        )

    def test_pixels_outside_the_domain_are_marked_minus_one(self, grid):
        x, y = tile_coordinates("h09v04", 2400)
        window = build_tile_window("h09v04", grid, x, y)
        assert np.any(window.cell_index == -1)

    def test_tile_windows_partition_the_domain_without_double_counting(self, grid):
        total = np.zeros(grid.n_cells, dtype=np.int64)
        for tile in ALL_FOUR:
            x, y = tile_coordinates(tile, 2400)
            window = build_tile_window(tile, grid, x, y)
            idx = window.cell_index.ravel()
            np.add.at(total, idx[idx >= 0], 1)
        np.testing.assert_array_equal(total, global_expected_counts(grid))

    def test_a_tile_that_misses_the_domain_yields_an_empty_window(self, grid):
        x, y = tile_coordinates("h20v08", 2400)
        window = build_tile_window("h20v08", grid, x, y)
        assert window.is_empty


class TestReduction:
    def test_planted_values_reduce_to_their_cell_means(self, grid):
        x, y = tile_coordinates("h09v05", 2400)
        window = build_tile_window("h09v05", grid, x, y)
        values = np.zeros(window.cell_index.shape, dtype=np.float64)
        target = grid.cell_index(2, 3)
        values[window.cell_index == target] = 0.4
        valid = np.ones(values.shape, dtype=bool)

        sums, counts = reduce_tile(values, valid, window, grid.n_cells)
        assert counts[target] > 0
        assert sums[target] / counts[target] == pytest.approx(0.4)

    def test_invalid_pixels_are_excluded_from_both_sum_and_count(self, grid):
        x, y = tile_coordinates("h09v05", 2400)
        window = build_tile_window("h09v05", grid, x, y)
        values = np.full(window.cell_index.shape, 0.5)
        valid = np.ones(values.shape, dtype=bool)
        full_sums, full_counts = reduce_tile(values, valid, window, grid.n_cells)

        valid[::2, :] = False
        part_sums, part_counts = reduce_tile(values, valid, window, grid.n_cells)
        assert part_counts.sum() < full_counts.sum()
        assert np.all(part_sums <= full_sums + 1e-9)

    def test_fill_is_not_treated_as_zero_snow(self, grid):
        """Fill is a land/elevation screen, not an observation of no snow."""
        x, y = tile_coordinates("h09v05", 2400)
        window = build_tile_window("h09v05", grid, x, y)
        target = grid.cell_index(4, 4)
        in_cell = window.cell_index == target
        values = np.where(in_cell, 0.8, 0.0)
        valid = in_cell.copy()
        valid[np.nonzero(in_cell)[0][: in_cell.sum() // 2], :] = False

        sums, counts = reduce_tile(values, valid, window, grid.n_cells)
        assert sums[target] / counts[target] == pytest.approx(0.8)

    def test_reduction_is_exact_for_a_split_batch(self, grid):
        x, y = tile_coordinates("h09v04", 2400)
        window = build_tile_window("h09v04", grid, x, y)
        rng = np.random.default_rng(0)
        values = rng.uniform(0, 1, window.cell_index.shape)
        valid = rng.random(values.shape) > 0.3

        whole_s, whole_c = reduce_tile(values, valid, window, grid.n_cells)
        half = values.shape[0] // 2
        a_valid = valid.copy(); a_valid[half:, :] = False
        b_valid = valid.copy(); b_valid[:half, :] = False
        a_s, a_c = reduce_tile(values, a_valid, window, grid.n_cells)
        b_s, b_c = reduce_tile(values, b_valid, window, grid.n_cells)

        np.testing.assert_array_equal(a_c + b_c, whole_c)
        np.testing.assert_allclose(a_s + b_s, whole_s, rtol=1e-12)
