from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .checkpoints import checkpoint_path, load_month_checkpoint
from .config import RunConfig
from .metrics import StatsBlock, merge_blocks
from .modis_fsca_stats import (
    ModisStatsBlock,
    load_modis_checkpoint,
    mean_modis_fsca_pct,
    merge_modis_blocks,
    modis_checkpoint_path,
)
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


COMPOSITE_GROUPS = (
    ("Wet", (2011, 2017, 2019, 2023)),
    ("Dry", (2012, 2013, 2015, 2018)),
)
COMPOSITE_MONTHS = (
    (11, "November"),
    (12, "December"),
    (1, "January"),
    (2, "February"),
    (3, "March"),
    (4, "April"),
    (5, "May"),
)
MIN_MODIS_FSCA_PCT = 5.0


def calendar_period_for_water_year(water_year: int, month: int) -> tuple[int, int]:
    if month not in {11, 12, 1, 2, 3, 4, 5}:
        raise ValueError("composite month must be between November and May")
    return (water_year - 1 if month >= 10 else water_year, month)


def load_composite_months(
    checkpoint_directory: Path, config: RunConfig, workers: int = 16
) -> dict[str, list[tuple[str, StatsBlock]]]:
    """Load 56 validated checkpoints and merge four water years per month."""

    tasks: list[tuple[str, int, int, int, int]] = []
    for group, water_years in COMPOSITE_GROUPS:
        for month_index, (month, _) in enumerate(COMPOSITE_MONTHS):
            for water_year in water_years:
                year, calendar_month = calendar_period_for_water_year(
                    water_year, month
                )
                tasks.append(
                    (group, month_index, water_year, year, calendar_month)
                )

    def load_one(
        task: tuple[str, int, int, int, int]
    ) -> tuple[str, int, int, StatsBlock]:
        group, month_index, water_year, year, month = task
        path = checkpoint_path(checkpoint_directory, year, month)
        if not path.exists():
            raise FileNotFoundError(
                f"missing validated checkpoint {path} for WY{water_year}"
            )
        stats = load_month_checkpoint(path, year, month, config)
        return group, month_index, water_year, stats

    loaded: dict[str, list[list[StatsBlock]]] = {
        group: [[] for _ in COMPOSITE_MONTHS] for group, _ in COMPOSITE_GROUPS
    }
    with ThreadPoolExecutor(max_workers=min(workers, len(tasks))) as executor:
        for group, month_index, _, stats in executor.map(load_one, tasks):
            loaded[group][month_index].append(stats)

    composites: dict[str, list[tuple[str, StatsBlock]]] = {}
    for group, water_years in COMPOSITE_GROUPS:
        composites[group] = []
        for month_index, (_, label) in enumerate(COMPOSITE_MONTHS):
            blocks = loaded[group][month_index]
            if len(blocks) != len(water_years):
                raise RuntimeError(
                    f"{group} {label} loaded {len(blocks)} of "
                    f"{len(water_years)} water years"
                )
            composites[group].append((label, merge_blocks(blocks)))
    return composites


