import math
import os

import matplotlib.pyplot as plt
import numpy as np
import pytest

from fsca_eval import aggregate, config, figures, metrics, regrid, significance, terrain


def _stats(sum_w=10.0, sum_w_error=2.0, sum_w_abs_error=3.0, sum_w_r=5.0):
    return metrics.SufficientStats(
        sum_w=sum_w, sum_w_error=sum_w_error, sum_w_abs_error=sum_w_abs_error, sum_w_r=sum_w_r,
        valid_pixels=10, expected_pixels=10, observed_pixels=10,
        n_cell_days=1, n_days=1, n_calendar_days=1,
    )


# --- figures.cells_to_grid ----------------------------------------------------


def test_cells_to_grid_places_values_at_correct_lat_lon_index():
    values = np.arange(config.N_CELLS, dtype=np.float64)
    grid = figures.cells_to_grid(values)
    assert grid.shape == (config.N_LAT_CELLS, config.N_LON_CELLS)
    for cell_id in (0, 5, 17, 71):
        lon_idx, lat_idx = divmod(cell_id, config.N_LAT_CELLS)
        assert grid[lat_idx, lon_idx] == cell_id


# --- figures.full_climatology_stats --------------------------------------------


def test_full_climatology_stats_sums_across_all_loaded_checkpoints():
    loaded = [
        aggregate.LoadedCheckpoint(water_year=2010, year=2009, month=10, cell_stats=[_stats() for _ in range(config.N_CELLS)]),
        aggregate.LoadedCheckpoint(water_year=2010, year=2009, month=11, cell_stats=[_stats() for _ in range(config.N_CELLS)]),
        aggregate.LoadedCheckpoint(water_year=2010, year=2009, month=12, cell_stats=[_stats() for _ in range(config.N_CELLS)]),
    ]
    combined = figures.full_climatology_stats(loaded)
    assert len(combined) == config.N_CELLS
    assert combined[0].sum_w == pytest.approx(30.0)
    assert combined[0].sum_w_error == pytest.approx(6.0)


# --- figures.build_monthly_domain_series ---------------------------------------


def test_build_monthly_domain_series_sorts_chronologically_and_combines_cells():
    # deliberately out of order to check the function sorts by (year, month)
    loaded = [
        aggregate.LoadedCheckpoint(water_year=2023, year=2022, month=11, cell_stats=[_stats(sum_w=10.0, sum_w_error=4.0, sum_w_abs_error=4.0) for _ in range(config.N_CELLS)]),
        aggregate.LoadedCheckpoint(water_year=2023, year=2022, month=10, cell_stats=[_stats(sum_w=10.0, sum_w_error=2.0, sum_w_abs_error=2.0) for _ in range(config.N_CELLS)]),
    ]
    data = figures.build_monthly_domain_series(loaded)
    assert data.labels == ["2022-10", "2022-11"]
    # domain bias = 100 * sum_w_error / sum_w, summed first across 72 identical cells
    assert data.bias_pp[0] == pytest.approx(20.0)
    assert data.bias_pp[1] == pytest.approx(40.0)
    assert data.mae_pp[0] == pytest.approx(20.0)
    assert data.mae_pp[1] == pytest.approx(40.0)


def test_build_monthly_domain_series_nan_for_zero_weight_month():
    loaded = [
        aggregate.LoadedCheckpoint(water_year=2023, year=2023, month=7, cell_stats=[metrics.SufficientStats() for _ in range(config.N_CELLS)]),
    ]
    data = figures.build_monthly_domain_series(loaded)
    assert math.isnan(data.bias_pp[0])
    assert math.isnan(data.mae_pp[0])


def test_render_monthly_domain_series_figure_writes_file(tmp_path):
    loaded = [
        aggregate.LoadedCheckpoint(water_year=2023, year=2022, month=10, cell_stats=[_stats() for _ in range(config.N_CELLS)]),
        aggregate.LoadedCheckpoint(water_year=2023, year=2022, month=11, cell_stats=[_stats() for _ in range(config.N_CELLS)]),
    ]
    data = figures.build_monthly_domain_series(loaded)
    out_path = str(tmp_path / "series.png")
    figures.render_monthly_domain_series_figure(data, out_path, title="test title")
    assert os.path.exists(out_path)
    assert os.path.getsize(out_path) > 0


