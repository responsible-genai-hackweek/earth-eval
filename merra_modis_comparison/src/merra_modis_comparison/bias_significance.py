from __future__ import annotations

import argparse
import csv
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap, TwoSlopeNorm
from matplotlib.patches import Rectangle
from scipy.stats import t as student_t

from .checkpoints import checkpoint_path, load_month_checkpoint
from .config import RunConfig
from .metrics import StatsBlock
from .spatial_plotting import (
    ELEVATION_CONTOURS_M,
    METRIC_LAYER_ALPHA,
    ElevationGrid,
    _save_figure,
    _terrain_extent,
    cell_mean_elevation_grid,
    hillshade_grid,
    load_elevation_grid,
)


ANALYSIS_MONTHS = (
    (11, "November"),
    (12, "December"),
    (1, "January"),
    (2, "February"),
    (3, "March"),
    (4, "April"),
    (5, "May"),
)
TEST_ALPHA = 0.05


@dataclass(frozen=True)
class MonthlyTTest:
    month: int
    label: str
    mean_bias_pp: np.ndarray
    t_statistic: np.ndarray
    p_value: np.ndarray
    bh_q_value: np.ndarray
    n_years: np.ndarray
    degrees_of_freedom: np.ndarray


@dataclass(frozen=True)
class VenturaFDR:
    adjusted_q_value: np.ndarray
    significant: np.ndarray
    estimated_alternative_fraction: float
    effective_bh_rate: float


def calendar_period_for_water_year(water_year: int, month: int) -> tuple[int, int]:
    if month not in {11, 12, 1, 2, 3, 4, 5}:
        raise ValueError("analysis month must be between November and May")
    return (water_year - 1 if month >= 10 else water_year, month)


def _cell_biases(stats: StatsBlock) -> np.ndarray:
    weights = stats.sum_w[: stats.n_cells]
    return np.divide(
        100.0 * stats.sum_w_error[: stats.n_cells],
        weights,
        out=np.full(stats.n_cells, np.nan, dtype=np.float64),
        where=weights > 0,
    )


def load_water_year_biases(
    checkpoint_directory: Path,
    config: RunConfig,
    workers: int = 16,
) -> dict[int, np.ndarray]:
    """Load monthly cell bias for every water year, concurrently.

    Returned arrays have shape ``(n_water_years, n_cells)``. Each row is one
    independent water-year replicate in the subsequent t-test.
    """

    tasks = [
        (month_index, water_year, *calendar_period_for_water_year(water_year, month))
        for month_index, (month, _) in enumerate(ANALYSIS_MONTHS)
        for water_year in config.water_years
    ]

    def load_one(task: tuple[int, int, int, int]) -> tuple[int, int, np.ndarray]:
        month_index, water_year, year, calendar_month = task
        path = checkpoint_path(checkpoint_directory, year, calendar_month)
        if not path.exists():
            raise FileNotFoundError(
                f"missing validated checkpoint {path} for WY{water_year}"
            )
        stats = load_month_checkpoint(path, year, calendar_month, config)
        return month_index, water_year, _cell_biases(stats)

    loaded = {
        month: np.full(
            (len(config.water_years), config.target_grid.size),
            np.nan,
            dtype=np.float64,
        )
        for month, _ in ANALYSIS_MONTHS
    }
    year_to_row = {year: row for row, year in enumerate(config.water_years)}
    with ThreadPoolExecutor(max_workers=min(workers, len(tasks))) as executor:
        for month_index, water_year, biases in executor.map(load_one, tasks):
            month = ANALYSIS_MONTHS[month_index][0]
            loaded[month][year_to_row[water_year], :] = biases
    return loaded


