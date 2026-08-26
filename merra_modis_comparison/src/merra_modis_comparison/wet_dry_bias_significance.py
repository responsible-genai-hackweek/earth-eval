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

from .bias_significance import two_sided_ttest
from .checkpoints import checkpoint_path, load_month_checkpoint
from .composite_plotting import (
    COMPOSITE_GROUPS,
    COMPOSITE_MONTHS,
    calendar_period_for_water_year,
)
from .config import RunConfig
from .metrics import StatsBlock
from .modis_fsca_stats import (
    ModisStatsBlock,
    load_modis_checkpoint,
    modis_checkpoint_path,
)
from .spatial_plotting import (
    ELEVATION_CONTOURS_M,
    METRIC_LAYER_ALPHA,
    ElevationGrid,
    _save_figure,
    _terrain_extent,
    hillshade_grid,
    load_elevation_grid,
)


TEST_ALPHA = 0.05
MINIMUM_MODIS_FSCA_FRACTION = 0.10


@dataclass(frozen=True)
class WetDryBiasResult:
    group: str
    water_years: tuple[int, ...]
    month: int
    label: str
    normalized_mean_bias_pct: np.ndarray
    mean_annual_nmb_pct: np.ndarray
    modis_fsca_pct: np.ndarray
    masked_low_modis_fsca: np.ndarray
    t_statistic: np.ndarray
    p_value: np.ndarray
    n_years: np.ndarray
    degrees_of_freedom: np.ndarray


def _validate_pair(comparison: StatsBlock, modis: ModisStatsBlock) -> None:
    if comparison.n_cells != modis.n_cells:
        raise ValueError("comparison and MODIS statistics use different grids")
    if not np.array_equal(
        comparison.sum_w[: comparison.n_cells], modis.sum_w[: modis.n_cells]
    ) or not np.array_equal(
        comparison.n_days[: comparison.n_cells], modis.n_days[: modis.n_cells]
    ):
        raise ValueError(
            "normalized bias requires exactly matched comparison and MODIS support"
        )


def calculate_group_month_result(
    group: str,
    water_years: tuple[int, ...],
    month: int,
    label: str,
    yearly_pairs: list[tuple[int, StatsBlock, ModisStatsBlock]],
    minimum_modis_fsca_fraction: float = MINIMUM_MODIS_FSCA_FRACTION,
) -> WetDryBiasResult:
    if not 0 < minimum_modis_fsca_fraction < 1:
        raise ValueError("minimum MODIS fSCA fraction must lie between zero and one")
    if tuple(year for year, _, _ in yearly_pairs) != water_years:
        raise ValueError("yearly statistics are not in the requested water-year order")
    n_cells = yearly_pairs[0][1].n_cells
    annual_nmb = np.full((len(yearly_pairs), n_cells), np.nan, dtype=np.float64)
    pooled_error = np.zeros(n_cells, dtype=np.float64)
    pooled_modis = np.zeros(n_cells, dtype=np.float64)
    pooled_weight = np.zeros(n_cells, dtype=np.float64)

    for row, (_, comparison, modis) in enumerate(yearly_pairs):
        _validate_pair(comparison, modis)
        if comparison.n_cells != n_cells:
            raise ValueError("yearly statistics use inconsistent grids")
        denominator = modis.sum_w_fsca[:n_cells]
        annual_nmb[row] = np.divide(
            100.0 * comparison.sum_w_error[:n_cells],
            denominator,
            out=np.full(n_cells, np.nan, dtype=np.float64),
            where=denominator > 0,
        )
        pooled_error += comparison.sum_w_error[:n_cells]
        pooled_modis += denominator
        pooled_weight += modis.sum_w[:n_cells]

    normalized_mean_bias = np.divide(
        100.0 * pooled_error,
        pooled_modis,
        out=np.full(n_cells, np.nan, dtype=np.float64),
        where=pooled_modis > 0,
    )
    modis_fsca_pct = np.divide(
        100.0 * pooled_modis,
        pooled_weight,
        out=np.full(n_cells, np.nan, dtype=np.float64),
        where=pooled_weight > 0,
    )
    minimum_pct = 100.0 * minimum_modis_fsca_fraction
    low_modis = ~np.isfinite(modis_fsca_pct) | (modis_fsca_pct < minimum_pct)

    test = two_sided_ttest(annual_nmb)
    p_value = test.p_value.copy()
    p_value[low_modis] = np.nan
    mean_annual_nmb = test.mean_bias_pp.copy()
    return WetDryBiasResult(
        group=group,
        water_years=water_years,
        month=month,
        label=label,
        normalized_mean_bias_pct=normalized_mean_bias,
        mean_annual_nmb_pct=mean_annual_nmb,
        modis_fsca_pct=modis_fsca_pct,
        masked_low_modis_fsca=low_modis,
        t_statistic=test.t_statistic,
        p_value=p_value,
        n_years=test.n_years,
        degrees_of_freedom=test.degrees_of_freedom,
    )


