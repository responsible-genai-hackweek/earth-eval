#!/usr/bin/env python
"""Exploratory analysis: how much of the pooled WY2010-2023 spatial bias
pattern lines up with subgrid terrain heterogeneity (a resolution-mismatch
proxy), versus how much bias varies year to year at the pooled-domain level.

Reads only already-produced artifacts -- the checked-in DEM fixture and the
final `results/water_year_2010_2023_{overall,pixel}_stats.csv` aggregates --
and reprocesses no daily or monthly checkpoints. Not part of the scientific
pipeline's public product; see README.md "Status" for what is public.

Two things this does NOT claim:
- Correlation with terrain heterogeneity is suggestive, not a controlled
  regridding experiment -- MERRA is never resampled to MODIS resolution here
  or anywhere else in this repository (scientific contract).
- The spatial/temporal variance split compares two different quantities
  (climatological per-cell bias vs pooled-domain per-year bias) as a rough
  magnitude comparison, not a formal ANOVA decomposition of one variance.

Usage: python scripts/resolution_attribution.py
"""

from __future__ import annotations

import csv
import json
import os
import sys

import numpy as np
from scipy import stats as sp_stats

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from fsca_eval import checkpoint, config, metrics, regrid, terrain  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(REPO_ROOT, "results")
DEM_PATH = os.path.join(REPO_ROOT, "tests", "fixtures", "domain_dem_3dep.tif")
OVERALL_STATS_PATH = os.path.join(RESULTS_DIR, config.OVERALL_STATS_FILENAME)
PIXEL_STATS_PATH = os.path.join(RESULTS_DIR, config.PIXEL_STATS_FILENAME)

OUT_CSV_PATH = os.path.join(RESULTS_DIR, "derived_resolution_attribution.csv")
OUT_FIGURE_PATH = os.path.join(RESULTS_DIR, "derived_resolution_attribution.png")


def _read_csv_rows(path: str) -> tuple[dict, list[dict]]:
    with open(path, "r", newline="") as f:
        first_line = f.readline()
        if not first_line.startswith("# METADATA "):
            raise ValueError(f"{path}: missing metadata header line")
        metadata = json.loads(first_line[len("# METADATA "):])
        reader = csv.DictReader(f)
        rows = list(reader)
    return metadata, rows


def _row_stats(row: dict) -> metrics.SufficientStats:
    return metrics.SufficientStats(
        sum_w=float(row["sum_w"]),
        sum_w_error=float(row["sum_w_error"]),
        sum_w_abs_error=float(row["sum_w_abs_error"]),
        sum_w_r=float(row["sum_w_r"]),
        valid_pixels=int(row["valid_pixels"]),
        expected_pixels=int(row["expected_pixels"]),
        observed_pixels=int(row["observed_pixels"]),
        n_cell_days=int(row["n_cell_days"]),
        n_days=int(row["n_days"]),
        n_calendar_days=int(row["n_calendar_days"]),
    )