def benjamini_hochberg(p_values: np.ndarray) -> np.ndarray:
    """Return Benjamini-Hochberg adjusted p-values, preserving NaNs."""

    values = np.asarray(p_values, dtype=np.float64)
    adjusted = np.full(values.shape, np.nan, dtype=np.float64)
    valid_slots = np.flatnonzero(np.isfinite(values))
    if valid_slots.size == 0:
        return adjusted
    order = np.argsort(values[valid_slots])
    sorted_slots = valid_slots[order]
    sorted_p = values[sorted_slots]
    ranks = np.arange(1, sorted_p.size + 1, dtype=np.float64)
    sorted_q = sorted_p * sorted_p.size / ranks
    sorted_q = np.minimum.accumulate(sorted_q[::-1])[::-1]
    adjusted[sorted_slots] = np.clip(sorted_q, 0.0, 1.0)
    return adjusted


def ventura_modified_fdr(
    p_values: np.ndarray,
    target_fdr: float = 0.05,
    x0: float = 0.8,
    n_grid_points: int = 20,
) -> VenturaFDR:
    """Apply Ventura et al. (2004) modified FDR-Indep.

    The alternative-hypothesis fraction is estimated from their equation (8),
    using the empirical p-value CDF at 20 points from 0.8 through 0.99. The
    ordinary Benjamini-Hochberg rate is then inflated by ``1 / (1 - a_hat)``
    as in their equation (6), while the target FDR remains ``target_fdr``.
    """

    if not 0 < target_fdr < 1:
        raise ValueError("target FDR must lie between zero and one")
    if not 0 <= x0 < 1:
        raise ValueError("x0 must lie in [0, 1)")
    if n_grid_points < 1:
        raise ValueError("at least one p-value CDF grid point is required")
    values = np.asarray(p_values, dtype=np.float64)
    valid = np.isfinite(values) & (values >= 0) & (values <= 1)
    valid_values = values[valid]
    adjusted = np.full(values.shape, np.nan, dtype=np.float64)
    significant = np.zeros(values.shape, dtype=bool)
    if valid_values.size == 0:
        return VenturaFDR(adjusted, significant, 0.0, target_fdr)

    x_values = x0 + (1.0 - x0) * (
        np.arange(n_grid_points, dtype=np.float64) / n_grid_points
    )
    empirical_cdf = np.asarray(
        [np.mean(valid_values <= x) for x in x_values], dtype=np.float64
    )
    contributions = np.maximum(
        0.0,
        np.divide(
            empirical_cdf - x_values,
            1.0 - x_values,
        ),
    )
    alternative_fraction = float(np.clip(np.mean(contributions), 0.0, 1.0))
    null_fraction = 1.0 - alternative_fraction
    effective_bh_rate = (
        1.0
        if null_fraction <= 0
        else float(min(1.0, target_fdr / null_fraction))
    )
    bh_adjusted = benjamini_hochberg(values)
    adjusted[valid] = np.clip(null_fraction * bh_adjusted[valid], 0.0, 1.0)
    significant[valid] = adjusted[valid] <= target_fdr
    return VenturaFDR(
        adjusted_q_value=adjusted,
        significant=significant,
        estimated_alternative_fraction=alternative_fraction,
        effective_bh_rate=effective_bh_rate,
    )


def two_sided_ttest(yearly_biases: np.ndarray) -> MonthlyTTest:
    """Test H0: mean cell bias = 0 against H1: mean cell bias != 0."""

    values = np.asarray(yearly_biases, dtype=np.float64)
    if values.ndim != 2:
        raise ValueError("yearly biases must be a two-dimensional array")
    finite = np.isfinite(values)
    n_years = finite.sum(axis=0).astype(np.int64)
    sums = np.where(finite, values, 0.0).sum(axis=0)
    means = np.divide(
        sums,
        n_years,
        out=np.full(values.shape[1], np.nan, dtype=np.float64),
        where=n_years > 0,
    )
    centered = np.where(finite, values - means, 0.0)
    sum_squares = np.square(centered).sum(axis=0)
    variances = np.divide(
        sum_squares,
        n_years - 1,
        out=np.full(values.shape[1], np.nan, dtype=np.float64),
        where=n_years >= 2,
    )
    standard_errors = np.sqrt(variances / n_years)
    usable = (n_years >= 2) & np.isfinite(standard_errors) & (standard_errors > 0)
    t_statistics = np.divide(
        means,
        standard_errors,
        out=np.full(values.shape[1], np.nan, dtype=np.float64),
        where=usable,
    )
    degrees_of_freedom = n_years - 1
    p_values = np.full(values.shape[1], np.nan, dtype=np.float64)
    p_values[usable] = 2.0 * student_t.sf(
        np.abs(t_statistics[usable]), degrees_of_freedom[usable]
    )
    return MonthlyTTest(
        month=0,
        label="",
        mean_bias_pp=means,
        t_statistic=t_statistics,
        p_value=p_values,
        bh_q_value=benjamini_hochberg(p_values),
        n_years=n_years,
        degrees_of_freedom=degrees_of_freedom,
    )