def load_wet_dry_results(
    comparison_directory: Path,
    modis_directory: Path,
    config: RunConfig,
    workers: int = 16,
) -> dict[str, list[WetDryBiasResult]]:
    tasks = [
        (group, water_years, month_index, water_year)
        for group, water_years in COMPOSITE_GROUPS
        for month_index, _ in enumerate(COMPOSITE_MONTHS)
        for water_year in water_years
    ]

    def load_one(
        task: tuple[str, tuple[int, ...], int, int]
    ) -> tuple[str, int, int, StatsBlock, ModisStatsBlock]:
        group, _, month_index, water_year = task
        month = COMPOSITE_MONTHS[month_index][0]
        year, calendar_month = calendar_period_for_water_year(water_year, month)
        comparison_path = checkpoint_path(
            comparison_directory, year, calendar_month
        )
        modis_path = modis_checkpoint_path(modis_directory, year, calendar_month)
        if not comparison_path.exists():
            raise FileNotFoundError(f"missing comparison checkpoint {comparison_path}")
        if not modis_path.exists():
            raise FileNotFoundError(f"missing MODIS checkpoint {modis_path}")
        comparison = load_month_checkpoint(
            comparison_path, year, calendar_month, config
        )
        modis = load_modis_checkpoint(modis_path, year, calendar_month, config)
        _validate_pair(comparison, modis)
        return group, month_index, water_year, comparison, modis

    loaded: dict[tuple[str, int], list[tuple[int, StatsBlock, ModisStatsBlock]]] = {
        (group, month_index): []
        for group, _ in COMPOSITE_GROUPS
        for month_index, _ in enumerate(COMPOSITE_MONTHS)
    }
    with ThreadPoolExecutor(max_workers=min(workers, len(tasks))) as executor:
        for group, month_index, water_year, comparison, modis in executor.map(
            load_one, tasks
        ):
            loaded[(group, month_index)].append(
                (water_year, comparison, modis)
            )

    results: dict[str, list[WetDryBiasResult]] = {
        group: [] for group, _ in COMPOSITE_GROUPS
    }
    for group, water_years in COMPOSITE_GROUPS:
        for month_index, (month, label) in enumerate(COMPOSITE_MONTHS):
            pairs = sorted(loaded[(group, month_index)], key=lambda item: item[0])
            results[group].append(
                calculate_group_month_result(
                    group,
                    water_years,
                    month,
                    label,
                    pairs,
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
        linewidths=0.45,
        alpha=0.52,
        zorder=2,
    )
    axis.clabel(
        contours,
        levels=ELEVATION_CONTOURS_M,
        fmt={2000: "2,000 m", 3000: "3,000 m"},
        fontsize=5.4,
        inline=True,
        inline_spacing=2,
        manual=[(-108.0, 37.2), (-106.6, 39.0)],
    )


def _add_cell_rectangle(
    axis: plt.Axes,
    grid,
    slot: int,
    *,
    facecolor: str,
    edgecolor,
    hatch: str | None,
    zorder: float,
) -> None:
    row, column = divmod(int(slot), len(grid.lons))
    axis.add_patch(
        Rectangle(
            (grid.lon_edges[column], grid.lat_edges[row]),
            grid.lon_edges[column + 1] - grid.lon_edges[column],
            grid.lat_edges[row + 1] - grid.lat_edges[row],
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=0.0 if hatch else 0.35,
            hatch=hatch,
            zorder=zorder,
        )
    )


def write_wet_dry_plot(
    results: dict[str, list[WetDryBiasResult]],
    config: RunConfig,
    output: Path,
    elevation: ElevationGrid,
) -> None:
    expected_groups = {group for group, _ in COMPOSITE_GROUPS}
    if set(results) != expected_groups or any(
        len(results[group]) != 7 for group in expected_groups
    ):
        raise ValueError("wet/dry results must contain seven months per group")
    grid = config.target_grid
    unmasked_values = np.concatenate(
        [
            result.normalized_mean_bias_pct[~result.masked_low_modis_fsca]
            for group, _ in COMPOSITE_GROUPS
            for result in results[group]
        ]
    )
    bias_limit = float(np.nanmax(np.abs(unmasked_values)))
    if not np.isfinite(bias_limit) or bias_limit <= 0:
        raise ValueError("normalized mean bias contains no usable values")
    bias_limit = float(np.ceil(bias_limit / 10.0) * 10.0)

    figure, axes = plt.subplots(
        7,
        2,
        figsize=(5.0, 15.2),
        sharex=True,
        sharey=True,
        constrained_layout=True,
    )
    figure.get_layout_engine().set(
        w_pad=0.012, h_pad=0.012, wspace=0.012, hspace=0.012
    )
    relief = hillshade_grid(elevation)
    terrain_extent = _terrain_extent(elevation)
    geographic_aspect = 1.0 / np.cos(np.deg2rad(float(np.mean(grid.lats))))
    base_colormap = plt.get_cmap("RdBu_r")
    colormap = ListedColormap(
        base_colormap(np.linspace(0.12, 0.88, 256)),
        name="trimmed_RdBu_r",
    )
    normalization = TwoSlopeNorm(
        vmin=-bias_limit,
        vcenter=0.0,
        vmax=bias_limit,
    )
    image = None
    for row, (_, month_label) in enumerate(COMPOSITE_MONTHS):
        for column, (group, water_years) in enumerate(COMPOSITE_GROUPS):
            result = results[group][row]
            axis = axes[row, column]
            _draw_terrain(axis, elevation, relief, terrain_extent)
            image = axis.pcolormesh(
                grid.lon_edges,
                grid.lat_edges,
                result.normalized_mean_bias_pct.reshape(grid.shape),
                cmap=colormap,
                norm=normalization,
                shading="flat",
                edgecolors="#59636f",
                linewidth=0.32,
                alpha=METRIC_LAYER_ALPHA,
                zorder=1,
            )
            significant = np.isfinite(result.p_value) & (
                result.p_value < TEST_ALPHA
            )
            for slot in np.flatnonzero(significant):
                _add_cell_rectangle(
                    axis,
                    grid,
                    int(slot),
                    facecolor="none",
                    edgecolor=(0.12, 0.14, 0.16, 0.72),
                    hatch="////",
                    zorder=3,
                )
            for slot in np.flatnonzero(result.masked_low_modis_fsca):
                _add_cell_rectangle(
                    axis,
                    grid,
                    int(slot),
                    facecolor="#000000",
                    edgecolor="#252525",
                    hatch=None,
                    zorder=4,
                )
            usable_count = int(np.count_nonzero(~result.masked_low_modis_fsca))
            significant_count = int(np.count_nonzero(significant))
            years_label = ", ".join(str(year) for year in water_years)
            heading = (
                f"{group} WYs: {years_label}\n" if row == 0 else ""
            )
            axis.set_title(
                f"{heading}p<0.05: {significant_count}/{usable_count}",
                fontsize=8.4,
            )
            axis.set_aspect(geographic_aspect)
            axis.set_xlim(grid.lon_edges[0], grid.lon_edges[-1])
            axis.set_ylim(grid.lat_edges[0], grid.lat_edges[-1])
            axis.set_yticks((37, 38, 39, 40, 41))
            axis.tick_params(labelsize=7.5)
            axis.set_anchor("E" if column == 0 else "W")
        axes[row, 0].set_ylabel(f"{month_label}\nLatitude (°N)")

    for axis in axes[-1]:
        axis.set_xlabel("Longitude (°E)")
        axis.set_xticks((-109, -108, -107, -106, -105, -104))
    if image is None:
        raise RuntimeError("wet/dry significance plot created no panels")
    figure.colorbar(
        image,
        ax=axes,
        location="bottom",
        shrink=0.78,
        pad=0.008,
        label="Normalized mean bias: 100 × Σw(MERRA-2 − MODSCAG) / Σw(MODSCAG) (%)",
    )
    figure.suptitle(
        "Wet- and dry-year normalized mean fSCA bias with two-sided significance\n"
        "Hatching: uncorrected two-sided p<0.05; black: pooled MODIS fSCA <0.10",
        fontsize=10.8,
    )
    _save_figure(figure, output)


CSV_FIELDS = (
    "group",
    "water_years",
    "month",
    "month_number",
    "slot",
    "cell_id",
    "merra_latitude",
    "merra_longitude",
    "pooled_modis_fsca_fraction",
    "masked_modis_fsca_below_0_1",
    "normalized_mean_bias_pct",
    "mean_annual_nmb_pct",
    "n_water_years",
    "degrees_of_freedom",
    "t_statistic",
    "two_sided_p_value",
    "two_sided_p_lt_0_05",
)


def write_wet_dry_csv(
    results: dict[str, list[WetDryBiasResult]],
    config: RunConfig,
    output: Path,
) -> None:
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
            for group, water_years in COMPOSITE_GROUPS:
                for result in results[group]:
                    for slot in range(config.target_grid.size):
                        metadata = config.target_grid.cell_metadata(slot)
                        masked = bool(result.masked_low_modis_fsca[slot])
                        writer.writerow(
                            {
                                "group": group,
                                "water_years": ",".join(map(str, water_years)),
                                "month": result.label,
                                "month_number": result.month,
                                "slot": slot,
                                "cell_id": metadata["cell_id"],
                                "merra_latitude": metadata["merra_latitude"],
                                "merra_longitude": metadata["merra_longitude"],
                                "pooled_modis_fsca_fraction": (
                                    result.modis_fsca_pct[slot] / 100.0
                                ),
                                "masked_modis_fsca_below_0_1": masked,
                                "normalized_mean_bias_pct": (
                                    result.normalized_mean_bias_pct[slot]
                                ),
                                "mean_annual_nmb_pct": (
                                    result.mean_annual_nmb_pct[slot]
                                ),
                                "n_water_years": result.n_years[slot],
                                "degrees_of_freedom": (
                                    result.degrees_of_freedom[slot]
                                ),
                                "t_statistic": (
                                    "" if masked else result.t_statistic[slot]
                                ),
                                "two_sided_p_value": (
                                    "" if masked else result.p_value[slot]
                                ),
                                "two_sided_p_lt_0_05": (
                                    False
                                    if masked
                                    else result.p_value[slot] < TEST_ALPHA
                                ),
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
            "Plot wet/dry normalized mean bias with two-sided cellwise "
            "water-year t-tests"
        )
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=Path("results/water_year_2010_2023_monthly_checkpoints"),
    )
    parser.add_argument(
        "--modis-checkpoint-dir",
        type=Path,
        default=Path("results/wet_dry_modis_fsca_monthly_checkpoints"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "results/wet_dry_pixel_normalized_bias_two_sided_ttest.png"
        ),
    )
    parser.add_argument(
        "--stats-output",
        type=Path,
        default=Path(
            "results/wet_dry_pixel_normalized_bias_two_sided_ttest.csv"
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
    results = load_wet_dry_results(
        args.checkpoint_dir,
        args.modis_checkpoint_dir,
        config,
        workers=args.workers,
    )
    elevation = load_elevation_grid(args.dem, config)
    write_wet_dry_plot(results, config, args.output, elevation)
    write_wet_dry_csv(results, config, args.stats_output)
    print(f"wrote {args.output}")
    print(f"wrote {args.stats_output}")


if __name__ == "__main__":
    main()
