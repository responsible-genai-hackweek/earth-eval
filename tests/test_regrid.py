import numpy as np
import pytest

from fsca_eval import config, regrid


def test_cell_id_from_indices_and_back_roundtrip():
    for lon_idx in range(config.N_LON_CELLS):
        for lat_idx in range(config.N_LAT_CELLS):
            cell_id = int(regrid.cell_id_from_indices(lon_idx, lat_idx))
            lon_center, lat_center = regrid.cell_id_to_center(cell_id)
            assert lon_center == pytest.approx(config.CELL_LON_CENTERS[lon_idx])
            assert lat_center == pytest.approx(config.CELL_LAT_CENTERS[lat_idx])


def test_cell_lon_lat_edges_span_domain():
    lon_edges = regrid.cell_lon_edges()
    lat_edges = regrid.cell_lat_edges()
    assert lon_edges[0] == pytest.approx(config.DOMAIN_LON_EDGE_MIN)
    assert lon_edges[-1] == pytest.approx(config.DOMAIN_LON_EDGE_MAX)
    assert lat_edges[0] == pytest.approx(config.DOMAIN_LAT_EDGE_MIN)
    assert lat_edges[-1] == pytest.approx(config.DOMAIN_LAT_EDGE_MAX)
    assert len(lon_edges) == config.N_LON_CELLS + 1
    assert len(lat_edges) == config.N_LAT_CELLS + 1


def _pixel_grid_for_cell(cell_id, n_per_side=10, jitter=0.2):
    """n_per_side^2 pixel centers scattered within one cell's interior."""
    lon_idx, lat_idx = divmod(cell_id, config.N_LAT_CELLS)
    lon_center, lat_center = config.CELL_LON_CENTERS[lon_idx], config.CELL_LAT_CENTERS[lat_idx]
    rng = np.random.default_rng(cell_id)
    lon = lon_center + rng.uniform(-jitter, jitter, n_per_side**2) * config.LON_SPACING / 2
    lat = lat_center + rng.uniform(-jitter, jitter, n_per_side**2) * config.LAT_SPACING / 2
    return lon, lat


def test_build_mapping_assigns_interior_pixels_to_correct_cell():
    lon, lat = _pixel_grid_for_cell(cell_id=5, n_per_side=10)
    mapping = regrid.build_mapping(lon, lat)
    assert np.all(mapping.pixel_cell_id == 5)
    assert mapping.expected_pixels_per_cell[5] == 100
    assert mapping.expected_pixels_per_cell.sum() == 100


def test_build_mapping_excludes_out_of_domain_pixels():
    lon = np.array([config.DOMAIN_LON_EDGE_MIN - 1.0, config.DOMAIN_LON_EDGE_MAX + 1.0])
    lat = np.array([config.DOMAIN_LAT_EDGE_MIN - 1.0, config.DOMAIN_LAT_EDGE_MAX + 1.0])
    mapping = regrid.build_mapping(lon, lat)
    assert np.all(mapping.pixel_cell_id == -1)
    assert mapping.expected_pixels_per_cell.sum() == 0


def test_apply_mapping_support_fraction_and_reference_value():
    lon, lat = _pixel_grid_for_cell(cell_id=10, n_per_side=10)  # 100 expected pixels
    mapping = regrid.build_mapping(lon, lat)

    # 85 of 100 pixels report valid snow_fraction=40%, the rest are fill (>100)
    snow_fraction = np.full(100, 200.0)
    snow_fraction[:85] = 40.0
    days_without_observation = np.zeros(100)
    days_without_observation[:40] = 1  # 40 interpolated, 45 directly observed among the 85 valid

    agg = regrid.apply_mapping(mapping, snow_fraction, days_without_observation)

    assert agg.expected_pixels[10] == 100
    assert agg.valid_pixels[10] == 85
    assert agg.observed_pixels[10] == 45
    assert agg.support_fraction[10] == pytest.approx(0.85)
    assert agg.reference_fraction[10] == pytest.approx(0.40)

    other_cells = [c for c in range(config.N_CELLS) if c != 10]
    assert np.all(agg.valid_pixels[other_cells] == 0)
    assert np.all(np.isnan(agg.reference_fraction[other_cells]))
    assert np.all(agg.support_fraction[other_cells] == 0.0)


def test_apply_mapping_below_support_threshold_still_reports_reference():
    """apply_mapping itself does not apply the 80% threshold -- that gating
    happens in metrics.cell_day_contribution. apply_mapping always reports
    the true support_fraction and reference_fraction from whatever pixels
    are valid.
    """
    lon, lat = _pixel_grid_for_cell(cell_id=3, n_per_side=10)
    mapping = regrid.build_mapping(lon, lat)

    snow_fraction = np.full(100, 200.0)
    snow_fraction[:50] = 60.0  # only 50% support
    days_without_observation = np.zeros(100)

    agg = regrid.apply_mapping(mapping, snow_fraction, days_without_observation)
    assert agg.support_fraction[3] == pytest.approx(0.50)
    assert agg.reference_fraction[3] == pytest.approx(0.60)


def test_apply_mapping_shape_mismatch_raises():
    lon, lat = _pixel_grid_for_cell(cell_id=0, n_per_side=5)
    mapping = regrid.build_mapping(lon, lat)
    with pytest.raises(ValueError):
        regrid.apply_mapping(mapping, np.zeros(10), np.zeros(10))


def test_transform_sinusoidal_to_lonlat_roundtrip_center():
    # (0, 0) in MODIS sinusoidal projection is (0 deg lon, 0 deg lat)
    lon, lat = regrid.transform_sinusoidal_to_lonlat(np.array([0.0]), np.array([0.0]))
    assert lon[0] == pytest.approx(0.0, abs=1e-6)
    assert lat[0] == pytest.approx(0.0, abs=1e-6)
