"""Spatial figures: pooled-climatology bias/MAE map and the wet/dry composite
NMB map with significance hatching.

Data-shaping (grid construction, masking) is kept separate from rendering so
tests can assert on arrays without needing to inspect a saved PNG.
"""

from __future__ import annotations

from dataclasses import dataclass

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np

from . import config, metrics, regrid, significance, terrain


def cells_to_grid(values: np.ndarray) -> np.ndarray:
    """Reshape a length-N_CELLS array (stable cell_id order) into
    (N_LAT_CELLS, N_LON_CELLS) for pcolormesh, using the same
    cell_id = lon_idx * N_LAT_CELLS + lat_idx convention as regrid.py.
    """
    grid = np.full((config.N_LAT_CELLS, config.N_LON_CELLS), np.nan)
    for cell_id in range(config.N_CELLS):
        lon_idx, lat_idx = divmod(cell_id, config.N_LAT_CELLS)
        grid[lat_idx, lon_idx] = values[cell_id]
    return grid


@dataclass(frozen=True)
class MonthlyDomainSeriesData:
    labels: list  # "YYYY-MM" strings, in chronological order
    bias_pp: np.ndarray
    mae_pp: np.ndarray


def build_monthly_domain_series(loaded: list) -> MonthlyDomainSeriesData:
    """Per-month domain-level bias/MAE for an arbitrary set of loaded
    checkpoints, sorted chronologically. Each month's domain stats are the
    combination of that month's 72 cell stats (sufficient statistics combined
    first, metrics derived once from the combination -- never an average of
    already-derived monthly bias/MAE values).
    """
    ordered = sorted(loaded, key=lambda lc: (lc.year, lc.month))
    labels = [f"{lc.year:04d}-{lc.month:02d}" for lc in ordered]
    domain_stats = [
        sum(lc.cell_stats, metrics.SufficientStats())
        for lc in ordered
    ]
    bias = np.array([metrics.bias_pp(s) for s in domain_stats])
    mae = np.array([metrics.mae_pp(s) for s in domain_stats])
    return MonthlyDomainSeriesData(labels=labels, bias_pp=bias, mae_pp=mae)