# --- figures.build_monthly_spatial_grid_data / render --------------------------


def test_build_monthly_spatial_grid_data_sorts_and_masks_low_snow():
    loaded = [
        aggregate.LoadedCheckpoint(
            water_year=2023, year=2022, month=11,
            cell_stats=[_stats(sum_w=10.0, sum_w_error=4.0, sum_w_abs_error=4.0, sum_w_r=5.0) for _ in range(config.N_CELLS)],
        ),
        aggregate.LoadedCheckpoint(
            water_year=2023, year=2022, month=10,
            cell_stats=[_stats(sum_w=10.0, sum_w_error=2.0, sum_w_abs_error=2.0, sum_w_r=0.3) for _ in range(config.N_CELLS)],
        ),
    ]
    data = figures.build_monthly_spatial_grid_data(loaded)
    assert data.labels == ["2022-10", "2022-11"]
    assert len(data.bias_grids) == 2
    # 2022-10: fsca = 0.3/10 = 0.03 < COMPOSITE_FSCA_MASK_THRESHOLD -> fully masked
    assert np.all(np.isnan(data.bias_grids[0]))
    # 2022-11: fsca = 5/10 = 0.5, above threshold -> bias visible everywhere
    lon_idx0, lat_idx0 = divmod(0, config.N_LAT_CELLS)
    assert data.bias_grids[1][lat_idx0, lon_idx0] == pytest.approx(40.0)


def test_render_monthly_spatial_grid_figure_writes_file_for_12_months(tmp_path):
    loaded = [
        aggregate.LoadedCheckpoint(water_year=2023, year=2022 if m >= 10 else 2023, month=m, cell_stats=[_stats() for _ in range(config.N_CELLS)])
        for m in (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9)
    ]
    data = figures.build_monthly_spatial_grid_data(loaded)
    assert len(data.labels) == 12
    out_path = str(tmp_path / "grid.png")
    figures.render_monthly_spatial_grid_figure(data, out_path, title="test grid title")
    assert os.path.exists(out_path)
    assert os.path.getsize(out_path) > 0


def test_render_monthly_spatial_grid_figure_writes_file_with_dem_overlay(tmp_path):
    loaded = [
        aggregate.LoadedCheckpoint(water_year=2023, year=2022 if m >= 10 else 2023, month=m, cell_stats=[_stats() for _ in range(config.N_CELLS)])
        for m in (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9)
    ]
    data = figures.build_monthly_spatial_grid_data(loaded)

    dem = terrain.DemGrid(
        elevation_m=np.linspace(1000.0, 4000.0, 12).reshape(3, 4),
        lon_edges=np.linspace(config.DOMAIN_LON_EDGE_MIN, config.DOMAIN_LON_EDGE_MAX, 5),
        lat_edges=np.linspace(config.DOMAIN_LAT_EDGE_MIN, config.DOMAIN_LAT_EDGE_MAX, 4),
    )

    out_path = str(tmp_path / "grid_dem.png")
    figures.render_monthly_spatial_grid_figure(data, out_path, title="test grid title", dem=dem)
    assert os.path.exists(out_path)
    assert os.path.getsize(out_path) > 0


# --- figures.build_bias_mae_figure_data ----------------------------------------


