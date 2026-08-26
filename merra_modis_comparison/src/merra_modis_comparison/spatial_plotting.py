from __future__ import annotations

import argparse
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import LightSource

from .checkpoints import checkpoint_path, load_month_checkpoint
from .config import RunConfig
from .metrics import StatsBlock, merge_blocks, metrics_for_slot


ANALYSIS_MONTHS = (
    (2022, 11, "November 2022"),
    (2022, 12, "December 2022"),
    (2023, 1, "January 2023"),
    (2023, 2, "February 2023"),
    (2023, 3, "March 2023"),
    (2023, 4, "April 2023"),
    (2023, 5, "May 2023"),
)
ELEVATION_CONTOURS_M = (2000, 3000)
METRIC_LAYER_ALPHA = 0.88


@dataclass(frozen=True)
class ElevationGrid:
    longitudes: np.ndarray
    latitudes: np.ndarray
    elevation_m: np.ndarray


def load_elevation_grid(path: Path, config: RunConfig) -> ElevationGrid:
    if not path.exists():
        raise FileNotFoundError(
            f"missing elevation raster {path}; run download_coarse_dem.zsh"
        )
    with rasterio.open(path) as dataset:
        if dataset.crs is None or dataset.crs.to_epsg() != 4326:
            raise ValueError("elevation raster must use EPSG:4326")
        if dataset.transform.b != 0 or dataset.transform.d != 0:
            raise ValueError("rotated elevation rasters are not supported")
        bounds = dataset.bounds
        grid = config.target_grid
        if (
            bounds.left > grid.lon_edges[0]
            or bounds.right < grid.lon_edges[-1]
            or bounds.bottom > grid.lat_edges[0]
            or bounds.top < grid.lat_edges[-1]
        ):
            raise ValueError("elevation raster does not cover the comparison grid")
        elevation = dataset.read(1, masked=True).filled(np.nan).astype(np.float64)
        longitudes = bounds.left + (
            np.arange(dataset.width, dtype=np.float64) + 0.5
        ) * dataset.transform.a
        latitudes = bounds.top + (
            np.arange(dataset.height, dtype=np.float64) + 0.5
        ) * dataset.transform.e
    if not np.isfinite(elevation).any():
        raise ValueError("elevation raster contains no finite values")
    return ElevationGrid(longitudes, latitudes, elevation)


def load_analysis_months(
    checkpoint_directory: Path, config: RunConfig
) -> list[tuple[str, StatsBlock]]:
    """Load and validate the seven independent month files concurrently."""

    def load_one(item: tuple[int, int, str]) -> tuple[str, StatsBlock]:
        year, month, label = item
        path = checkpoint_path(checkpoint_directory, year, month)
        if not path.exists():
            raise FileNotFoundError(
                f"missing validated monthly checkpoint {path}; complete the "
                "main comparison pipeline first"
            )
        return label, load_month_checkpoint(path, year, month, config)

    with ThreadPoolExecutor(max_workers=len(ANALYSIS_MONTHS)) as executor:
        return list(executor.map(load_one, ANALYSIS_MONTHS))


def cell_metric_grid(stats: StatsBlock, metric: str, shape: tuple[int, int]) -> np.ndarray:
    if metric not in {"bias_pp", "mae_pp"}:
        raise ValueError(f"unsupported spatial metric: {metric}")
    values = [metrics_for_slot(stats, slot)[metric] for slot in range(stats.n_cells)]
    return np.asarray(
        [np.nan if value is None else float(value) for value in values],
        dtype=np.float64,
    ).reshape(shape)


def hillshade_grid(elevation: ElevationGrid) -> np.ndarray:
    """Return geographically scaled shaded relief for a north-up DEM."""

    longitude_step = float(np.median(np.abs(np.diff(elevation.longitudes))))
    latitude_step = float(np.median(np.abs(np.diff(elevation.latitudes))))
    mean_latitude = float(np.mean(elevation.latitudes))
    dx_m = longitude_step * 111_320.0 * np.cos(np.deg2rad(mean_latitude))
    dy_m = latitude_step * 111_320.0
    filled = np.where(
        np.isfinite(elevation.elevation_m),
        elevation.elevation_m,
        np.nanmedian(elevation.elevation_m),
    )
    return LightSource(azdeg=315, altdeg=42).hillshade(
        filled,
        vert_exag=1.15,
        dx=dx_m,
        dy=dy_m,
        fraction=1.2,
    )