def calculate_monthly_ttests(
    yearly_biases: dict[int, np.ndarray],
) -> list[MonthlyTTest]:
    results: list[MonthlyTTest] = []
    for month, label in ANALYSIS_MONTHS:
        result = two_sided_ttest(yearly_biases[month])
        results.append(
            MonthlyTTest(
                month=month,
                label=label,
                mean_bias_pp=result.mean_bias_pp,
                t_statistic=result.t_statistic,
                p_value=result.p_value,
                bh_q_value=result.bh_q_value,
                n_years=result.n_years,
                degrees_of_freedom=result.degrees_of_freedom,
            )
        )
    return results


def _draw_terrain(
    axis: plt.Axes,
    elevation: ElevationGrid,
    relief: np.ndarray,
    terrain_extent: tuple[float, float, float, float],
) -> None:
    axis.imshow(
        relief,
        extent=terrain_extent,
        origin="upper",
        cmap="gray",
        vmin=0,
        vmax=1,
        interpolation="bilinear",
        zorder=0,
    )
    contours = axis.contour(
        elevation.longitudes,
        elevation.latitudes,
        elevation.elevation_m,
        levels=ELEVATION_CONTOURS_M,
        colors="#303942",
        linewidths=0.5,
        alpha=0.58,
        zorder=2,
    )
    axis.clabel(
        contours,
        levels=ELEVATION_CONTOURS_M,
        fmt={2000: "2,000 m", 3000: "3,000 m"},
        fontsize=6.2,
        inline=True,
        inline_spacing=2,
        manual=[(-108.0, 37.2), (-106.6, 39.0)],
    )