def test_build_bias_mae_figure_data_masks_low_snow_and_zero_weight_cells():
    cell_stats = [metrics.SufficientStats() for _ in range(config.N_CELLS)]
    # cell 0: fsca = sum_w_r/sum_w = 5/10 = 0.5, above threshold -> kept
    cell_stats[0] = _stats(sum_w=10.0, sum_w_error=2.0, sum_w_abs_error=3.0, sum_w_r=5.0)
    # cell 1: fsca = 0.3/10 = 0.03, below COMPOSITE_FSCA_MASK_THRESHOLD (0.05) -> masked
    cell_stats[1] = _stats(sum_w=10.0, sum_w_error=1.0, sum_w_abs_error=1.0, sum_w_r=0.3)
    # cell 2: zero weight -> fsca is NaN -> masked
    cell_stats[2] = metrics.SufficientStats()

    data = figures.build_bias_mae_figure_data(cell_stats)

    lon_idx0, lat_idx0 = divmod(0, config.N_LAT_CELLS)
    lon_idx1, lat_idx1 = divmod(1, config.N_LAT_CELLS)
    lon_idx2, lat_idx2 = divmod(2, config.N_LAT_CELLS)

    assert data.bias_grid[lat_idx0, lon_idx0] == pytest.approx(20.0)  # 100*2/10
    assert math.isnan(data.bias_grid[lat_idx1, lon_idx1])
    assert math.isnan(data.bias_grid[lat_idx2, lon_idx2])

    assert not data.excluded_grid[lat_idx0, lon_idx0]
    assert data.excluded_grid[lat_idx1, lon_idx1]
    assert data.excluded_grid[lat_idx2, lon_idx2]

    # composite_fsca_grid is never masked -- it is the basis for the mask itself
    assert data.composite_fsca_grid[lat_idx1, lon_idx1] == pytest.approx(0.03)
    assert math.isnan(data.composite_fsca_grid[lat_idx2, lon_idx2])


def test_render_bias_mae_figure_writes_png(tmp_path):
    cell_stats = [_stats() for _ in range(config.N_CELLS)]
    data = figures.build_bias_mae_figure_data(cell_stats)

    out_path = tmp_path / "bias_mae.png"
    figures.render_bias_mae_figure(data, str(out_path))
    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_render_bias_mae_figure_writes_png_with_dem_overlay(tmp_path):
    cell_stats = [_stats() for _ in range(config.N_CELLS)]
    data = figures.build_bias_mae_figure_data(cell_stats)

    dem = terrain.DemGrid(
        elevation_m=np.linspace(1000.0, 4000.0, 12).reshape(3, 4),
        lon_edges=np.linspace(config.DOMAIN_LON_EDGE_MIN, config.DOMAIN_LON_EDGE_MAX, 5),
        lat_edges=np.linspace(config.DOMAIN_LAT_EDGE_MIN, config.DOMAIN_LAT_EDGE_MAX, 4),
    )

    out_path = tmp_path / "bias_mae_dem.png"
    figures.render_bias_mae_figure(data, str(out_path), dem=dem)
    assert out_path.exists()
    assert out_path.stat().st_size > 0


# --- figures.build_wet_dry_figure_data -----------------------------------------


def test_build_wet_dry_figure_data_masks_by_significance_threshold():
    wet_nmb = np.zeros(config.N_CELLS)
    dry_nmb = np.zeros(config.N_CELLS)
    wet_nmb[0], dry_nmb[0] = 15.0, -5.0
    wet_nmb[1], dry_nmb[1] = 25.0, 10.0

    wet_hatch = np.zeros(config.N_CELLS, dtype=bool)
    dry_hatch = np.zeros(config.N_CELLS, dtype=bool)

    sig = significance.WetDrySignificance(
        wet_composite_nmb=wet_nmb, dry_composite_nmb=dry_nmb,
        wet_pvalues=np.ones(config.N_CELLS), dry_pvalues=np.ones(config.N_CELLS),
        wet_hatch=wet_hatch, dry_hatch=dry_hatch,
    )

    wet_fsca = np.full(config.N_CELLS, np.nan)
    dry_fsca = np.full(config.N_CELLS, np.nan)
    wet_fsca[0], dry_fsca[0] = 0.20, np.nan  # cell 0: wet kept, dry excluded (NaN)
    wet_fsca[1], dry_fsca[1] = 0.05, 0.50  # cell 1: wet excluded (below 0.10), dry kept

    data = figures.build_wet_dry_figure_data(sig, wet_fsca, dry_fsca)

    lon_idx0, lat_idx0 = divmod(0, config.N_LAT_CELLS)
    lon_idx1, lat_idx1 = divmod(1, config.N_LAT_CELLS)

    assert not data.wet_excluded[0]
    assert data.dry_excluded[0]
    assert data.wet_excluded[1]
    assert not data.dry_excluded[1]

    assert data.wet_grid[lat_idx0, lon_idx0] == pytest.approx(15.0)
    assert math.isnan(data.dry_grid[lat_idx0, lon_idx0])
    assert math.isnan(data.wet_grid[lat_idx1, lon_idx1])
    assert data.dry_grid[lat_idx1, lon_idx1] == pytest.approx(10.0)


