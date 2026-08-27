from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .grids import RegularLatLonGrid
from .reanalysis_checkpoints import checkpoint_path, load_month_checkpoint
from .reanalysis_config import MODEL_SPECS, ReanalysisModelSpec, ReanalysisRunConfig
from .reanalysis_metrics import (
    ReanalysisStatsBlock,
    merge_reanalysis_blocks,
    reanalysis_metrics_for_slot,
)
from .spatial_plotting import (
    ANALYSIS_MONTHS,
    ELEVATION_CONTOURS_M,
    METRIC_LAYER_ALPHA,
    ElevationGrid,
    _save_figure,
    _terrain_extent,
    cell_mean_elevation_grid,
    hillshade_grid,
    load_elevation_grid,
)


MIN_MODIS_FSCA_PCT = 5.0
NORMALIZED_BIAS_LIMIT_PCT = 120.0
NORMALIZED_MAE_LIMIT_PCT = 140.0
ELEVATION_ANALYSIS_MONTHS = ("April 2023", "May 2023")


@dataclass(frozen=True)
class _ElevationConfig:
    target_grid: RegularLatLonGrid


def load_reanalysis_elevation_grid(
    path: Path, grid: RegularLatLonGrid
) -> ElevationGrid:
    """Load the shared DEM after checking coverage of a reanalysis grid."""

    return load_elevation_grid(path, _ElevationConfig(grid))  # type: ignore[arg-type]


def load_reanalysis_analysis_months(
    checkpoint_directory: Path,
    config: ReanalysisRunConfig,
    spec: ReanalysisModelSpec,
) -> list[tuple[str, ReanalysisStatsBlock]]:
    """Load the seven WY2023 snow-season checkpoints concurrently."""

    if spec.model_id not in config.model_ids:
        raise ValueError(f"{spec.model_id} is not selected in the run configuration")

    def load_one(
        item: tuple[int, int, str],
    ) -> tuple[str, ReanalysisStatsBlock]:
        year, month, label = item
        path = checkpoint_path(checkpoint_directory, year, month)
        if not path.exists():
            raise FileNotFoundError(
                f"missing validated monthly checkpoint {path}; complete the "
                f"{spec.display_name} WY2023 comparison first"
            )
        return label, load_month_checkpoint(path, year, month, config, spec)

    with ThreadPoolExecutor(max_workers=len(ANALYSIS_MONTHS)) as executor:
        return list(executor.map(load_one, ANALYSIS_MONTHS))


def reanalysis_cell_metric_grid(
    stats: ReanalysisStatsBlock,
    metric: str,
    shape: tuple[int, int],
) -> np.ndarray:
    if metric not in {"bias_pp", "mae_pp"}:
        raise ValueError(f"unsupported reanalysis spatial metric: {metric}")
    if stats.n_cells != shape[0] * shape[1]:
        raise ValueError("statistics cell count differs from the plotting grid")
    values = [
        reanalysis_metrics_for_slot(stats, slot)[metric]
        for slot in range(stats.n_cells)
    ]
    return np.asarray(
        [np.nan if value is None else float(value) for value in values],
        dtype=np.float64,
    ).reshape(shape)


def reanalysis_normalized_metric_grid(
    stats: ReanalysisStatsBlock,
    metric: str,
    shape: tuple[int, int],
    minimum_modis_fsca_pct: float = MIN_MODIS_FSCA_PCT,
) -> np.ndarray:
    """Return NMB or NMAE after masking cells with little paired MODSCAG snow."""

    if metric not in {"nmb_pct", "nmae_pct"}:
        raise ValueError(f"unsupported normalized reanalysis metric: {metric}")
    if stats.n_cells != shape[0] * shape[1]:
        raise ValueError("statistics cell count differs from the plotting grid")
    weights = stats.sum_w[: stats.n_cells]
    reference_sum = stats.sum_w_reference[: stats.n_cells]
    mean_reference_pct = np.divide(
        100.0 * reference_sum,
        weights,
        out=np.full(weights.shape, np.nan, dtype=np.float64),
        where=weights > 0,
    )
    numerator = (
        stats.sum_w_error[: stats.n_cells]
        if metric == "nmb_pct"
        else stats.sum_w_abs_error[: stats.n_cells]
    )
    usable = (
        (mean_reference_pct >= minimum_modis_fsca_pct)
        & (reference_sum > 0)
        & np.isfinite(mean_reference_pct)
    )
    values = np.divide(
        100.0 * numerator,
        reference_sum,
        out=np.full(reference_sum.shape, np.nan, dtype=np.float64),
        where=usable,
    )
    return values.reshape(shape)


