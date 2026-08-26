from pathlib import Path

import numpy as np

from merra_modis_comparison.composite_plotting import (
    COMPOSITE_GROUPS,
    COMPOSITE_MONTHS,
)
from merra_modis_comparison.config import RunConfig
from merra_modis_comparison.metrics import StatsBlock, update_stats
from merra_modis_comparison.modis_fsca_stats import (
    ModisStatsBlock,
    update_modis_stats,
)
from merra_modis_comparison.spatial_plotting import load_elevation_grid
from merra_modis_comparison.wet_dry_bias_significance import (
    WetDryBiasResult,
    calculate_group_month_result,
    write_wet_dry_csv,
    write_wet_dry_plot,
)


def _yearly_pairs(config: RunConfig):
    result = []
    errors = (-0.10, -0.08, -0.12, -0.10)
    for water_year, error in zip((2011, 2017, 2019, 2023), errors, strict=True):
        shape = config.target_grid.shape
        modis_fsca = np.full(shape, 0.5)
        modis_fsca.ravel()[0] = 0.05
        valid = np.full(shape, 10)
        expected = np.full(shape, 10)
        observed = np.full(shape, 8)
        comparison = StatsBlock.empty(config.target_grid.size)
        update_stats(
            comparison,
            modis_fsca + error,
            modis_fsca,
            valid,
            expected,
            observed,
        )
        modis = ModisStatsBlock.empty(config.target_grid.size)
        update_modis_stats(modis, modis_fsca, valid, expected, observed)
        result.append((water_year, comparison, modis))
    return result


def test_group_month_normalized_bias_and_modis_mask():
    config = RunConfig()
    result = calculate_group_month_result(
        "Wet",
        (2011, 2017, 2019, 2023),
        1,
        "January",
        _yearly_pairs(config),
    )
    assert result.masked_low_modis_fsca[0]
    assert np.isnan(result.p_value[0])
    assert np.allclose(result.normalized_mean_bias_pct[1:], -20.0)
    assert np.all(result.n_years == 4)
    assert np.all(result.degrees_of_freedom == 3)
    assert np.all(result.p_value[1:] < 0.05)


def test_wet_dry_plot_and_csv(tmp_path):
    config = RunConfig()
    base = calculate_group_month_result(
        "Wet",
        (2011, 2017, 2019, 2023),
        1,
        "January",
        _yearly_pairs(config),
    )
    results: dict[str, list[WetDryBiasResult]] = {"Wet": [], "Dry": []}
    for group, water_years in COMPOSITE_GROUPS:
        for month, label in COMPOSITE_MONTHS:
            results[group].append(
                WetDryBiasResult(
                    group=group,
                    water_years=water_years,
                    month=month,
                    label=label,
                    normalized_mean_bias_pct=base.normalized_mean_bias_pct,
                    mean_annual_nmb_pct=base.mean_annual_nmb_pct,
                    modis_fsca_pct=base.modis_fsca_pct,
                    masked_low_modis_fsca=base.masked_low_modis_fsca,
                    t_statistic=base.t_statistic,
                    p_value=base.p_value,
                    n_years=base.n_years,
                    degrees_of_freedom=base.degrees_of_freedom,
                )
            )
    elevation = load_elevation_grid(Path("data/usgs_3dep_coarse_dem.tif"), config)
    plot_output = tmp_path / "wet_dry_ttest.png"
    csv_output = tmp_path / "wet_dry_ttest.csv"
    write_wet_dry_plot(results, config, plot_output, elevation)
    write_wet_dry_csv(results, config, csv_output)
    assert plot_output.stat().st_size > 10_000
    assert len(csv_output.read_text().splitlines()) == 1 + 14 * 72
    header = csv_output.read_text().splitlines()[0]
    assert "two_sided_p_lt_0_05" in header
    assert "ventura" not in header