def test_add_hatches_only_marks_significant_non_excluded_cells():
    fig, ax = plt.subplots()
    try:
        hatch = np.zeros(config.N_CELLS, dtype=bool)
        excluded = np.zeros(config.N_CELLS, dtype=bool)
        hatch[3] = True
        hatch[4] = True
        excluded[4] = True  # significant but masked out -> must not get a patch

        lon_edges = regrid.cell_lon_edges()
        lat_edges = regrid.cell_lat_edges()
        figures._add_hatches(ax, hatch, excluded, lon_edges, lat_edges)

        assert len(ax.patches) == 1
        lon_idx, lat_idx = divmod(3, config.N_LAT_CELLS)
        assert ax.patches[0].get_x() == pytest.approx(lon_edges[lon_idx])
        assert ax.patches[0].get_y() == pytest.approx(lat_edges[lat_idx])
    finally:
        plt.close(fig)


def test_render_wet_dry_nmb_figure_writes_png(tmp_path):
    wet_nmb = np.full(config.N_CELLS, 5.0)
    dry_nmb = np.full(config.N_CELLS, -50.0)  # deliberately different magnitude
    wet_hatch = np.zeros(config.N_CELLS, dtype=bool)
    dry_hatch = np.ones(config.N_CELLS, dtype=bool)

    sig = significance.WetDrySignificance(
        wet_composite_nmb=wet_nmb, dry_composite_nmb=dry_nmb,
        wet_pvalues=np.ones(config.N_CELLS), dry_pvalues=np.zeros(config.N_CELLS),
        wet_hatch=wet_hatch, dry_hatch=dry_hatch,
    )
    data = figures.WetDryFigureData(
        wet_grid=figures.cells_to_grid(wet_nmb),
        dry_grid=figures.cells_to_grid(dry_nmb),
        wet_excluded=np.zeros(config.N_CELLS, dtype=bool),
        dry_excluded=np.zeros(config.N_CELLS, dtype=bool),
    )

    out_path = tmp_path / "wet_dry.png"
    figures.render_wet_dry_nmb_figure(data, sig, str(out_path))
    assert out_path.exists()
    assert out_path.stat().st_size > 0


# --- figures.build_monthly_wet_dry_*_data / render_monthly_wet_dry_grid_figure --


def _monthly_index(sum_w_r=5.0):
    """One CheckpointIndex entry per (water_year, month) for all wet+dry
    years across config.COMPOSITE_MONTHS, uniform cell stats.
    """
    index = {}
    for water_year in sorted(config.WET_WATER_YEARS | config.DRY_WATER_YEARS):
        err = 2.0 if water_year in config.WET_WATER_YEARS else 0.0
        for month in config.COMPOSITE_MONTHS:
            index[(water_year, month)] = [
                _stats(sum_w=10.0, sum_w_error=err, sum_w_abs_error=abs(err), sum_w_r=sum_w_r)
                for _ in range(config.N_CELLS)
            ]
    return index


def test_build_monthly_wet_dry_nmb_data_shape_and_hatch():
    index = _monthly_index()
    data = figures.build_monthly_wet_dry_nmb_data(index)

    assert data.months == list(config.COMPOSITE_MONTHS)
    assert len(data.wet_grids) == len(config.COMPOSITE_MONTHS)
    assert len(data.dry_grids) == len(config.COMPOSITE_MONTHS)
    assert data.wet_hatch is not None and data.dry_hatch is not None

    lon_idx0, lat_idx0 = divmod(0, config.N_LAT_CELLS)
    # wet: bias=2.0, sum_w_r=5.0, sum_w=10.0 -> nmb = 100*2/5 = 40
    assert data.wet_grids[0][lat_idx0, lon_idx0] == pytest.approx(40.0)
    # dry: bias=0.0 -> nmb = 0
    assert data.dry_grids[0][lat_idx0, lon_idx0] == pytest.approx(0.0)
    # wet years all have identical nonzero error -> zero variance around a nonzero
    # mean -> t-stat diverges -> p -> 0 -> hatched
    assert bool(data.wet_hatch[0][0])
    # dry years all have identical zero error -> mean is exactly 0 -> never hatched
    assert not bool(data.dry_hatch[0][0])