def reanalysis_modis_fsca_grid(
    stats: ReanalysisStatsBlock,
    shape: tuple[int, int],
) -> np.ndarray:
    """Return paired, pixel-day-weighted MODSCAG fSCA as percent by cell."""

    if stats.n_cells != shape[0] * shape[1]:
        raise ValueError("statistics cell count differs from the plotting grid")
    weights = stats.sum_w[: stats.n_cells]
    reference_sum = stats.sum_w_reference[: stats.n_cells]
    values = np.divide(
        100.0 * reference_sum,
        weights,
        out=np.full(weights.shape, np.nan, dtype=np.float64),
        where=weights > 0,
    )
    return values.reshape(shape)


def _dependency_statistics(
    elevation_km: np.ndarray, values: np.ndarray
) -> tuple[float, float, float]:
    slope, intercept = np.polyfit(elevation_km, values, 1)
    correlation = (
        float("nan")
        if np.isclose(np.std(elevation_km), 0) or np.isclose(np.std(values), 0)
        else float(np.corrcoef(elevation_km, values)[0, 1])
    )
    return float(slope), float(intercept), correlation


def write_reanalysis_elevation_dependency_plot(
    monthly_stats: list[tuple[str, ReanalysisStatsBlock]],
    config: ReanalysisRunConfig,
    spec: ReanalysisModelSpec,
    output: Path,
    elevation: ElevationGrid,
) -> None:
    """Plot aggregate normalized errors and MODSCAG fSCA against elevation."""

    labels = tuple(label for label, _ in monthly_stats)
    if labels != ELEVATION_ANALYSIS_MONTHS:
        raise ValueError(
            "the elevation-dependence figure requires April and May in order"
        )
    grid = config.target_grid(spec.model_id)
    period_stats = merge_reanalysis_blocks([stats for _, stats in monthly_stats])
    elevations_km = (
        cell_mean_elevation_grid(
            elevation, _ElevationConfig(grid)  # type: ignore[arg-type]
        ).ravel()
        / 1000.0
    )
    metrics = (
        (
            "Normalized mean bias",
            reanalysis_normalized_metric_grid(
                period_stats, "nmb_pct", grid.shape
            ).ravel(),
            "Normalized mean bias (%)",
            "#2166ac",
        ),
        (
            "Normalized MAE",
            reanalysis_normalized_metric_grid(
                period_stats, "nmae_pct", grid.shape
            ).ravel(),
            "Normalized mean absolute error (%)",
            "#b2182b",
        ),
        (
            "Mean MODSCAG fSCA",
            reanalysis_modis_fsca_grid(period_stats, grid.shape).ravel(),
            "MODIS fractional snow-covered area (%)",
            "#238b45",
        ),
    )

    figure, axes = plt.subplots(
        1, 3, figsize=(14.2, 4.8), sharex=True, constrained_layout=True
    )
    for axis, (label, metric_values, y_label, color) in zip(
        axes, metrics, strict=True
    ):
        valid = np.isfinite(elevations_km) & np.isfinite(metric_values)
        x = elevations_km[valid]
        y = metric_values[valid]
        if x.size < 3:
            raise ValueError(
                f"too few valid {spec.display_name} cells for elevation analysis"
            )
        slope, intercept, correlation = _dependency_statistics(x, y)
        correlation_label = (
            "undefined" if not np.isfinite(correlation) else f"{correlation:+.2f}"
        )
        trend_x = np.linspace(float(x.min()), float(x.max()), 200)
        axis.scatter(
            x,
            y,
            s=13,
            color=color,
            alpha=0.34,
            edgecolors="none",
            rasterized=True,
        )
        axis.plot(
            trend_x,
            slope * trend_x + intercept,
            color="#252a30",
            linewidth=1.8,
        )
        if label == "Normalized mean bias":
            axis.axhline(0, color="#59636f", linewidth=0.8, alpha=0.7)
        axis.set_title(
            f"{label}\nSlope {slope:+.1f} pp km⁻¹; "
            f"Pearson r = {correlation_label}; n = {x.size:,}",
            fontsize=10.5,
        )
        axis.set_xlabel(f"{spec.display_name} cell mean elevation (km)")
        axis.set_ylabel(y_label)
        axis.grid(color="#c7ccd1", linewidth=0.5, alpha=0.55)

    figure.suptitle(
        f"Elevation dependence of {spec.display_name} normalized snow-cover error\n"
        "Colorado, April–May 2023 aggregate; USGS 3DEP cell-mean "
        "elevation\n"
        "Normalized metrics exclude paired MODSCAG fSCA < 5%; black line is "
        "the OLS trend",
        fontsize=12.5,
    )
    _save_figure(figure, output)


