from pathlib import Path

import numpy as np

from merra_modis_comparison.bias_significance import (
    ANALYSIS_MONTHS,
    benjamini_hochberg,
    calculate_monthly_ttests,
    two_sided_ttest,
    ventura_modified_fdr,
    write_ttest_csv,
    write_ttest_plot,
)
from merra_modis_comparison.config import RunConfig
from merra_modis_comparison.spatial_plotting import load_elevation_grid


def test_two_sided_ttest_uses_years_as_replicates():
    yearly_biases = np.array(
        [
            [-3.0, 3.0, np.nan],
            [-2.0, 4.0, -1.0],
            [-4.0, 2.0, -2.0],
            [-3.0, 5.0, -3.0],
        ]
    )
    result = two_sided_ttest(yearly_biases)
    assert np.array_equal(result.n_years, (4, 4, 3))
    assert np.array_equal(result.degrees_of_freedom, (3, 3, 2))
    assert result.mean_bias_pp[0] < 0
    assert result.p_value[0] < 0.05
    assert result.mean_bias_pp[1] > 0
    assert result.p_value[1] < 0.05


def test_benjamini_hochberg_adjustment():
    p_values = np.array([0.001, 0.01, 0.04, 0.5, np.nan])
    adjusted = benjamini_hochberg(p_values)
    assert np.allclose(adjusted[:4], (0.004, 0.02, 0.053333333333, 0.5))
    assert np.isnan(adjusted[4])


def test_ventura_modified_fdr_matches_equations_six_and_eight():
    p_values = np.array([0.001, 0.01, 0.04, 0.2, 0.5, 0.9, np.nan])
    result = ventura_modified_fdr(p_values)

    valid = p_values[np.isfinite(p_values)]
    x_values = 0.8 + 0.2 * np.arange(20) / 20
    empirical_cdf = np.array([(valid <= x).mean() for x in x_values])
    expected_alternative_fraction = np.mean(
        np.maximum(0.0, (empirical_cdf - x_values) / (1.0 - x_values))
    )
    expected_bh = benjamini_hochberg(p_values)

    assert np.isclose(
        result.estimated_alternative_fraction,
        expected_alternative_fraction,
    )
    assert np.isclose(
        result.effective_bh_rate,
        min(1.0, 0.05 / (1.0 - expected_alternative_fraction)),
    )
    assert np.allclose(
        result.adjusted_q_value[:-1],
        (1.0 - expected_alternative_fraction) * expected_bh[:-1],
    )
    assert np.isnan(result.adjusted_q_value[-1])
    assert np.array_equal(
        result.significant[:-1], result.adjusted_q_value[:-1] <= 0.05
    )


def test_ttest_plot_and_csv(tmp_path):
    config = RunConfig()
    n_years = len(config.water_years)
    n_cells = config.target_grid.size
    base = np.linspace(-4.0, 2.0, n_cells)
    yearly_biases = {
        month: np.vstack(
            [base + 0.15 * (year_index - n_years / 2) for year_index in range(n_years)]
        )
        for month, _ in ANALYSIS_MONTHS
    }
    results = calculate_monthly_ttests(yearly_biases)
    elevation = load_elevation_grid(Path("data/usgs_3dep_coarse_dem.tif"), config)
    plot_output = tmp_path / "ttest.png"
    csv_output = tmp_path / "ttest.csv"
    write_ttest_plot(results, config, plot_output, elevation)
    write_ttest_csv(results, config, elevation, csv_output)
    assert plot_output.stat().st_size > 10_000
    assert len(csv_output.read_text().splitlines()) == 1 + 7 * n_cells