def test_build_monthly_wet_dry_nmb_data_masks_low_fsca():
    index = _monthly_index(sum_w_r=0.5)  # fsca = 0.5/10 = 0.05 < SIGNIFICANCE_FSCA_MASK_THRESHOLD (0.10)
    data = figures.build_monthly_wet_dry_nmb_data(index)
    assert np.all(data.wet_excluded[0])
    assert np.all(data.dry_excluded[0])
    assert np.all(np.isnan(data.wet_grids[0]))


def test_build_monthly_wet_dry_nmae_data_masks_at_composite_threshold_and_no_hatch():
    index = _monthly_index(sum_w_r=0.3)  # fsca = 0.03 < COMPOSITE_FSCA_MASK_THRESHOLD (0.05)
    data = figures.build_monthly_wet_dry_nmae_data(index)
    assert data.wet_hatch is None and data.dry_hatch is None
    assert np.all(data.wet_excluded[0])

    index_ok = _monthly_index(sum_w_r=5.0)
    data_ok = figures.build_monthly_wet_dry_nmae_data(index_ok)
    lon_idx0, lat_idx0 = divmod(0, config.N_LAT_CELLS)
    # wet: abs_error=2.0, sum_w_r=5.0 -> nmae = 100*2/5 = 40
    assert data_ok.wet_grids[0][lat_idx0, lon_idx0] == pytest.approx(40.0)


def test_build_monthly_wet_dry_fsca_data_is_never_masked():
    index = _monthly_index(sum_w_r=0.3)  # would be masked in the NMB/NMAE builders
    data = figures.build_monthly_wet_dry_fsca_data(index)
    assert data.wet_hatch is None and data.dry_hatch is None
    assert not np.any(data.wet_excluded[0])
    lon_idx0, lat_idx0 = divmod(0, config.N_LAT_CELLS)
    assert data.wet_grids[0][lat_idx0, lon_idx0] == pytest.approx(0.03)


def test_render_monthly_wet_dry_grid_figure_writes_file(tmp_path):
    index = _monthly_index()
    data = figures.build_monthly_wet_dry_nmb_data(index)
    out_path = tmp_path / "monthly_wet_dry_nmb.png"
    figures.render_monthly_wet_dry_grid_figure(
        data, str(out_path), title="test monthly nmb", cmap="RdBu_r", diverging=True,
        colorbar_label="NMB (%)",
    )
    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_render_monthly_wet_dry_grid_figure_writes_file_with_dem_overlay(tmp_path):
    index = _monthly_index()
    data = figures.build_monthly_wet_dry_fsca_data(index)

    dem = terrain.DemGrid(
        elevation_m=np.linspace(1000.0, 4000.0, 12).reshape(3, 4),
        lon_edges=np.linspace(config.DOMAIN_LON_EDGE_MIN, config.DOMAIN_LON_EDGE_MAX, 5),
        lat_edges=np.linspace(config.DOMAIN_LAT_EDGE_MIN, config.DOMAIN_LAT_EDGE_MAX, 4),
    )

    out_path = tmp_path / "monthly_wet_dry_fsca_dem.png"
    figures.render_monthly_wet_dry_grid_figure(
        data, str(out_path), title="test monthly fsca", cmap="YlOrRd", diverging=False,
        colorbar_label="Composite fSCA", dem=dem,
    )
    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_shared_norm_covers_both_wet_and_dry_ranges():
    wet_grid = np.full((config.N_LAT_CELLS, config.N_LON_CELLS), 5.0)
    dry_grid = np.full((config.N_LAT_CELLS, config.N_LON_CELLS), -50.0)
    norm = terrain.shared_norm(wet_grid, dry_grid, diverging=True)
    assert norm.vmax >= 50.0
    assert norm.vmin <= -50.0
    assert norm.vcenter == 0.0


# --- terrain.py -----------------------------------------------------------------


def test_hillshade_flat_surface_returns_uniform_expected_value():
    elevation = np.zeros((5, 5))
    shaded = terrain.hillshade(elevation, cellsize_x_m=100.0, cellsize_y_m=100.0)
    expected = math.sin(math.radians(45.0))
    assert shaded.shape == (5, 5)
    assert np.allclose(shaded, expected)
    assert np.all(shaded >= 0.0) and np.all(shaded <= 1.0)