def write_ttest_plot(
    results: list[MonthlyTTest],
    config: RunConfig,
    output: Path,
    elevation: ElevationGrid,
) -> None:
    if len(results) != len(ANALYSIS_MONTHS):
        raise ValueError("the significance map requires November through May")
    grid = config.target_grid
    figure, axes = plt.subplots(
        2,
        4,
        figsize=(12.8, 7.25),
        sharex=True,
        sharey=True,
        constrained_layout=True,
    )
    figure.get_layout_engine().set(
        w_pad=0.035, h_pad=0.035, wspace=0.025, hspace=0.04
    )
    relief = hillshade_grid(elevation)
    terrain_extent = _terrain_extent(elevation)
    geographic_aspect = 1.0 / np.cos(np.deg2rad(float(np.mean(grid.lats))))
    base_colormap = plt.get_cmap("RdBu_r")
    colormap = ListedColormap(
        base_colormap(np.linspace(0.12, 0.88, 256)),
        name="trimmed_RdBu_r",
    )
    colormap.set_bad("#c8c8c8", alpha=0.8)
    bias_limit = max(
        float(np.nanmax(np.abs(result.mean_bias_pp))) for result in results
    )
    if not np.isfinite(bias_limit) or bias_limit <= 0:
        raise ValueError("mean-bias results contain no finite nonzero values")
    bias_limit = float(np.ceil(bias_limit / 5.0) * 5.0)
    normalization = TwoSlopeNorm(
        vmin=-bias_limit,
        vcenter=0.0,
        vmax=bias_limit,
    )
    image = None
    for axis, result in zip(axes.ravel()[:7], results, strict=True):
        _draw_terrain(axis, elevation, relief, terrain_extent)
        image = axis.pcolormesh(
            grid.lon_edges,
            grid.lat_edges,
            result.mean_bias_pp.reshape(grid.shape),
            cmap=colormap,
            norm=normalization,
            shading="flat",
            edgecolors="#59636f",
            linewidth=0.35,
            alpha=METRIC_LAYER_ALPHA,
            zorder=1,
        )
        significant = result.p_value < TEST_ALPHA
        for slot in np.flatnonzero(significant):
            row, column = divmod(int(slot), len(grid.lons))
            axis.add_patch(
                Rectangle(
                    (grid.lon_edges[column], grid.lat_edges[row]),
                    grid.lon_edges[column + 1] - grid.lon_edges[column],
                    grid.lat_edges[row + 1] - grid.lat_edges[row],
                    facecolor="none",
                    edgecolor=(0.12, 0.14, 0.16, 0.7),
                    linewidth=0.0,
                    hatch="////",
                    zorder=3,
                )
            )
        raw_count = int(np.count_nonzero(significant))
        low_count = int(
            np.count_nonzero(significant & (result.mean_bias_pp < 0))
        )
        high_count = int(
            np.count_nonzero(significant & (result.mean_bias_pp > 0))
        )
        fdr_count = int(np.count_nonzero(result.bh_q_value < TEST_ALPHA))
        axis.set_title(
            f"{result.label}\np<0.05: {raw_count}/72 "
            f"(low {low_count}, high {high_count}); FDR {fdr_count}/72",
            fontsize=8.8,
        )
        axis.set_aspect(geographic_aspect)
        axis.set_xlim(grid.lon_edges[0], grid.lon_edges[-1])
        axis.set_ylim(grid.lat_edges[0], grid.lat_edges[-1])
        axis.set_xticks((-109, -108, -107, -106, -105, -104))
        axis.set_yticks((37, 38, 39, 40, 41))
        axis.tick_params(labelsize=7.5)
        axis.set_xlabel("Longitude (°E)")
        axis.set_ylabel("Latitude (°N)")

    note_axis = axes.ravel()[7]
    note_axis.axis("off")
    note_axis.text(
        0.03,
        0.92,
        "Two-sided cellwise test",
        transform=note_axis.transAxes,
        fontsize=12,
        fontweight="bold",
        va="top",
    )
    all_sample_sizes = np.concatenate([result.n_years for result in results])
    minimum_n = int(all_sample_sizes.min())
    maximum_n = int(all_sample_sizes.max())
    sample_label = (
        f"n={maximum_n}, df={maximum_n - 1}"
        if minimum_n == maximum_n
        else f"n={minimum_n}–{maximum_n}, df={minimum_n - 1}–{maximum_n - 1}"
    )
    note_axis.text(
        0.03,
        0.78,
        "H₀: mean bias = 0\nH₁: mean bias ≠ 0\n\n"
        "One monthly bias per water year\n"
        f"WY{config.start_water_year}–{config.end_water_year}: {sample_label}\n\n"
        "Color: mean bias (percentage points)\n"
        "Blue: MERRA-2 low; red: MERRA-2 high\n"
        "Hatching: raw two-sided p<0.05\n\n"
        "Panel FDR counts use Benjamini–Hochberg\n"
        "adjustment across the 72 cell tests.",
        transform=note_axis.transAxes,
        fontsize=9.5,
        linespacing=1.35,
        va="top",
    )
    if image is None:
        raise RuntimeError("significance plot created no panels")
    colorbar = figure.colorbar(
        image,
        ax=axes.ravel()[:7].tolist(),
        location="bottom",
        shrink=0.82,
        pad=0.035,
        ticks=np.linspace(-bias_limit, bias_limit, 7),
        label="Mean MERRA-2 − MODSCAG bias (percentage points)",
    )
    figure.suptitle(
        "Mean MERRA-2 fractional-snow-cover bias with two-sided significance\n"
        "Daily 15:00–16:00 UTC MERRA-2 versus STC-MODSCAG; "
        "USGS 3DEP hillshade and 2,000/3,000 m contours",
        fontsize=12.5,
    )
    _save_figure(figure, output)