def per_cell_terrain_heterogeneity() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bin the checked-in 3DEP DEM's pixel centers into the 72 MERRA cells and
    return (elevation_mean_m, elevation_std_m, elevation_range_m), each
    length N_CELLS, in stable cell_id order. Elevation std/range within a
    MERRA footprint is the subgrid terrain-heterogeneity proxy: a cell that
    is topographically uniform can be well represented by one coarse fSCA
    value, while a cell straddling a steep gradient cannot, regardless of
    which product is "wrong".
    """
    dem = terrain.LocalFileDemTransport(DEM_PATH).fetch(
        config.DOMAIN_LON_EDGE_MIN, config.DOMAIN_LAT_EDGE_MIN,
        config.DOMAIN_LON_EDGE_MAX, config.DOMAIN_LAT_EDGE_MAX,
        width_px=800, height_px=600,
    )
    lon_centers = (dem.lon_edges[:-1] + dem.lon_edges[1:]) / 2
    lat_centers = (dem.lat_edges[:-1] + dem.lat_edges[1:]) / 2
    lon_mesh, lat_mesh = np.meshgrid(lon_centers, lat_centers)

    cell_lon_edges = regrid.cell_lon_edges()
    cell_lat_edges = regrid.cell_lat_edges()
    lon_idx = np.searchsorted(cell_lon_edges, lon_mesh.ravel(), side="right") - 1
    lat_idx = np.searchsorted(cell_lat_edges, lat_mesh.ravel(), side="right") - 1
    in_domain = (lon_idx >= 0) & (lon_idx < config.N_LON_CELLS) & (lat_idx >= 0) & (lat_idx < config.N_LAT_CELLS)
    cell_id = np.where(in_domain, regrid.cell_id_from_indices(lon_idx, lat_idx), -1)

    elevation = dem.elevation_m.ravel()
    valid = in_domain & np.isfinite(elevation)

    mean_m = np.full(config.N_CELLS, np.nan)
    std_m = np.full(config.N_CELLS, np.nan)
    range_m = np.full(config.N_CELLS, np.nan)
    for cid in range(config.N_CELLS):
        pixels = elevation[valid & (cell_id == cid)]
        if pixels.size == 0:
            continue
        mean_m[cid] = pixels.mean()
        std_m[cid] = pixels.std()
        range_m[cid] = pixels.max() - pixels.min()

    return mean_m, std_m, range_m


def per_cell_pooled_climatology() -> list[metrics.SufficientStats]:
    """Combine the 12 already-computed `climatology_month` pixel_stats rows
    per cell into one WY2010-2023 pooled record per cell -- the same pooling
    `figures.full_climatology_stats` would produce from raw checkpoints, but
    read back from the final aggregate CSV instead of touching the 168
    monthly checkpoints again.
    """
    _, rows = _read_csv_rows(PIXEL_STATS_PATH)
    combined = [metrics.SufficientStats() for _ in range(config.N_CELLS)]
    for row in rows:
        if row["group_type"] != "climatology_month":
            continue
        cid = int(row["cell_id"])
        combined[cid] = combined[cid] + _row_stats(row)
    return combined


def annual_domain_bias() -> tuple[list[int], np.ndarray]:
    """Combine each water year's 12 wy_month domain rows (already in
    overall_stats.csv) into one domain-level bias_pp per water year --
    the interannual variability the wet/dry composite years are drawn from.
    """
    _, rows = _read_csv_rows(OVERALL_STATS_PATH)
    by_wy: dict[int, metrics.SufficientStats] = {}
    for row in rows:
        if row["group_type"] != "wy_month" or int(row["cell_id"]) != checkpoint.DOMAIN_CELL_ID:
            continue
        wy = int(row["water_year"])
        by_wy[wy] = by_wy.get(wy, metrics.SufficientStats()) + _row_stats(row)

    water_years = sorted(by_wy)
    bias = np.array([metrics.bias_pp(by_wy[wy]) for wy in water_years])
    return water_years, bias


def write_csv(cell_ids, lon, lat, elev_mean, elev_std, elev_range, bias, mae, nmb, nmae, fsca, excluded) -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    fieldnames = [
        "cell_id", "lon_center", "lat_center", "elevation_mean_m", "elevation_std_m",
        "elevation_range_m", "bias_pp", "mae_pp", "nmb_pct", "nmae_pct",
        "composite_fsca", "excluded_low_snow",
    ]
    with open(OUT_CSV_PATH, "w", newline="") as f:
        f.write(
            "# METADATA "
            + json.dumps(
                {
                    "description": (
                        "Exploratory: per-cell subgrid terrain heterogeneity from the "
                        "checked-in 3DEP DEM fixture vs. pooled WY2010-2023 climatology "
                        "bias/MAE/NMB/NMAE, read from existing final aggregates only."
                    ),
                    "source_dem": os.path.relpath(DEM_PATH, REPO_ROOT),
                    "source_pixel_stats": os.path.relpath(PIXEL_STATS_PATH, REPO_ROOT),
                    "low_snow_mask_threshold": config.COMPOSITE_FSCA_MASK_THRESHOLD,
                    "error_sign": config.ERROR_SIGN,
                },
                sort_keys=True,
            )
            + "\n"
        )
        writer = csv.writer(f)
        writer.writerow(fieldnames)
        for i in range(len(cell_ids)):
            writer.writerow([
                cell_ids[i], lon[i], lat[i], elev_mean[i], elev_std[i], elev_range[i],
                bias[i], mae[i], nmb[i], nmae[i], fsca[i], excluded[i],
            ])


def render_figure(elev_std, bias, excluded, water_years, annual_bias, r_value, p_value) -> None:
    import matplotlib.pyplot as plt

    included = ~excluded
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)

    ax = axes[0]
    ax.scatter(elev_std[included], bias[included], color="#4C72B0", edgecolor="white", s=60, zorder=3, label="Included cells")
    ax.scatter(elev_std[excluded], bias[excluded], color="#B0B0B0", edgecolor="white", s=60, zorder=2, label="Excluded (low snow)")
    if included.sum() >= 2:
        slope, intercept, *_ = sp_stats.linregress(elev_std[included], bias[included])
        xs = np.linspace(elev_std[included].min(), elev_std[included].max(), 50)
        ax.plot(xs, slope * xs + intercept, color="#C44E52", linewidth=1.5, zorder=4,
                 label=f"fit (r={r_value:.2f}, p={p_value:.3f})")
    ax.axhline(0.0, color="gray", linewidth=0.8, zorder=1)
    ax.set_xlabel("Within-cell elevation std. dev. (m)")
    ax.set_ylabel("Pooled climatology bias, MERRA-2 minus MODSCAG (pp)")
    ax.set_title("Terrain heterogeneity vs. spatial bias pattern")
    ax.legend(fontsize=8)

    ax = axes[1]
    spatial_var = np.nanvar(bias[included])
    temporal_var = np.nanvar(annual_bias)
    bars = ax.bar(
        ["Spatial\n(72 pooled cells)", "Temporal\n(14 annual domain values)"],
        [spatial_var, temporal_var],
        color=["#4C72B0", "#DD8452"],
    )
    for b, v in zip(bars, [spatial_var, temporal_var]):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.1f}", ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("Variance of bias_pp (pp$^2$)")
    ax.set_title("Spatial vs. temporal bias variance\n(rough magnitude comparison, not an ANOVA split)")

    fig.savefig(OUT_FIGURE_PATH, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    elev_mean, elev_std, elev_range = per_cell_terrain_heterogeneity()
    cell_stats = per_cell_pooled_climatology()

    lon = np.array([regrid.cell_id_to_center(cid)[0] for cid in range(config.N_CELLS)])
    lat = np.array([regrid.cell_id_to_center(cid)[1] for cid in range(config.N_CELLS)])
    bias = np.array([metrics.bias_pp(s) for s in cell_stats])
    mae = np.array([metrics.mae_pp(s) for s in cell_stats])
    nmb = np.array([metrics.nmb(s) for s in cell_stats])
    nmae = np.array([metrics.nmae(s) for s in cell_stats])
    fsca = np.array([metrics.composite_fsca(s) for s in cell_stats])
    excluded = np.isnan(fsca) | (fsca < config.COMPOSITE_FSCA_MASK_THRESHOLD)

    included = ~excluded & np.isfinite(elev_std) & np.isfinite(bias)
    r_value, p_value = np.nan, np.nan
    if included.sum() >= 3:
        r_value, p_value = sp_stats.pearsonr(elev_std[included], bias[included])

    water_years, annual_bias = annual_domain_bias()

    write_csv(
        list(range(config.N_CELLS)), lon, lat, elev_mean, elev_std, elev_range,
        bias, mae, nmb, nmae, fsca, excluded,
    )
    render_figure(elev_std, bias, excluded, water_years, annual_bias, r_value, p_value)

    n_included = int(included.sum())
    print(f"Cells included (composite fSCA >= {config.COMPOSITE_FSCA_MASK_THRESHOLD}): {n_included} of {config.N_CELLS}")
    print(f"Pearson r (elevation std vs bias_pp, included cells): {r_value:.3f} (p={p_value:.4f}, R^2={r_value**2:.3f})")
    print(f"Spatial variance of pooled per-cell bias_pp (included cells): {np.nanvar(bias[included]):.2f} pp^2")
    print(f"Temporal variance of pooled-domain annual bias_pp ({len(water_years)} water years): {np.nanvar(annual_bias):.2f} pp^2")
    print(f"Wrote {OUT_CSV_PATH}")
    print(f"Wrote {OUT_FIGURE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