def load_modis_composite_months(
    checkpoint_directory: Path, config: RunConfig, workers: int = 16
) -> dict[str, list[tuple[str, ModisStatsBlock]]]:
    """Load the 56 standalone MODIS checkpoints and merge by group/month."""

    tasks: list[tuple[str, int, int, int, int]] = []
    for group, water_years in COMPOSITE_GROUPS:
        for month_index, (month, _) in enumerate(COMPOSITE_MONTHS):
            for water_year in water_years:
                year, calendar_month = calendar_period_for_water_year(
                    water_year, month
                )
                tasks.append(
                    (group, month_index, water_year, year, calendar_month)
                )

    def load_one(
        task: tuple[str, int, int, int, int]
    ) -> tuple[str, int, ModisStatsBlock]:
        group, month_index, water_year, year, month = task
        path = modis_checkpoint_path(checkpoint_directory, year, month)
        if not path.exists():
            raise FileNotFoundError(
                f"missing standalone MODIS checkpoint {path} for WY{water_year}; "
                "run plot_wet_dry_composites.zsh to build it"
            )
        return group, month_index, load_modis_checkpoint(
            path, year, month, config
        )

    loaded: dict[str, list[list[ModisStatsBlock]]] = {
        group: [[] for _ in COMPOSITE_MONTHS] for group, _ in COMPOSITE_GROUPS
    }
    with ThreadPoolExecutor(max_workers=min(workers, len(tasks))) as executor:
        for group, month_index, stats in executor.map(load_one, tasks):
            loaded[group][month_index].append(stats)

    composites: dict[str, list[tuple[str, ModisStatsBlock]]] = {}
    for group, water_years in COMPOSITE_GROUPS:
        composites[group] = []
        for month_index, (_, label) in enumerate(COMPOSITE_MONTHS):
            blocks = loaded[group][month_index]
            if len(blocks) != len(water_years):
                raise RuntimeError(
                    f"{group} {label} loaded {len(blocks)} of "
                    f"{len(water_years)} MODIS water years"
                )
            composites[group].append((label, merge_modis_blocks(blocks)))
    return composites


def _validate_composites(
    composites: dict[str, list[tuple[str, StatsBlock]]],
) -> None:
    expected_groups = {group for group, _ in COMPOSITE_GROUPS}
    if set(composites) != expected_groups:
        raise ValueError(f"expected composite groups {sorted(expected_groups)}")
    if any(len(composites[group]) != 7 for group in expected_groups):
        raise ValueError("each composite must contain November through May")


def _validate_modis_composites(
    composites: dict[str, list[tuple[str, ModisStatsBlock]]],
) -> None:
    expected_groups = {group for group, _ in COMPOSITE_GROUPS}
    if set(composites) != expected_groups:
        raise ValueError(f"expected MODIS composite groups {sorted(expected_groups)}")
    if any(len(composites[group]) != 7 for group in expected_groups):
        raise ValueError("each MODIS composite must contain November through May")


def modis_fsca_grid(
    stats: ModisStatsBlock, shape: tuple[int, int]
) -> np.ndarray:
    values = [mean_modis_fsca_pct(stats, slot) for slot in range(stats.n_cells)]
    return np.asarray(
        [np.nan if value is None else float(value) for value in values],
        dtype=np.float64,
    ).reshape(shape)


def normalized_error_grid(
    comparison: StatsBlock,
    modis: ModisStatsBlock,
    metric: str,
    shape: tuple[int, int],
    minimum_modis_fsca_pct: float = MIN_MODIS_FSCA_PCT,
) -> np.ndarray:
    """Return exact NMB or NMAE, masking cells with little reference snow."""

    if metric not in {"nmb_pct", "nmae_pct"}:
        raise ValueError(f"unsupported normalized metric: {metric}")
    if comparison.n_cells != modis.n_cells:
        raise ValueError("comparison and MODIS statistics use different grids")
    comparison_weights = comparison.sum_w[: comparison.n_cells]
    modis_weights = modis.sum_w[: modis.n_cells]
    if not np.array_equal(comparison_weights, modis_weights) or not np.array_equal(
        comparison.n_days[: comparison.n_cells],
        modis.n_days[: modis.n_cells],
    ):
        raise ValueError(
            "normalized metrics require exactly matched comparison and MODIS weights"
        )
    denominator = modis.sum_w_fsca[: modis.n_cells]
    mean_modis_fsca = np.divide(
        100.0 * denominator,
        modis_weights,
        out=np.full(modis_weights.shape, np.nan, dtype=np.float64),
        where=modis_weights > 0,
    )
    numerator = (
        comparison.sum_w_error[: comparison.n_cells]
        if metric == "nmb_pct"
        else comparison.sum_w_abs_error[: comparison.n_cells]
    )
    usable = (mean_modis_fsca >= minimum_modis_fsca_pct) & (denominator > 0)
    values = np.divide(
        100.0 * numerator,
        denominator,
        out=np.full(denominator.shape, np.nan, dtype=np.float64),
        where=usable,
    )
    return values.reshape(shape)


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
        linewidths=0.45,
        alpha=0.5,
        zorder=2,
    )
    axis.clabel(
        contours,
        levels=ELEVATION_CONTOURS_M,
        fmt={2000: "2,000 m", 3000: "3,000 m"},
        fontsize=5.2,
        inline=True,
        inline_spacing=2,
        manual=[(-108.0, 37.2), (-106.6, 39.0)],
    )


