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
from .reanalysis_metrics import ReanalysisStatsBlock, reanalysis_metrics_for_slot
from .spatial_plotting import (
    ANALYSIS_MONTHS,
    ELEVATION_CONTOURS_M,
    METRIC_LAYER_ALPHA,
    ElevationGrid,
    _save_figure,
    _terrain_extent,
    hillshade_grid,
    load_elevation_grid,
)


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


def write_reanalysis_spatial_monthly_plot(
    monthly_stats: list[tuple[str, ReanalysisStatsBlock]],
    config: ReanalysisRunConfig,
    spec: ReanalysisModelSpec,
    output: Path,
    elevation: ElevationGrid,
) -> None:
    """Write seven monthly bias/MAE rows with common scales and terrain context."""

    if len(monthly_stats) != 7:
        raise ValueError("the November–May spatial figure requires seven months")
    grid = config.target_grid(spec.model_id)
    bias_grids = [
        reanalysis_cell_metric_grid(stats, "bias_pp", grid.shape)
        for _, stats in monthly_stats
    ]
    mae_grids = [
        reanalysis_cell_metric_grid(stats, "mae_pp", grid.shape)
        for _, stats in monthly_stats
    ]
    bias_limit = max(float(np.nanmax(np.abs(values))) for values in bias_grids)
    mae_limit = max(float(np.nanmax(values)) for values in mae_grids)
    if not np.isfinite(bias_limit) or not np.isfinite(mae_limit):
        raise ValueError("reanalysis spatial metrics contain no finite values")

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

    for row, ((label, _), bias, mae) in enumerate(
        zip(monthly_stats, bias_grids, mae_grids, strict=True)
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
            bias,
            cmap="RdBu_r",
            vmin=-bias_limit,
            vmax=bias_limit,
            shading="flat",
            edgecolors="none",
            linewidth=0,
            alpha=METRIC_LAYER_ALPHA,
            zorder=1,
        )
        mae_image = axes[row, 1].pcolormesh(
            longitude_edges,
            latitude_edges,
            mae,
            cmap="magma_r",
            vmin=0,
            vmax=mae_limit,
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

    axes[0, 0].set_title("Mean bias", fontsize=13)
    axes[0, 1].set_title("Mean absolute error", fontsize=13)
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
        label=f"{spec.display_name} − MODSCAG\n(percentage points)",
    )
    figure.colorbar(
        mae_image,
        ax=axes[:, 1],
        location="bottom",
        shrink=0.68,
        pad=0.018,
        anchor=(0.0, 0.5),
        label="Absolute error\n(percentage points)",
    )
    figure.suptitle(
        f"{spec.display_name} versus daily STC-MODSCAG fractional snow cover\n"
        f"by {spec.longitude_step:g}° {spec.display_name} grid cell — Colorado, "
        "November 2022–May 2023\n"
        f"15:00 UTC; MODSCAG aggregated to {spec.display_name}\n"
        "USGS 3DEP hillshade; 2,000 and 3,000 m contours",
        fontsize=11.5,
    )
    _save_figure(figure, output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plot November 2022–May 2023 ERA5-Land cell bias and MAE from "
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
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