def test_contour_levels_are_documented_values():
    assert terrain.contour_levels() == (2000, 3000)


def test_smooth_for_contours_reduces_fine_scale_noise():
    rng = np.random.default_rng(0)
    checkerboard = np.indices((60, 60)).sum(axis=0) % 2 * 2000.0 + 1000.0  # alternating 1000/3000
    noisy = checkerboard + rng.normal(scale=1.0, size=checkerboard.shape)
    smoothed = terrain.smooth_for_contours(noisy, sigma_px=8.0)
    assert np.nanstd(smoothed) < np.nanstd(noisy)


def test_smooth_for_contours_keeps_nan_where_input_is_all_nan_nearby():
    elevation = np.full((40, 40), 2500.0)
    elevation[:10, :10] = np.nan  # a nodata corner far from any valid pixel
    smoothed = terrain.smooth_for_contours(elevation, sigma_px=2.0)
    assert np.isnan(smoothed[0, 0])
    assert np.isfinite(smoothed[30, 30])


def test_crop_to_data_extent_trims_all_invalid_borders():
    valid_mask = np.zeros((5, 5), dtype=bool)
    valid_mask[1:4, 1:4] = True
    row_slice, col_slice = terrain.crop_to_data_extent(np.zeros((5, 5)), valid_mask)
    assert row_slice == slice(1, 4)
    assert col_slice == slice(1, 4)


def test_crop_to_data_extent_all_invalid_returns_empty_slice():
    valid_mask = np.zeros((3, 3), dtype=bool)
    row_slice, col_slice = terrain.crop_to_data_extent(np.zeros((3, 3)), valid_mask)
    assert row_slice == slice(0, 0)
    assert col_slice == slice(0, 0)


def test_diverging_norm_centers_at_zero_and_trims_outliers():
    values = np.concatenate([np.linspace(-1.0, 1.0, 99), [1000.0]])
    norm = terrain.diverging_norm(values, trim_percentile=2.0)
    assert norm.vcenter == 0.0
    assert norm.vmax < 10.0  # the single huge outlier must not dominate the scale
    assert norm.vmin == -norm.vmax


def test_diverging_norm_with_no_finite_values_returns_default():
    norm = terrain.diverging_norm(np.array([np.nan, np.nan]))
    assert (norm.vmin, norm.vcenter, norm.vmax) == (-1.0, 0.0, 1.0)


def test_sequential_norm_basic_range():
    norm = terrain.sequential_norm(np.array([0.0, 5.0, 10.0]))
    assert norm.vmin == 0.0
    assert norm.vmax == pytest.approx(10.0)


def test_sequential_norm_with_no_finite_values_returns_default():
    norm = terrain.sequential_norm(np.array([np.nan, np.nan]))
    assert norm.vmin == 0.0
    assert norm.vmax == 1.0


def test_shared_norm_matches_diverging_norm_of_concatenation():
    a = np.array([-2.0, 1.0])
    b = np.array([3.0, -4.0])
    shared = terrain.shared_norm(a, b, diverging=True)
    direct = terrain.diverging_norm(np.concatenate([a, b]))
    assert shared.vmin == direct.vmin
    assert shared.vmax == direct.vmax


class _FakeDemTransport:
    def __init__(self):
        self.calls = []

    def fetch(self, lon_min, lat_min, lon_max, lat_max, width_px, height_px):
        self.calls.append((lon_min, lat_min, lon_max, lat_max, width_px, height_px))
        elevation = np.zeros((height_px, width_px))
        lon_edges = np.linspace(lon_min, lon_max, width_px + 1)
        lat_edges = np.linspace(lat_min, lat_max, height_px + 1)
        return terrain.DemGrid(elevation_m=elevation, lon_edges=lon_edges, lat_edges=lat_edges)


def test_fetch_dem_passes_bbox_and_size_through_to_transport():
    transport = _FakeDemTransport()
    dem = terrain.fetch_dem(-109.0, 36.75, -104.0, 41.25, transport, width_px=40, height_px=30)
    assert transport.calls == [(-109.0, 36.75, -104.0, 41.25, 40, 30)]
    assert dem.elevation_m.shape == (30, 40)