def write_composite_spatial_plot(
    composites: dict[str, list[tuple[str, StatsBlock]]],
    modis_composites: dict[str, list[tuple[str, ModisStatsBlock]]],
    config: RunConfig,
    output: Path,
    elevation: ElevationGrid,
) -> None:
    _validate_composites(composites)
    _validate_modis_composites(modis_composites)
    grid = config.target_grid
    column_specs = (
        ("Wet", "nmb_pct", "Wet composite\nNormalized mean bias"),
        ("Dry", "nmb_pct", "Dry composite\nNormalized mean bias"),
        ("Wet", "nmae_pct", "Wet composite\nNormalized MAE"),
        ("Dry", "nmae_pct", "Dry composite\nNormalized MAE"),
        ("Wet", "modis_fsca_pct", "Wet composite\nMODIS fSCA"),
        ("Dry", "modis_fsca_pct", "Dry composite\nMODIS fSCA"),
    )
    metric_grids: dict[tuple[str, str], list[np.ndarray]] = {}
    for group, _ in COMPOSITE_GROUPS:
        for metric in ("nmb_pct", "nmae_pct"):
            metric_grids[(group, metric)] = [
                normalized_error_grid(
                    comparison_stats,
                    modis_stats,
                    metric,
                    grid.shape,
                )
                for (_, comparison_stats), (_, modis_stats) in zip(
                    composites[group], modis_composites[group], strict=True
                )
            ]
        metric_grids[(group, "modis_fsca_pct")] = [
            modis_fsca_grid(stats, grid.shape)
            for _, stats in modis_composites[group]
        ]
    bias_limit = max(
        float(np.nanmax(np.abs(values)))
        for group, _ in COMPOSITE_GROUPS
        for values in metric_grids[(group, "nmb_pct")]
    )
    mae_limit = max(
        float(np.nanmax(values))
        for group, _ in COMPOSITE_GROUPS
        for values in metric_grids[(group, "nmae_pct")]
    )
    if not np.isfinite(bias_limit) or not np.isfinite(mae_limit):
        raise ValueError("composite spatial metrics contain no finite values")
    bias_limit = float(np.ceil(bias_limit / 10.0) * 10.0)
    mae_limit = float(np.ceil(mae_limit / 10.0) * 10.0)

    figure, axes = plt.subplots(
        7,
        6,
        figsize=(14.1, 17.3),
        sharex=True,
        sharey=True,
        constrained_layout=True,
    )
    figure.get_layout_engine().set(
        w_pad=0.025, h_pad=0.025, wspace=0.02, hspace=0.025
    )
    longitude_edges = grid.lon_edges
    latitude_edges = grid.lat_edges
    geographic_aspect = 1.0 / np.cos(np.deg2rad(float(np.mean(grid.lats))))
    relief = hillshade_grid(elevation)
    terrain_extent = _terrain_extent(elevation)
    images: dict[str, object] = {}
    normalized_bias_cmap = plt.get_cmap("RdBu_r").copy()
    normalized_mae_cmap = plt.get_cmap("magma_r").copy()
    normalized_bias_cmap.set_bad("#c8c8c8", alpha=0.78)
    normalized_mae_cmap.set_bad("#c8c8c8", alpha=0.78)

    for row, (_, month_label) in enumerate(COMPOSITE_MONTHS):
        for column, (group, metric, _) in enumerate(column_specs):
            axis = axes[row, column]
            _draw_terrain(axis, elevation, relief, terrain_extent)
            is_bias = metric == "nmb_pct"
            is_fsca = metric == "modis_fsca_pct"
            images[metric] = axis.pcolormesh(
                longitude_edges,
                latitude_edges,
                metric_grids[(group, metric)][row],
                cmap=(
                    normalized_bias_cmap
                    if is_bias
                    else ("Blues" if is_fsca else normalized_mae_cmap)
                ),
                vmin=-bias_limit if is_bias else 0,
                vmax=bias_limit if is_bias else (100 if is_fsca else mae_limit),
                shading="flat",
                edgecolors="#59636f",
                linewidth=0.32,
                alpha=METRIC_LAYER_ALPHA,
                zorder=1,
            )
            axis.set_aspect(geographic_aspect)
            axis.set_xlim(longitude_edges[0], longitude_edges[-1])
            axis.set_ylim(latitude_edges[0], latitude_edges[-1])
            axis.set_yticks((37, 38, 39, 40, 41))
            axis.tick_params(labelsize=7.5)
        axes[row, 0].set_ylabel(f"{month_label}\nLatitude (°N)")

    for column, (_, _, title) in enumerate(column_specs):
        axes[0, column].set_title(title, fontsize=10.5)
        axes[-1, column].set_xlabel("Longitude (°E)")
        axes[-1, column].set_xticks((-109, -108, -107, -106, -105, -104))
    figure.colorbar(
        images["nmb_pct"],
        ax=axes[:, :2],
        location="bottom",
        shrink=0.72,
        pad=0.018,
        label="Normalized mean bias (%)",
    )
    figure.colorbar(
        images["nmae_pct"],
        ax=axes[:, 2:4],
        location="bottom",
        shrink=0.72,
        pad=0.018,
        label="Normalized mean absolute error (%)",
    )
    figure.colorbar(
        images["modis_fsca_pct"],
        ax=axes[:, 4:],
        location="bottom",
        shrink=0.72,
        pad=0.018,
        label="MODIS fractional snow-covered area (%)",
    )
    figure.suptitle(
        "Wet- and dry-year composites of fractional snow cover and normalized MERRA-2 error\n"
        "Wet WYs: 2011, 2017, 2019, 2023; Dry WYs: 2012, 2013, 2015, 2018\n"
        "November–May; daily 15:00–16:00 UTC MERRA-2 versus STC-MODSCAG\n"
        "Normalized metrics masked where composite MODIS fSCA < 5%; "
        "USGS 3DEP hillshade and contours",
        fontsize=12.5,
    )
    _save_figure(figure, output)


