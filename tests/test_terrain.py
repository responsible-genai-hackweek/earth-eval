"""Tests backed by a real (checked-in, coarse) DEM raster, complementing the
synthetic DemGrid fixtures already covering terrain.py's pure functions in
test_figures.py.

tests/fixtures/domain_dem_3dep.tif is a real USGS 3DEP DEM over the
configured comparison domain, exported via
scripts/earth_engine_dem_export.js at the same 800x600 display grid
terrain.fetch_dem() defaults to -- small enough to check in (~1.6 MB),
unlike a native-resolution export of this domain (several GB).
"""

import os

import numpy as np
import pytest
import rasterio

from fsca_eval import config, figures, terrain

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "domain_dem_3dep.tif")


class FixtureDemTransport:
    """Decodes the checked-in fixture the same way RealDemTransport decodes
    a live response (rasterio read + nodata->NaN), minus the network call.
    """

    def fetch(self, lon_min, lat_min, lon_max, lat_max, width_px, height_px):
        with rasterio.open(FIXTURE_PATH) as dataset:
            elevation = dataset.read(1).astype(np.float64)
            if dataset.nodata is not None:
                elevation[elevation == dataset.nodata] = np.nan

        lon_edges = np.linspace(lon_min, lon_max, width_px + 1)
        lat_edges = np.linspace(lat_min, lat_max, height_px + 1)
        return terrain.DemGrid(elevation_m=elevation, lon_edges=lon_edges, lat_edges=lat_edges)


def _fetch_fixture_dem() -> terrain.DemGrid:
    return terrain.fetch_dem(
        config.DOMAIN_LON_EDGE_MIN, config.DOMAIN_LAT_EDGE_MIN,
        config.DOMAIN_LON_EDGE_MAX, config.DOMAIN_LAT_EDGE_MAX,
        FixtureDemTransport(), width_px=800, height_px=600,
    )


def test_fixture_dem_matches_configured_domain_grid():
    dem = _fetch_fixture_dem()
    assert dem.elevation_m.shape == (600, 800)
    assert dem.lon_edges[0] == pytest.approx(config.DOMAIN_LON_EDGE_MIN)
    assert dem.lon_edges[-1] == pytest.approx(config.DOMAIN_LON_EDGE_MAX)
    assert dem.lat_edges[0] == pytest.approx(config.DOMAIN_LAT_EDGE_MIN)
    assert dem.lat_edges[-1] == pytest.approx(config.DOMAIN_LAT_EDGE_MAX)


def test_fixture_dem_elevation_values_are_plausible_for_domain():
    dem = _fetch_fixture_dem()
    # No fill sentinels leaking through, and a plausible range for the
    # southern Rockies (this domain spans roughly the San Juans/Sawatch).
    assert np.all(np.isfinite(dem.elevation_m))
    assert 1000.0 < np.nanmin(dem.elevation_m) < 2500.0
    assert 3500.0 < np.nanmax(dem.elevation_m) < 5000.0


def test_hillshade_on_real_fixture_is_bounded_and_varies():
    dem = _fetch_fixture_dem()
    shaded, extent = figures._domain_hillshade_extent(dem)
    assert shaded.shape == dem.elevation_m.shape
    assert np.nanmin(shaded) >= 0.0 and np.nanmax(shaded) <= 1.0
    assert np.nanstd(shaded) > 0.0  # real terrain -- not a flat plane
    assert extent == [dem.lon_edges[0], dem.lon_edges[-1], dem.lat_edges[0], dem.lat_edges[-1]]


def test_crop_to_data_extent_on_real_fixture_keeps_full_grid():
    dem = _fetch_fixture_dem()
    valid_mask = np.isfinite(dem.elevation_m)
    row_slice, col_slice = terrain.crop_to_data_extent(dem.elevation_m, valid_mask)
    assert (row_slice, col_slice) == (slice(0, 600), slice(0, 800))


def test_local_file_dem_transport_reads_real_fixture_like_fixture_transport():
    dem = terrain.fetch_dem(
        config.DOMAIN_LON_EDGE_MIN, config.DOMAIN_LAT_EDGE_MIN,
        config.DOMAIN_LON_EDGE_MAX, config.DOMAIN_LAT_EDGE_MAX,
        terrain.LocalFileDemTransport(FIXTURE_PATH), width_px=800, height_px=600,
    )
    assert dem.elevation_m.shape == (600, 800)
    assert dem.lon_edges[0] == pytest.approx(config.DOMAIN_LON_EDGE_MIN)
    assert dem.lon_edges[-1] == pytest.approx(config.DOMAIN_LON_EDGE_MAX)
    assert np.all(np.isfinite(dem.elevation_m))
    assert 1000.0 < np.nanmin(dem.elevation_m) < 2500.0
    assert 3500.0 < np.nanmax(dem.elevation_m) < 5000.0