def cell_mean_elevation_grid(
    elevation: ElevationGrid, config: RunConfig
) -> np.ndarray:
    """Area-weight the coarse DEM samples inside each MERRA-2 grid cell."""

    grid = config.target_grid
    result = np.full(grid.shape, np.nan, dtype=np.float64)
    for row, (south, north) in enumerate(
        zip(grid.lat_edges[:-1], grid.lat_edges[1:], strict=True)
    ):
        latitude_mask = (elevation.latitudes >= south) & (
            elevation.latitudes < north
        )
        for column, (west, east) in enumerate(
            zip(grid.lon_edges[:-1], grid.lon_edges[1:], strict=True)
        ):
            longitude_mask = (elevation.longitudes >= west) & (
                elevation.longitudes < east
            )
            values = elevation.elevation_m[np.ix_(latitude_mask, longitude_mask)]
            latitude_weights = np.cos(
                np.deg2rad(elevation.latitudes[latitude_mask])
            )[:, np.newaxis]
            weights = np.broadcast_to(latitude_weights, values.shape)
            valid = np.isfinite(values)
            if valid.any():
                result[row, column] = np.average(
                    values[valid], weights=weights[valid]
                )
    if not np.isfinite(result).all():
        raise ValueError("DEM does not provide samples for every MERRA-2 cell")
    return result


def _terrain_extent(elevation: ElevationGrid) -> tuple[float, float, float, float]:
    longitude_step = float(np.median(np.abs(np.diff(elevation.longitudes))))
    latitude_step = float(np.median(np.abs(np.diff(elevation.latitudes))))
    return (
        float(elevation.longitudes[0] - longitude_step / 2),
        float(elevation.longitudes[-1] + longitude_step / 2),
        float(elevation.latitudes[-1] - latitude_step / 2),
        float(elevation.latitudes[0] + latitude_step / 2),
    )