def render_monthly_domain_series_figure(data: MonthlyDomainSeriesData, out_path: str, title: str) -> None:
    fig, ax = plt.subplots(figsize=(10, 5), constrained_layout=True)
    x = np.arange(len(data.labels))
    ax.plot(x, data.bias_pp, marker="o", label="Bias (pp)")
    ax.plot(x, data.mae_pp, marker="s", label="MAE (pp)")
    ax.axhline(0.0, color="gray", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(data.labels, rotation=45, ha="right")
    ax.set_ylabel("Percentage points")
    ax.set_title(title)
    ax.legend()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


@dataclass(frozen=True)
class MonthlySpatialGridData:
    labels: list  # "YYYY-MM" strings, in chronological order
    bias_grids: list  # one masked (lat, lon) grid per month, same order as labels


def build_monthly_spatial_grid_data(loaded: list) -> MonthlySpatialGridData:
    """Per-month masked spatial bias grid for an arbitrary set of loaded
    checkpoints, sorted chronologically. Each month's mask and bias come from
    that month's own cell stats via `build_bias_mae_figure_data` -- the same
    low-snow mask and bias formula as the pooled spatial figure, just applied
    one month at a time instead of pooled across months.
    """
    ordered = sorted(loaded, key=lambda lc: (lc.year, lc.month))
    labels = [f"{lc.year:04d}-{lc.month:02d}" for lc in ordered]
    bias_grids = [build_bias_mae_figure_data(lc.cell_stats).bias_grid for lc in ordered]
    return MonthlySpatialGridData(labels=labels, bias_grids=bias_grids)


def render_monthly_spatial_grid_figure(
    data: MonthlySpatialGridData, out_path: str, title: str, n_cols: int = 3,
    dem: terrain.DemGrid | None = None,
) -> None:
    """One figure with a small-multiple panel per month, sharing a single
    color scale across all panels (per the shared-scale visual-inspection
    requirement -- panels are not independently normalized).
    """
    lon_edges = regrid.cell_lon_edges()
    lat_edges = regrid.cell_lat_edges()
    n = len(data.labels)
    n_rows = (n + n_cols - 1) // n_cols
    norm = terrain.diverging_norm(np.concatenate([g.ravel() for g in data.bias_grids]))

    fig, axes = plt.subplots(
        n_rows, n_cols, figsize=(3.2 * n_cols, 2.8 * n_rows), constrained_layout=True, squeeze=False
    )
    mesh = None
    for i in range(n_rows * n_cols):
        ax = axes[i // n_cols][i % n_cols]
        if i >= n:
            ax.axis("off")
            continue
        _draw_hillshade_background(ax, dem)
        mesh = ax.pcolormesh(
            lon_edges, lat_edges, data.bias_grids[i], cmap="RdBu_r", norm=norm, alpha=0.85, zorder=2
        )
        _draw_elevation_contours(ax, dem)
        ax.set_title(data.labels[i], fontsize=10)
        ax.set_xticks([])
        ax.set_yticks([])

    fig.suptitle(title)
    if mesh is not None:
        fig.colorbar(mesh, ax=axes, shrink=0.6, label="MERRA-2 minus MODSCAG bias (pp)")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def full_climatology_stats(loaded) -> list:
    """Pool every loaded checkpoint's cell stats across all 168 months --
    the full WY2010-2023 climatology used by the main bias/MAE map.
    """
    combined = [metrics.SufficientStats() for _ in range(config.N_CELLS)]
    for lc in loaded:
        for cell_id in range(config.N_CELLS):
            combined[cell_id] = combined[cell_id] + lc.cell_stats[cell_id]
    return combined


@dataclass(frozen=True)
class BiasMaeFigureData:
    bias_grid: np.ndarray
    mae_grid: np.ndarray
    composite_fsca_grid: np.ndarray
    excluded_grid: np.ndarray  # bool, True where masked out by the low-snow threshold


def build_bias_mae_figure_data(cell_stats: list) -> BiasMaeFigureData:
    fsca = np.array([metrics.composite_fsca(s) for s in cell_stats])
    bias = np.array([metrics.bias_pp(s) for s in cell_stats])
    mae = np.array([metrics.mae_pp(s) for s in cell_stats])

    excluded = np.isnan(fsca) | (fsca < config.COMPOSITE_FSCA_MASK_THRESHOLD)

    return BiasMaeFigureData(
        bias_grid=cells_to_grid(np.where(excluded, np.nan, bias)),
        mae_grid=cells_to_grid(np.where(excluded, np.nan, mae)),
        composite_fsca_grid=cells_to_grid(fsca),
        excluded_grid=cells_to_grid(excluded.astype(float)) > 0,
    )


def _domain_hillshade_extent(dem: terrain.DemGrid) -> tuple[np.ndarray, list]:
    cellsize_x_m = (dem.lon_edges[-1] - dem.lon_edges[0]) / (len(dem.lon_edges) - 1) * 111_320
    cellsize_y_m = (dem.lat_edges[-1] - dem.lat_edges[0]) / (len(dem.lat_edges) - 1) * 110_540
    shaded = terrain.hillshade(dem.elevation_m, cellsize_x_m, cellsize_y_m)
    extent = [dem.lon_edges[0], dem.lon_edges[-1], dem.lat_edges[0], dem.lat_edges[-1]]
    return shaded, extent


def _draw_hillshade_background(ax, dem: terrain.DemGrid | None) -> None:
    """Draw the hillshade under everything else (zorder=0). Call this before
    the data mesh; it is faint even unobstructed and gets washed out further
    under a semi-transparent mesh drawn on top of it.
    """
    if dem is None:
        return
    shaded, extent = _domain_hillshade_extent(dem)
    ax.imshow(shaded, cmap="gray", extent=extent, origin="lower", vmin=0, vmax=1, zorder=0)


def _draw_elevation_contours(ax, dem: terrain.DemGrid | None, zorder: int = 3) -> None:
    """Draw elevation contour lines above the data mesh (default zorder=3,
    above the mesh's zorder=2) so they stay legible instead of being washed
    out by the mesh's alpha blending.
    """
    if dem is None:
        return
    lon_mesh, lat_mesh = np.meshgrid(
        (dem.lon_edges[:-1] + dem.lon_edges[1:]) / 2, (dem.lat_edges[:-1] + dem.lat_edges[1:]) / 2
    )
    smoothed = terrain.smooth_for_contours(dem.elevation_m)
    ax.contour(
        lon_mesh, lat_mesh, smoothed, levels=terrain.contour_levels(),
        colors="black", linewidths=0.9, alpha=0.85, zorder=zorder,
    )


def render_bias_mae_figure(data: BiasMaeFigureData, out_path: str, dem: terrain.DemGrid | None = None) -> None:
    lon_edges = regrid.cell_lon_edges()
    lat_edges = regrid.cell_lat_edges()

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)

    bias_norm = terrain.diverging_norm(data.bias_grid)
    mae_norm = terrain.sequential_norm(data.mae_grid)

    for ax, grid, norm, cmap, title in (
        (axes[0], data.bias_grid, bias_norm, "RdBu_r", "MERRA-2 minus MODSCAG bias (pp)"),
        (axes[1], data.mae_grid, mae_norm, "YlOrRd", "MAE (pp)"),
    ):
        _draw_hillshade_background(ax, dem)
        mesh = ax.pcolormesh(lon_edges, lat_edges, grid, cmap=cmap, norm=norm, alpha=0.85, zorder=2)
        _draw_elevation_contours(ax, dem)
        fig.colorbar(mesh, ax=ax, shrink=0.85)
        ax.set_title(title)
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")

    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _add_hatches(ax, hatch_per_cell: np.ndarray, excluded_per_cell: np.ndarray, lon_edges, lat_edges) -> None:
    for cell_id in range(config.N_CELLS):
        if excluded_per_cell[cell_id] or not hatch_per_cell[cell_id]:
            continue
        lon_idx, lat_idx = divmod(cell_id, config.N_LAT_CELLS)
        rect = mpatches.Rectangle(
            (lon_edges[lon_idx], lat_edges[lat_idx]), config.LON_SPACING, config.LAT_SPACING,
            fill=False, hatch="///", edgecolor="black", linewidth=0, zorder=3,
        )
        ax.add_patch(rect)


@dataclass(frozen=True)
class WetDryFigureData:
    wet_grid: np.ndarray
    dry_grid: np.ndarray
    wet_excluded: np.ndarray  # length N_CELLS, bool
    dry_excluded: np.ndarray


def build_wet_dry_figure_data(
    sig: significance.WetDrySignificance, wet_fsca: np.ndarray, dry_fsca: np.ndarray
) -> WetDryFigureData:
    threshold = config.SIGNIFICANCE_FSCA_MASK_THRESHOLD
    wet_excluded = np.isnan(wet_fsca) | (wet_fsca < threshold)
    dry_excluded = np.isnan(dry_fsca) | (dry_fsca < threshold)

    return WetDryFigureData(
        wet_grid=cells_to_grid(np.where(wet_excluded, np.nan, sig.wet_composite_nmb)),
        dry_grid=cells_to_grid(np.where(dry_excluded, np.nan, sig.dry_composite_nmb)),
        wet_excluded=wet_excluded,
        dry_excluded=dry_excluded,
    )


def render_wet_dry_nmb_figure(
    data: WetDryFigureData, sig: significance.WetDrySignificance, out_path: str,
    dem: terrain.DemGrid | None = None,
) -> None:
    lon_edges = regrid.cell_lon_edges()
    lat_edges = regrid.cell_lat_edges()

    norm = terrain.shared_norm(data.wet_grid, data.dry_grid, diverging=True)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
    for ax, grid, hatch, excluded, title in (
        (axes[0], data.wet_grid, sig.wet_hatch, data.wet_excluded, "Wet-year composite NMB (%)"),
        (axes[1], data.dry_grid, sig.dry_hatch, data.dry_excluded, "Dry-year composite NMB (%)"),
    ):
        _draw_hillshade_background(ax, dem)
        mesh = ax.pcolormesh(lon_edges, lat_edges, grid, cmap="RdBu_r", norm=norm, alpha=0.85, zorder=2)
        _draw_elevation_contours(ax, dem)
        _add_hatches(ax, hatch, excluded, lon_edges, lat_edges)
        fig.colorbar(mesh, ax=ax, shrink=0.85)
        ax.set_title(title)
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")

    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


@dataclass(frozen=True)
class MonthlyWetDryGridData:
    months: list  # calendar month ints, Nov-May order (config.COMPOSITE_MONTHS)
    wet_grids: list  # one masked (lat, lon) grid per month
    dry_grids: list
    wet_excluded: list  # one length-N_CELLS bool array per month
    dry_excluded: list
    wet_hatch: list | None  # one length-N_CELLS bool array per month, or None if not applicable
    dry_hatch: list | None


_MONTH_NAMES = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


def build_monthly_wet_dry_nmb_data(
    index: significance.CheckpointIndex, months: tuple = config.COMPOSITE_MONTHS
) -> MonthlyWetDryGridData:
    """Per-month wet/dry composite NMB, masked and hatched exactly like the
    pooled significance figure (0.10 fSCA threshold, df=3 raw p<0.05 no-FDR),
    just windowed to one month at a time instead of pooled Nov-May.
    """
    per_month_sig = significance.monthly_wet_dry_significance(index, months)
    wet_fsca_by_month = significance.monthly_composite_metric(
        index, config.WET_WATER_YEARS, metrics.composite_fsca, months
    )
    dry_fsca_by_month = significance.monthly_composite_metric(
        index, config.DRY_WATER_YEARS, metrics.composite_fsca, months
    )
    threshold = config.SIGNIFICANCE_FSCA_MASK_THRESHOLD

    wet_grids, dry_grids, wet_excluded, dry_excluded, wet_hatch, dry_hatch = [], [], [], [], [], []
    for month in months:
        sig = per_month_sig[month]
        w_excl = np.isnan(wet_fsca_by_month[month]) | (wet_fsca_by_month[month] < threshold)
        d_excl = np.isnan(dry_fsca_by_month[month]) | (dry_fsca_by_month[month] < threshold)
        wet_grids.append(cells_to_grid(np.where(w_excl, np.nan, sig.wet_composite_nmb)))
        dry_grids.append(cells_to_grid(np.where(d_excl, np.nan, sig.dry_composite_nmb)))
        wet_excluded.append(w_excl)
        dry_excluded.append(d_excl)
        wet_hatch.append(sig.wet_hatch)
        dry_hatch.append(sig.dry_hatch)

    return MonthlyWetDryGridData(
        months=list(months), wet_grids=wet_grids, dry_grids=dry_grids,
        wet_excluded=wet_excluded, dry_excluded=dry_excluded,
        wet_hatch=wet_hatch, dry_hatch=dry_hatch,
    )


def build_monthly_wet_dry_nmae_data(
    index: significance.CheckpointIndex, months: tuple = config.COMPOSITE_MONTHS
) -> MonthlyWetDryGridData:
    """Per-month wet/dry composite NMAE, masked at the 0.05 composite-metric
    threshold (same mask as the pooled bias/MAE figure). Not significance
    -tested -- only NMB is hatched per the figure contract.
    """
    wet_nmae_by_month = significance.monthly_composite_metric(index, config.WET_WATER_YEARS, metrics.nmae, months)
    dry_nmae_by_month = significance.monthly_composite_metric(index, config.DRY_WATER_YEARS, metrics.nmae, months)
    wet_fsca_by_month = significance.monthly_composite_metric(
        index, config.WET_WATER_YEARS, metrics.composite_fsca, months
    )
    dry_fsca_by_month = significance.monthly_composite_metric(
        index, config.DRY_WATER_YEARS, metrics.composite_fsca, months
    )
    threshold = config.COMPOSITE_FSCA_MASK_THRESHOLD

    wet_grids, dry_grids, wet_excluded, dry_excluded = [], [], [], []
    for month in months:
        w_excl = np.isnan(wet_fsca_by_month[month]) | (wet_fsca_by_month[month] < threshold)
        d_excl = np.isnan(dry_fsca_by_month[month]) | (dry_fsca_by_month[month] < threshold)
        wet_grids.append(cells_to_grid(np.where(w_excl, np.nan, wet_nmae_by_month[month])))
        dry_grids.append(cells_to_grid(np.where(d_excl, np.nan, dry_nmae_by_month[month])))
        wet_excluded.append(w_excl)
        dry_excluded.append(d_excl)

    return MonthlyWetDryGridData(
        months=list(months), wet_grids=wet_grids, dry_grids=dry_grids,
        wet_excluded=wet_excluded, dry_excluded=dry_excluded,
        wet_hatch=None, dry_hatch=None,
    )


def build_monthly_wet_dry_fsca_data(
    index: significance.CheckpointIndex, months: tuple = config.COMPOSITE_MONTHS
) -> MonthlyWetDryGridData:
    """Per-month wet/dry composite MODIS fSCA -- unmasked (fSCA is the
    reference signal itself, never self-masked, matching
    `build_bias_mae_figure_data`'s composite_fsca_grid), not hatched.
    """
    wet_fsca_by_month = significance.monthly_composite_metric(
        index, config.WET_WATER_YEARS, metrics.composite_fsca, months
    )
    dry_fsca_by_month = significance.monthly_composite_metric(
        index, config.DRY_WATER_YEARS, metrics.composite_fsca, months
    )
    no_excl = np.zeros(config.N_CELLS, dtype=bool)

    wet_grids = [cells_to_grid(wet_fsca_by_month[month]) for month in months]
    dry_grids = [cells_to_grid(dry_fsca_by_month[month]) for month in months]

    return MonthlyWetDryGridData(
        months=list(months), wet_grids=wet_grids, dry_grids=dry_grids,
        wet_excluded=[no_excl for _ in months], dry_excluded=[no_excl for _ in months],
        wet_hatch=None, dry_hatch=None,
    )


def render_monthly_wet_dry_grid_figure(
    data: MonthlyWetDryGridData, out_path: str, title: str, cmap: str, diverging: bool,
    colorbar_label: str, dem: terrain.DemGrid | None = None,
) -> None:
    """One figure: months (Nov-May) as rows, wet/dry as the two columns,
    one shared color scale across every panel.
    """
    lon_edges = regrid.cell_lon_edges()
    lat_edges = regrid.cell_lat_edges()
    n_months = len(data.months)

    norm = terrain.shared_norm(
        *data.wet_grids, *data.dry_grids, diverging=diverging
    )

    fig, axes = plt.subplots(
        n_months, 2, figsize=(9, 2.6 * n_months), constrained_layout=True, squeeze=False
    )
    mesh = None
    for row, month in enumerate(data.months):
        for col, (grid, excluded, hatch_list) in enumerate((
            (data.wet_grids[row], data.wet_excluded[row], data.wet_hatch),
            (data.dry_grids[row], data.dry_excluded[row], data.dry_hatch),
        )):
            ax = axes[row][col]
            _draw_hillshade_background(ax, dem)
            mesh = ax.pcolormesh(lon_edges, lat_edges, grid, cmap=cmap, norm=norm, alpha=0.85, zorder=2)
            _draw_elevation_contours(ax, dem)
            if hatch_list is not None:
                _add_hatches(ax, hatch_list[row], excluded, lon_edges, lat_edges)
            ax.set_xticks([])
            ax.set_yticks([])
            if row == 0:
                ax.set_title("Wet" if col == 0 else "Dry")
            if col == 0:
                ax.set_ylabel(_MONTH_NAMES[month], fontsize=10, rotation=0, ha="right", va="center")

    fig.suptitle(title)
    if mesh is not None:
        fig.colorbar(mesh, ax=axes, shrink=0.6, label=colorbar_label)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