def _dependency_statistics(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    slope, intercept = np.polyfit(x, y, 1)
    correlation = (
        float("nan")
        if np.isclose(np.std(x), 0) or np.isclose(np.std(y), 0)
        else float(np.corrcoef(x, y)[0, 1])
    )
    return float(slope), float(intercept), correlation


def write_composite_elevation_plot(
    composites: dict[str, list[tuple[str, StatsBlock]]],
    modis_composites: dict[str, list[tuple[str, ModisStatsBlock]]],
    config: RunConfig,
    output: Path,
    elevation: ElevationGrid,
) -> None:
    _validate_composites(composites)
    _validate_modis_composites(modis_composites)
    grid = config.target_grid
    elevations_km = cell_mean_elevation_grid(elevation, config).ravel() / 1000.0
    period_stats = {
        group: merge_blocks([stats for _, stats in composites[group]])
        for group, _ in COMPOSITE_GROUPS
    }
    period_modis_stats = {
        group: merge_modis_blocks(
            [stats for _, stats in modis_composites[group]]
        )
        for group, _ in COMPOSITE_GROUPS
    }
    values = {
        (group, metric): normalized_error_grid(
            period_stats[group],
            period_modis_stats[group],
            metric,
            grid.shape,
        ).ravel()
        for group, _ in COMPOSITE_GROUPS
        for metric in ("nmb_pct", "nmae_pct")
    }
    values.update(
        {
            (group, "modis_fsca_pct"): modis_fsca_grid(
                period_modis_stats[group], grid.shape
            ).ravel()
            for group, _ in COMPOSITE_GROUPS
        }
    )

    figure, axes = plt.subplots(
        2,
        3,
        figsize=(13.5, 7.7),
        sharex=True,
        sharey="col",
        constrained_layout=True,
    )
    metric_specs = (
        ("nmb_pct", "Normalized mean bias", "#2166ac"),
        ("nmae_pct", "Normalized MAE", "#b2182b"),
        ("modis_fsca_pct", "Mean MODIS fSCA", "#238b45"),
    )
    for row, (group, _) in enumerate(COMPOSITE_GROUPS):
        for column, (metric, metric_label, color) in enumerate(metric_specs):
            axis = axes[row, column]
            metric_values = values[(group, metric)]
            valid = np.isfinite(elevations_km) & np.isfinite(metric_values)
            x = elevations_km[valid]
            y = metric_values[valid]
            if x.size < 3:
                raise ValueError(
                    f"too few valid MERRA-2 cells for the {group} composite"
                )
            slope, intercept, correlation = _dependency_statistics(x, y)
            correlation_label = (
                "undefined"
                if not np.isfinite(correlation)
                else f"{correlation:+.2f}"
            )
            trend_x = np.linspace(float(x.min()), float(x.max()), 200)
            axis.scatter(
                x,
                y,
                s=32,
                color=color,
                alpha=0.68,
                edgecolors="white",
                linewidths=0.45,
            )
            axis.plot(
                trend_x,
                slope * trend_x + intercept,
                color="#252a30",
                linewidth=1.7,
            )
            if metric == "nmb_pct":
                axis.axhline(0, color="#59636f", linewidth=0.8, alpha=0.7)
            axis.set_title(
                f"{group} composite — {metric_label}\n"
                f"Slope {slope:+.1f} pp km⁻¹; Pearson r = {correlation_label}",
                fontsize=10.5,
            )
            axis.grid(color="#c7ccd1", linewidth=0.5, alpha=0.55)
            if row == 1:
                axis.set_xlabel("MERRA-2 cell mean elevation (km)")
            if column == 0:
                axis.set_ylabel("Normalized mean bias (%)")
            elif column == 1:
                axis.set_ylabel("Normalized mean absolute error (%)")
            else:
                axis.set_ylabel("MODIS fractional snow-covered area (%)")
    figure.suptitle(
        "Elevation dependence of wet- and dry-year normalized snow-cover error\n"
        "Four water years per group, November–May; USGS 3DEP cell-mean elevation\n"
        "Normalized metrics exclude MODIS fSCA < 5%; black line is the OLS trend",
        fontsize=13,
    )
    _save_figure(figure, output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plot wet- and dry-water-year MERRA-2/MODSCAG composites"
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=Path("results/water_year_2010_2023_monthly_checkpoints"),
    )
    parser.add_argument(
        "--spatial-output",
        type=Path,
        default=Path("results/wet_dry_composite_spatial_bias_mae.png"),
    )
    parser.add_argument(
        "--elevation-output",
        type=Path,
        default=Path("results/wet_dry_composite_elevation_dependency.png"),
    )
    parser.add_argument(
        "--modis-checkpoint-dir",
        type=Path,
        default=Path("results/wet_dry_modis_fsca_monthly_checkpoints"),
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
    composites = load_composite_months(
        args.checkpoint_dir, config, workers=args.workers
    )
    modis_composites = load_modis_composite_months(
        args.modis_checkpoint_dir, config, workers=args.workers
    )
    elevation = load_elevation_grid(args.dem, config)
    write_composite_spatial_plot(
        composites,
        modis_composites,
        config,
        args.spatial_output,
        elevation,
    )
    write_composite_elevation_plot(
        composites,
        modis_composites,
        config,
        args.elevation_output,
        elevation,
    )
    print(f"wrote {args.spatial_output}")
    print(f"wrote {args.elevation_output}")


if __name__ == "__main__":
    main()