def _save_figure(figure: plt.Figure, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".png",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        figure.savefig(temporary_path, dpi=220, bbox_inches="tight", facecolor="white")
        temporary_path.replace(output)
        output.chmod(0o644)
    finally:
        plt.close(figure)
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def write_spatial_monthly_plot(
    monthly_stats: list[tuple[str, StatsBlock]],
    config: RunConfig,
    output: Path,
    elevation: ElevationGrid | None = None,
) -> None:
    if len(monthly_stats) != 7:
        raise ValueError("the November–May spatial figure requires seven months")
    grid = config.target_grid
    bias_grids = [
        cell_metric_grid(stats, "bias_pp", grid.shape) for _, stats in monthly_stats
    ]
    mae_grids = [
        cell_metric_grid(stats, "mae_pp", grid.shape) for _, stats in monthly_stats
    ]
    bias_limit = max(float(np.nanmax(np.abs(values))) for values in bias_grids)
    mae_limit = max(float(np.nanmax(values)) for values in mae_grids)
    if not np.isfinite(bias_limit) or not np.isfinite(mae_limit):
        raise ValueError("spatial metrics contain no finite values")

    figure, axes = plt.subplots(
        7,
        2,
        figsize=(4.9, 17.3),
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
    relief = None if elevation is None else hillshade_grid(elevation)
    terrain_extent = None if elevation is None else _terrain_extent(elevation)
    bias_image = None
    mae_image = None
    for row, ((label, _), bias, mae) in enumerate(
        zip(monthly_stats, bias_grids, mae_grids, strict=True)
    ):
        if relief is not None and terrain_extent is not None:
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
            edgecolors="#59636f",
            linewidth=0.35,
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
            edgecolors="#59636f",
            linewidth=0.35,
            alpha=METRIC_LAYER_ALPHA,
            zorder=1,
        )
        if elevation is not None:
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
        axes[row, 0].set_ylabel(f"{label}\nLatitude (°N)")
        for axis in axes[row]:
            axis.set_aspect(geographic_aspect)
            axis.set_xlim(longitude_edges[0], longitude_edges[-1])
            axis.set_ylim(latitude_edges[0], latitude_edges[-1])
            axis.set_yticks((37, 38, 39, 40, 41))
            axis.tick_params(labelsize=8)
        axes[row, 0].set_anchor("E")
        axes[row, 1].set_anchor("W")

    axes[0, 0].set_title("Mean bias", fontsize=13)
    axes[0, 1].set_title("Mean absolute error", fontsize=13)
    axes[-1, 0].set_xlabel("Longitude (°E)")
    axes[-1, 1].set_xlabel("Longitude (°E)")
    for axis in axes[-1]:
        axis.set_xticks((-109, -108, -107, -106, -105, -104))
    if bias_image is None or mae_image is None:
        raise RuntimeError("spatial plot created no panels")
    figure.colorbar(
        bias_image,
        ax=axes[:, 0],
        location="bottom",
        shrink=0.68,
        pad=0.018,
        anchor=(1.0, 0.5),
        label="MERRA-2 − MODSCAG\n(percentage points)",
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
        "MERRA-2 versus daily STC-MODSCAG fractional snow cover\n"
        "by MERRA-2 grid cell — Colorado, November 2022–May 2023\n"
        "15:00–16:00 UTC; MODSCAG aggregated to MERRA-2\n"
        "USGS 3DEP hillshade; 2,000 and 3,000 m contours",
        fontsize=11.5,
    )
    _save_figure(figure, output)


def write_elevation_dependency_plot(
    monthly_stats: list[tuple[str, StatsBlock]],
    config: RunConfig,
    output: Path,
    elevation: ElevationGrid,
) -> None:
    """Plot period-aggregate cell errors against mean cell elevation."""

    if len(monthly_stats) != 7:
        raise ValueError("the elevation-dependence figure requires seven months")
    grid = config.target_grid
    period_stats = merge_blocks([stats for _, stats in monthly_stats])
    elevations_km = cell_mean_elevation_grid(elevation, config).ravel() / 1000.0
    metrics = {
        "Mean bias": cell_metric_grid(period_stats, "bias_pp", grid.shape).ravel(),
        "Mean absolute error": cell_metric_grid(
            period_stats, "mae_pp", grid.shape
        ).ravel(),
    }

    figure, axes = plt.subplots(1, 2, figsize=(9.3, 4.25), constrained_layout=True)
    colors = ("#2166ac", "#b2182b")
    for axis, ((label, values), color) in zip(
        axes, zip(metrics.items(), colors, strict=True), strict=True
    ):
        valid = np.isfinite(elevations_km) & np.isfinite(values)
        x = elevations_km[valid]
        y = values[valid]
        if x.size < 3:
            raise ValueError("too few valid MERRA-2 cells for elevation analysis")
        slope, intercept = np.polyfit(x, y, 1)
        correlation = (
            float("nan")
            if np.isclose(np.std(x), 0) or np.isclose(np.std(y), 0)
            else float(np.corrcoef(x, y)[0, 1])
        )
        correlation_label = (
            "undefined" if not np.isfinite(correlation) else f"{correlation:+.2f}"
        )
        trend_x = np.linspace(float(x.min()), float(x.max()), 200)
        axis.scatter(
            x,
            y,
            s=34,
            color=color,
            alpha=0.68,
            edgecolors="white",
            linewidths=0.45,
            label=f"MERRA-2 cells (n={x.size})",
        )
        axis.plot(
            trend_x,
            slope * trend_x + intercept,
            color="#252a30",
            linewidth=1.7,
            label="Ordinary least-squares trend",
        )
        if label == "Mean bias":
            axis.axhline(0, color="#59636f", linewidth=0.8, alpha=0.7)
        axis.set_title(
            f"{label}\nSlope {slope:+.1f} pp km⁻¹; Pearson r = {correlation_label}",
            fontsize=11,
        )
        axis.set_xlabel("MERRA-2 cell mean elevation (km)")
        axis.grid(color="#c7ccd1", linewidth=0.5, alpha=0.55)
        axis.legend(frameon=False, fontsize=8, loc="best")
    axes[0].set_ylabel("MERRA-2 − MODSCAG (percentage points)")
    axes[1].set_ylabel("Absolute error (percentage points)")
    figure.suptitle(
        "Elevation dependence of fractional snow-cover error\n"
        "Colorado, November 2022–May 2023 aggregate; USGS 3DEP cell-mean elevation",
        fontsize=13,
    )
    _save_figure(figure, output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plot November 2022–May 2023 MERRA-cell bias and MAE from validated "
            "monthly comparison checkpoints"
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
        default=Path("results/nov2022_may2023_spatial_bias_mae.png"),
    )
    parser.add_argument(
        "--elevation-output",
        type=Path,
        default=Path("results/nov2022_may2023_elevation_dependency.png"),
    )
    parser.add_argument(
        "--dem",
        type=Path,
        default=Path("data/usgs_3dep_coarse_dem.tif"),
        help="coarse EPSG:4326 elevation GeoTIFF used for contours",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = RunConfig()
    monthly_stats = load_analysis_months(args.checkpoint_dir, config)
    elevation = load_elevation_grid(args.dem, config)
    write_spatial_monthly_plot(monthly_stats, config, args.output, elevation)
    write_elevation_dependency_plot(
        monthly_stats, config, args.elevation_output, elevation
    )
    print(f"wrote {args.output}")
    print(f"wrote {args.elevation_output}")


if __name__ == "__main__":
    main()
