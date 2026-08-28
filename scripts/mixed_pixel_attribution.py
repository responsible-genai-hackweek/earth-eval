#!/usr/bin/env python
"""Exploratory follow-up to resolution_attribution.py: does the pooled bias
track how much snow a cell typically carries?

Original motivation: fine 500 m MODSCAG pixels can resolve a coarse MERRA
cell that is partly snow-covered and partly bare, so disagreement might be
worst in cells that are often in a *mixed* snow/bare state -- proxied by
fsca*(1-fsca), which peaks at composite fSCA=0.5. In this domain every
included cell has composite fSCA < 0.5 (range ~0.05-0.49), where
fsca*(1-fsca) is monotonically increasing in fsca -- so over this domain's
actual range it is nearly indistinguishable from raw fSCA itself, and cannot
isolate "mixed-pixel-ness" from "how much snow is present." Reported here
instead as the more honest, unconfounded quantity: raw composite fSCA vs.
bias_pp.

This correlation cannot by itself distinguish a resolution/mixed-pixel
mechanism from other explanations that also scale with snow amount (e.g. a
MERRA depletion-curve or snow-physics effect independent of pixel size). See
results/resolution_attribution_slides.pdf slide 3 for the caveated writeup.

This is a proxy for subpixel heterogeneity, not a direct measurement: the
saved sufficient statistics (pixel_stats.csv) hold sum_w_r (sum of weighted
MODSCAG fraction) but not a sum of squares, so within-cell fine-pixel
variance cannot be reconstructed from already-produced aggregates. A direct
test would require touching daily granules again, which is out of scope here.

Reads only results/derived_resolution_attribution.csv, itself produced by
scripts/resolution_attribution.py from already-final aggregates. Reprocesses
nothing.

Usage: python scripts/mixed_pixel_attribution.py
"""

from __future__ import annotations

import csv
import json
import os

import numpy as np
from scipy import stats as sp_stats

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(REPO_ROOT, "results")
IN_CSV_PATH = os.path.join(RESULTS_DIR, "derived_resolution_attribution.csv")
OUT_FIGURE_PATH = os.path.join(RESULTS_DIR, "derived_mixed_pixel_attribution.png")


def read_derived_csv() -> tuple[dict, list[dict]]:
    with open(IN_CSV_PATH, "r", newline="") as f:
        first_line = f.readline()
        if not first_line.startswith("# METADATA "):
            raise ValueError(f"{IN_CSV_PATH}: missing metadata header line")
        metadata = json.loads(first_line[len("# METADATA "):])
        rows = list(csv.DictReader(f))
    return metadata, rows


def render_figure(fsca, bias, excluded, r_value, p_value) -> None:
    import matplotlib.pyplot as plt

    included = ~excluded
    fig, ax = plt.subplots(figsize=(6, 5), constrained_layout=True)

    ax.scatter(fsca[included], bias[included], color="#4C72B0", edgecolor="white",
               s=60, zorder=3, label="Included cells")
    ax.scatter(fsca[excluded], bias[excluded], color="#B0B0B0", edgecolor="white",
               s=60, zorder=2, label="Excluded (low snow)")
    if included.sum() >= 2:
        slope, intercept, *_ = sp_stats.linregress(fsca[included], bias[included])
        xs = np.linspace(fsca[included].min(), fsca[included].max(), 50)
        ax.plot(xs, slope * xs + intercept, color="#C44E52", linewidth=1.5, zorder=4,
                label=f"fit (r={r_value:.2f}, p={p_value:.3g})")
    ax.axhline(0.0, color="gray", linewidth=0.8, zorder=1)
    ax.set_xlabel("Composite MODSCAG fSCA (climatology mean, per cell)")
    ax.set_ylabel("Pooled climatology bias, MERRA-2 minus MODSCAG (pp)")
    ax.set_title("Snow amount vs. spatial bias pattern")
    ax.legend(fontsize=8)

    fig.savefig(OUT_FIGURE_PATH, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    _, rows = read_derived_csv()

    cell_id = np.array([int(r["cell_id"]) for r in rows])
    fsca = np.array([float(r["composite_fsca"]) for r in rows])
    bias = np.array([float(r["bias_pp"]) for r in rows])
    excluded = np.array([r["excluded_low_snow"] == "True" for r in rows])

    included = ~excluded & np.isfinite(fsca) & np.isfinite(bias)
    r_value, p_value = np.nan, np.nan
    if included.sum() >= 3:
        r_value, p_value = sp_stats.pearsonr(fsca[included], bias[included])

    mixed_index = fsca * (1.0 - fsca)
    r_mixed, p_mixed = np.nan, np.nan
    if included.sum() >= 3:
        r_mixed, p_mixed = sp_stats.pearsonr(mixed_index[included], bias[included])

    render_figure(fsca, bias, excluded, r_value, p_value)

    n_included = int(included.sum())
    print(f"Cells included: {n_included} of {len(cell_id)}")
    print(f"fSCA range over included cells: [{fsca[included].min():.3f}, {fsca[included].max():.3f}] "
          f"(all < 0.5 -> fsca*(1-fsca) is monotonic in fsca here, not a clean mixed-pixel isolate)")
    print(f"Pearson r (composite fSCA vs bias_pp, included cells): {r_value:.3f} "
          f"(p={p_value:.4g}, R^2={r_value**2:.3f})")
    print(f"Pearson r (fsca*(1-fsca) vs bias_pp, included cells, confounded): {r_mixed:.3f} "
          f"(p={p_mixed:.4g}, R^2={r_mixed**2:.3f})")
    print(f"Wrote {OUT_FIGURE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
