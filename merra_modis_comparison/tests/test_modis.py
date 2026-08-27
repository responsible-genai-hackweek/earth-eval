"""MODIS sinusoidal tile algebra and the projection transform.

Protects: equal-area pixel geometry, the descending y axis, pixel centers vs
corners, and the tile bounds that decide which tiles the domain needs.
"""
import numpy as np
import pytest

from merra_modis_comparison.modis import (
    GLOBAL_X_MAX,
    MODIS_SPHERE_RADIUS_M,
    TILE_SIZE_M,
    nominal_pixel_size_m,
    sinusoidal_to_lonlat,
    tile_bounds,
    tile_coordinates,
    tiles_covering,
)


class TestGlobalConstants:
    def test_tile_size_is_one_eighteenth_of_the_global_extent(self):
        assert TILE_SIZE_M == pytest.approx(GLOBAL_X_MAX / 18)

    def test_nominal_500m_pixel_size(self):
        assert nominal_pixel_size_m(2400) == pytest.approx(463.3127165, abs=1e-6)

    def test_a_375m_grid_is_finer(self):
        assert nominal_pixel_size_m(3000) < nominal_pixel_size_m(2400)


class TestTileBounds:
    def test_h09v04_is_where_the_algebra_says(self):
        # published MODIS grid constants, quoted to millimetre precision
        b = tile_bounds("h09v04")
        assert b.x_min == pytest.approx(-10007554.677, abs=0.01)
        assert b.x_max == pytest.approx(-8895604.157, abs=0.01)
        assert b.y_max == pytest.approx(5559752.598, abs=0.01)
        assert b.y_min == pytest.approx(4447802.079, abs=0.01)

    def test_v04_sits_north_of_v05(self):
        assert tile_bounds("h09v04").y_min >= tile_bounds("h09v05").y_max - 1e-6

    def test_h10_sits_east_of_h09(self):
        assert tile_bounds("h10v04").x_min >= tile_bounds("h09v04").x_max - 1e-6

    def test_the_v04_v05_seam_is_40_degrees_north(self):
        seam_y = tile_bounds("h09v04").y_min
        lat = np.degrees(seam_y / MODIS_SPHERE_RADIUS_M)
        assert lat == pytest.approx(40.0, abs=1e-6)

    @pytest.mark.parametrize("bad", ["h9v4", "x09v04", "h09", "", "h99v99"])
    def test_malformed_tile_names_are_rejected(self, bad):
        with pytest.raises(ValueError):
            tile_bounds(bad)


class TestTileCoordinates:
    def test_x_ascends_and_y_descends(self):
        x, y = tile_coordinates("h09v04", 2400)
        assert np.all(np.diff(x) > 0)
        assert np.all(np.diff(y) < 0), "row 0 must be the northern edge"

    def test_coordinates_are_pixel_centers_not_corners(self):
        x, y = tile_coordinates("h09v04", 2400)
        b = tile_bounds("h09v04")
        half = nominal_pixel_size_m(2400) / 2
        assert x[0] == pytest.approx(b.x_min + half)
        assert y[0] == pytest.approx(b.y_max - half)

    def test_reconstructing_the_corner_from_the_center_recovers_the_bound(self):
        x, y = tile_coordinates("h09v04", 2400)
        b = tile_bounds("h09v04")
        half = nominal_pixel_size_m(2400) / 2
        assert x[0] - half == pytest.approx(b.x_min)
        assert y[0] + half == pytest.approx(b.y_max)

    def test_spacing_is_uniform(self):
        x, _ = tile_coordinates("h09v04", 2400)
        np.testing.assert_allclose(np.diff(x), nominal_pixel_size_m(2400))

    def test_grid_size_is_honoured(self):
        x, y = tile_coordinates("h09v04", 1200)
        assert x.size == y.size == 1200


class TestProjection:
    def test_matches_the_analytic_spherical_inverse(self):
        """Sinusoidal is analytic; agreement proves the CRS string is right."""
        x, y = tile_coordinates("h09v05", 2400)
        xs = x[::200]
        ys = y[::200]
        gx, gy = np.meshgrid(xs, ys)
        lon, lat = sinusoidal_to_lonlat(gx.ravel(), gy.ravel())

        lat_a = np.degrees(gy.ravel() / MODIS_SPHERE_RADIUS_M)
        lon_a = np.degrees(
            gx.ravel() / (MODIS_SPHERE_RADIUS_M * np.cos(np.radians(lat_a)))
        )
        np.testing.assert_allclose(lat, lat_a, atol=1e-9)
        np.testing.assert_allclose(lon, lon_a, atol=1e-9)

    def test_h09v05_lands_over_the_south_western_united_states(self):
        x, y = tile_coordinates("h09v05", 2400)
        lon, lat = sinusoidal_to_lonlat(np.array([x[1200]]), np.array([y[1200]]))
        assert -120 < lon[0] < -100
        assert 30 < lat[0] < 40

    def test_the_colorado_domain_transforms_back_into_the_expected_tiles(self):
        lon, lat = sinusoidal_to_lonlat(
            *_sinu(np.array([-106.0]), np.array([39.0]))
        )
        assert lon[0] == pytest.approx(-106.0, abs=1e-9)
        assert lat[0] == pytest.approx(39.0, abs=1e-9)


class TestTilesCovering:
    def test_the_domain_needs_the_three_archived_tiles(self):
        needed = tiles_covering(-109.0625, -104.0625, 36.75, 41.25)
        assert {"h09v04", "h09v05", "h10v04"} <= set(needed)

    def test_it_also_reveals_the_unarchived_corner_tile(self):
        """h10v05 clips a small south-east corner and is absent from the archive."""
        needed = tiles_covering(-109.0625, -104.0625, 36.75, 41.25)
        assert "h10v05" in needed

    def test_a_small_interior_box_needs_one_tile(self):
        assert tiles_covering(-107.0, -106.5, 38.0, 38.5) == ("h09v05",)


def _sinu(lon_deg, lat_deg):
    lat = np.radians(lat_deg)
    return (
        MODIS_SPHERE_RADIUS_M * np.radians(lon_deg) * np.cos(lat),
        MODIS_SPHERE_RADIUS_M * lat,
    )
