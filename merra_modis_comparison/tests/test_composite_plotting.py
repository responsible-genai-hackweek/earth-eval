from pathlib import Path

import numpy as np

from merra_modis_comparison.composite_plotting import (
    COMPOSITE_MONTHS,
    calendar_period_for_water_year,
    normalized_error_grid,
    write_composite_elevation_plot,
    write_composite_spatial_plot,
)
from merra_modis_comparison.config import RunConfig
from merra_modis_comparison.metrics import StatsBlock, update_stats
from merra_modis_comparison.modis_fsca_stats import (
    ModisStatsBlock,
    update_modis_stats,
)
from merra_modis_comparison.spatial_plotting import load_elevation_grid


def _stats(config: RunConfig, error: float) -> StatsBlock:
    stats = StatsBlock.empty(config.target_grid.size)
    shape = config.target_grid.shape
    update_stats(
        stats,
        np.full(shape, 0.5 + error),
        np.full(shape, 0.5),
        np.full(shape, 9),
        np.full(shape, 10),
        np.full(shape, 7),
    )
    return stats


def _composites(config: RunConfig) -> dict[str, list[tuple[str, StatsBlock]]]:
    labels = [label for _, label in COMPOSITE_MONTHS]
    return {
        "Wet": [
            (label, _stats(config, error))
            for label, error in zip(
                labels,
                (-0.12, -0.10, -0.08, -0.06, -0.04, -0.02, 0.01),
                strict=True,
            )
        ],
        "Dry": [
            (label, _stats(config, error))
            for label, error in zip(
                labels,
                (-0.06, -0.05, -0.04, -0.03, -0.02, -0.01, 0.02),
                strict=True,
            )
        ],
    }


def _modis_composites(
    config: RunConfig,
) -> dict[str, list[tuple[str, ModisStatsBlock]]]:
    labels = [label for _, label in COMPOSITE_MONTHS]
    result: dict[str, list[tuple[str, ModisStatsBlock]]] = {
        "Wet": [],
        "Dry": [],
    }
    for group, base_fsca in (("Wet", 0.55), ("Dry", 0.35)):
        for index, label in enumerate(labels):
            stats = ModisStatsBlock.empty(config.target_grid.size)
            shape = config.target_grid.shape
            update_modis_stats(
                stats,
                np.full(shape, min(base_fsca + index * 0.02, 1.0)),
                np.full(shape, 9),
                np.full(shape, 10),
                np.full(shape, 7),
            )
            result[group].append((label, stats))
    return result


def test_water_year_month_mapping():
    assert calendar_period_for_water_year(2011, 11) == (2010, 11)
    assert calendar_period_for_water_year(2011, 12) == (2010, 12)
    assert calendar_period_for_water_year(2011, 1) == (2011, 1)


def test_normalized_metrics_and_five_percent_mask():
    config = RunConfig()
    comparison = _stats(config, -0.1)
    shape = config.target_grid.shape
    modis = ModisStatsBlock.empty(config.target_grid.size)
    update_modis_stats(
        modis,
        np.full(shape, 0.5),
        np.full(shape, 9),
        np.full(shape, 10),
        np.full(shape, 7),
    )
    assert np.allclose(
        normalized_error_grid(comparison, modis, "nmb_pct", shape), -20
    )
    assert np.allclose(
        normalized_error_grid(comparison, modis, "nmae_pct", shape), 20
    )

    low_snow = ModisStatsBlock.empty(config.target_grid.size)
    update_modis_stats(
        low_snow,
        np.full(shape, 0.04),
        np.full(shape, 9),
        np.full(shape, 10),
        np.full(shape, 7),
    )
    assert np.isnan(
        normalized_error_grid(comparison, low_snow, "nmb_pct", shape)
    ).all()


def test_composite_plots(tmp_path):
    config = RunConfig()
    composites = _composites(config)
    modis_composites = _modis_composites(config)
    elevation = load_elevation_grid(
        Path("data/usgs_3dep_coarse_dem.tif"), config
    )
    spatial_output = tmp_path / "composite_spatial.png"
    elevation_output = tmp_path / "composite_elevation.png"
    write_composite_spatial_plot(
        composites, modis_composites, config, spatial_output, elevation
    )
    write_composite_elevation_plot(
        composites, modis_composites, config, elevation_output, elevation
    )
    assert spatial_output.stat().st_size > 10_000
    assert elevation_output.stat().st_size > 10_000
    assert not list(tmp_path.glob("*.tmp"))