def write_reanalysis_spatial_monthly_plot(
    monthly_stats: list[tuple[str, ReanalysisStatsBlock]],
    config: ReanalysisRunConfig,
    spec: ReanalysisModelSpec,
    output: Path,
    elevation: ElevationGrid,
) -> None:
    """Write seven monthly NMB/NMAE rows with common scales and terrain context."""

    if len(monthly_stats) != 7:
        raise ValueError("the November–May spatial figure requires seven months")
    grid = config.target_grid(spec.model_id)
    nmb_grids = [
        reanalysis_normalized_metric_grid(stats, "nmb_pct", grid.shape)
        for _, stats in monthly_stats
    ]
    nmae_grids = [
        reanalysis_normalized_metric_grid(stats, "nmae_pct", grid.shape)
        for _, stats in monthly_stats
    ]
    if not any(np.isfinite(values).any() for values in (*nmb_grids, *nmae_grids)):
        raise ValueError("normalized reanalysis spatial metrics contain no finite values")

    figure, axes = plt.subplots(
        7,
        2,
        figsize=(5.1, 17.3),
        sharex=True,
        sharey=True,
        constrained_layout=True,
    )
    figure.get_layout_engine().set(
        w_pad=0.025, h_pad=0.025, wspace=0.025, hspace=0.025
    )
    longitude_edges = grid.lon_edges
    latitude_edges = grid.lat_edges
    geographic_aspect = 1.0 / np.cos(np.deg2rad(float(np.mean(grid.lats))))
    relief = hillshade_grid(elevation)
    terrain_extent = _terrain_extent(elevation)
    bias_image = None
    mae_image = None
    normalized_bias_cmap = plt.get_cmap("RdBu_r").copy()
    normalized_mae_cmap = plt.get_cmap("magma_r").copy()
    normalized_bias_cmap.set_bad("#c8c8c8", alpha=0.78)
    normalized_mae_cmap.set_bad("#c8c8c8", alpha=0.78)

    for row, ((label, _), nmb, nmae) in enumerate(
        zip(monthly_stats, nmb_grids, nmae_grids, strict=True)
    ):
        for axis in axes[row]:
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
        bias_image = axes[row, 0].pcolormesh(
            longitude_edges,
            latitude_edges,
            nmb,
            cmap=normalized_bias_cmap,
            vmin=-NORMALIZED_BIAS_LIMIT_PCT,
            vmax=NORMALIZED_BIAS_LIMIT_PCT,
            shading="flat",
            edgecolors="none",
            linewidth=0,
            alpha=METRIC_LAYER_ALPHA,
            zorder=1,
        )
        mae_image = axes[row, 1].pcolormesh(
            longitude_edges,
            latitude_edges,
            nmae,
            cmap=normalized_mae_cmap,
            vmin=0,
            vmax=NORMALIZED_MAE_LIMIT_PCT,
            shading="flat",
            edgecolors="none",
            linewidth=0,
            alpha=METRIC_LAYER_ALPHA,
            zorder=1,
        )
        for axis in axes[row]:
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
                fontsize=5.5,
                inline=True,
                inline_spacing=2,
                manual=[(-108.0, 37.2), (-106.6, 39.0)],
            )
            axis.set_aspect(geographic_aspect)
            axis.set_xlim(longitude_edges[0], longitude_edges[-1])
            axis.set_ylim(latitude_edges[0], latitude_edges[-1])
            axis.set_yticks((37, 38, 39, 40, 41))
            axis.tick_params(labelsize=8)
        axes[row, 0].set_ylabel(f"{label}\nLatitude (°N)")
        axes[row, 0].set_anchor("E")
        axes[row, 1].set_anchor("W")

    axes[0, 0].set_title("Normalized mean bias\n(NMB)", fontsize=12)
    axes[0, 1].set_title("Normalized mean absolute error\n(NMAE)", fontsize=12)
    for axis in axes[-1]:
        axis.set_xlabel("Longitude (°E)")
        axis.set_xticks((-109, -108, -107, -106, -105, -104))
    if bias_image is None or mae_image is None:
        raise RuntimeError("reanalysis spatial plot created no panels")
    figure.colorbar(
        bias_image,
        ax=axes[:, 0],
        location="bottom",
        shrink=0.68,
        pad=0.018,
        anchor=(1.0, 0.5),
        extend="both",
        label="NMB (%)",
    )
    figure.colorbar(
        mae_image,
        ax=axes[:, 1],
        location="bottom",
        shrink=0.68,
        pad=0.018,
        anchor=(0.0, 0.5),
        extend="max",
        label="NMAE (%)",
    )
    figure.suptitle(
        f"{spec.display_name} versus daily STC-MODSCAG fractional snow cover\n"
        f"by {spec.longitude_step:g}° {spec.display_name} grid cell — Colorado, "
        "November 2022–May 2023\n"
        f"15:00 UTC; MODSCAG aggregated to {spec.display_name}\n"
        "Masked where paired MODSCAG fSCA < 5%; USGS 3DEP hillshade; "
        "2,000 and 3,000 m contours",
        fontsize=11.5,
    )
    _save_figure(figure, output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plot November 2022–May 2023 ERA5-Land cell NMB and NMAE from "
            "validated monthly comparison checkpoints"
        )
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=Path(
            "results/era5_land_modis_water_year_2023_2023_monthly_checkpoints"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/era5_land_wy2023_nov_may_spatial_bias_mae.png"),
    )
    parser.add_argument(
        "--elevation-output",
        type=Path,
        default=Path(
            "results/era5_land_wy2023_apr_may_elevation_dependency.png"
        ),
    )
    parser.add_argument(
        "--dem",
        type=Path,
        default=Path("data/usgs_3dep_era5_land_coarse_dem.tif"),
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = ReanalysisRunConfig(
        start_water_year=2023,
        end_water_year=2023,
        model_ids=("era5-land",),
    )
    spec = MODEL_SPECS["era5-land"]
    monthly_stats = load_reanalysis_analysis_months(
        args.checkpoint_dir, config, spec
    )
    elevation = load_reanalysis_elevation_grid(
        args.dem, config.target_grid(spec.model_id)
    )
    write_reanalysis_spatial_monthly_plot(
        monthly_stats, config, spec, args.output, elevation
    )
    elevation_months = [
        (label, stats)
        for label, stats in monthly_stats
        if label in ELEVATION_ANALYSIS_MONTHS
    ]
    write_reanalysis_elevation_dependency_plot(
        elevation_months, config, spec, args.elevation_output, elevation
    )
    print(f"wrote {args.output}")
    print(f"wrote {args.elevation_output}")


if __name__ == "__main__":
    main()