CSV_FIELDS = (
    "month",
    "month_number",
    "slot",
    "cell_id",
    "merra_latitude",
    "merra_longitude",
    "cell_mean_elevation_m",
    "n_water_years",
    "degrees_of_freedom",
    "mean_bias_pp",
    "t_statistic",
    "two_sided_p_value",
    "benjamini_hochberg_two_sided_q_value",
    "raw_two_sided_p_lt_0_05",
    "bh_two_sided_q_lt_0_05",
    "water_years",
    "alternative",
)


def write_ttest_csv(
    results: list[MonthlyTTest],
    config: RunConfig,
    elevation: ElevationGrid,
    output: Path,
) -> None:
    cell_elevations = cell_mean_elevation_grid(elevation, config).ravel()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            writer = csv.DictWriter(temporary, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for result in results:
                for slot in range(config.target_grid.size):
                    metadata = config.target_grid.cell_metadata(slot)
                    writer.writerow(
                        {
                            "month": result.label,
                            "month_number": result.month,
                            "slot": slot,
                            "cell_id": metadata["cell_id"],
                            "merra_latitude": metadata["merra_latitude"],
                            "merra_longitude": metadata["merra_longitude"],
                            "cell_mean_elevation_m": cell_elevations[slot],
                            "n_water_years": result.n_years[slot],
                            "degrees_of_freedom": result.degrees_of_freedom[slot],
                            "mean_bias_pp": result.mean_bias_pp[slot],
                            "t_statistic": result.t_statistic[slot],
                            "two_sided_p_value": result.p_value[slot],
                            "benjamini_hochberg_two_sided_q_value": (
                                result.bh_q_value[slot]
                            ),
                            "raw_two_sided_p_lt_0_05": (
                                result.p_value[slot] < TEST_ALPHA
                            ),
                            "bh_two_sided_q_lt_0_05": (
                                result.bh_q_value[slot] < TEST_ALPHA
                            ),
                            "water_years": (
                                f"WY{config.start_water_year}-WY{config.end_water_year}"
                            ),
                            "alternative": "mean MERRA2_minus_MODSCAG bias != 0",
                        }
                    )
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.replace(output)
        output.chmod(0o644)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a two-sided MERRA-2 fSCA bias test by cell using water years as "
            "independent replicates"
        )
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=Path("results/water_year_2010_2023_monthly_checkpoints"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "results/water_year_2010_2023_pixel_bias_two_sided_ttest.png"
        ),
    )
    parser.add_argument(
        "--stats-output",
        type=Path,
        default=Path(
            "results/water_year_2010_2023_pixel_bias_two_sided_ttest.csv"
        ),
    )
    parser.add_argument(
        "--dem",
        type=Path,
        default=Path("data/usgs_3dep_coarse_dem.tif"),
    )
    parser.add_argument("--workers", type=int, default=16)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if not 1 <= args.workers <= 20:
        raise ValueError("workers must be between 1 and 20")
    config = RunConfig()
    yearly_biases = load_water_year_biases(
        args.checkpoint_dir, config, workers=args.workers
    )
    results = calculate_monthly_ttests(yearly_biases)
    elevation = load_elevation_grid(args.dem, config)
    write_ttest_plot(results, config, args.output, elevation)
    write_ttest_csv(results, config, elevation, args.stats_output)
    print(f"wrote {args.output}")
    print(f"wrote {args.stats_output}")


if __name__ == "__main__":
    main()
