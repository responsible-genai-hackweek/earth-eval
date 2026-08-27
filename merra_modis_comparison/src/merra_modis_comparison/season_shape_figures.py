"""Figures for the season-shape comparison against SNOTEL.

Separate from :mod:`figures`, which owns the magnitude and ranking panels, so
neither file grows past the point where it can be read in one sitting. The
palette, the style contract and ``save`` are shared from there; only the layouts
are local.

Two conventions inherited from the domain skill and worth restating because both
were got wrong first:

- **The observation is the reference, not a third opinion.** SNOTEL is drawn
  heaviest, in a strong neutral no model uses, and it leads every legend.
- **Narrative belongs in the caption.** Nothing on these canvases explains what
  the panel means, how a member was normalised, or what the result is. Titles
  carry domain, subject and record period; legends carry identity; that is all.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter

from .figures import (
    ERA5_COLOUR,
    GRID,
    INK,
    INK_SECONDARY,
    MERRA2_COLOUR,
    SURFACE,
    beeswarm_offsets,
    figure_title,
    panel_label,
    quiet_legend,
    save,
    style_axes,
)
from .seasonshape import METRICS

__all__ = ["season_shape", "season_turning_points", "snotel_timing_by_elevation"]

#: The observation's identity. A strong neutral no model uses, so that "heaviest
#: mark" and "reference" are the same statement.
OBSERVATION_COLOUR = INK
#: A reference rule is not a model and must not borrow a model's identity hue.
REFERENCE_RULE = INK_SECONDARY

#: Legend and row order: reference first, then the models in the fixed pair
#: order this project uses everywhere. Draw order is chosen separately, by which
#: mark must stay on top; the two are not the same and neither inherits the other.
SOURCE_ORDER = ("SNOTEL", "ERA5", "MERRA-2")
SOURCE_COLOUR = {
    "SNOTEL": OBSERVATION_COLOUR, "ERA5": ERA5_COLOUR, "MERRA-2": MERRA2_COLOUR,
}
METRIC_LABEL = {
    "onset": "Onset", "centroid": "Centroid", "peak": "Peak", "melt_out": "Melt-Out",
}
_MONTHS = ((0, "Oct"), (31, "Nov"), (61, "Dec"), (92, "Jan"), (123, "Feb"),
           (151, "Mar"), (182, "Apr"), (212, "May"), (243, "Jun"), (273, "Jul"))


def _month_axis(ax, low: float, high: float) -> None:
    ax.set_xticks([day for day, _ in _MONTHS])
    ax.set_xticklabels([name for _, name in _MONTHS])
    ax.set_xlim(low, high)


def season_shape(
    curves: dict[str, tuple[np.ndarray, np.ndarray]], path: Path, *, period: str
) -> Path:
    """Normalised median season curve per source, on a water-year axis.

    ``curves`` maps source name to ``(day, fraction)`` from
    :func:`seasonshape.normalised_composite`, which has already rescaled each
    composite to its own maximum. Every curve therefore peaks at exactly 1.0 and
    the axis label is true.
    """
    fig, ax = plt.subplots(figsize=(11.0, 6.0))
    style_axes(ax)
    # Draw weakest first so the reference finishes on top of both models.
    for name in reversed(SOURCE_ORDER):
        day, fraction = curves[name]
        heaviest = name == "SNOTEL"
        ax.plot(day, fraction, color=SOURCE_COLOUR[name],
                linewidth=3.6 if heaviest else 2.4, zorder=6 if heaviest else 4,
                label=name, solid_capstyle="round")
    ax.set_ylabel("Fraction of Peak", color=INK)
    ax.set_ylim(0, 1.02)
    _month_axis(ax, 0, 288)
    handles, labels = ax.get_legend_handles_labels()
    order = [labels.index(name) for name in SOURCE_ORDER]
    quiet_legend(ax, loc="upper left", handles=[handles[i] for i in order],
                 labels=[labels[i] for i in order])
    figure_title(fig, f"Colorado Rocky Mountains   Season Shape   {period}")
    return save(fig, path)


def season_turning_points(
    per_year: dict[str, dict[str, np.ndarray]], path: Path, *, period: str
) -> Path:
    """Four turning points, one point per water year, three sources each.

    ``per_year[source][metric]`` is one value per water year — the median across
    band cells, or across stations. Per-member points are deliberately not shown:
    at thousands of members a strip saturates into a solid slab that carries
    nothing.
    """
    fig, ax = plt.subplots(figsize=(11.5, 7.0))
    style_axes(ax, grid_axis="x")
    weights = {"SNOTEL": (3.6, 46, 0.78), "ERA5": (2.8, 32, 0.62),
               "MERRA-2": (2.8, 32, 0.62)}
    positions, labels = [], []
    for index, metric in enumerate(METRICS):
        top = (len(METRICS) - 1 - index) * 3.3
        for row, name in enumerate(SOURCE_ORDER):
            y = top + (1.0 - row)
            values = np.asarray(per_year[name][metric], dtype=float)
            values = values[np.isfinite(values)]
            line_width, size, alpha = weights[name]
            colour = SOURCE_COLOUR[name]
            ax.scatter(values, y + beeswarm_offsets(values, 2.6, 0.095), s=size,
                       color=colour, alpha=alpha, edgecolor="none", zorder=3,
                       label=name if index == 0 else None)
            median = float(np.median(values))
            ax.plot([median, median], [y - 0.5, y + 0.5], color=SURFACE,
                    linewidth=line_width + 3.0, zorder=4)
            ax.plot([median, median], [y - 0.5, y + 0.5], color=colour,
                    linewidth=line_width, zorder=5)
        positions.append(top)
        labels.append(METRIC_LABEL[metric])
    ax.set_yticks(positions)
    ax.set_yticklabels(labels, fontsize=12.5, color=INK)
    ax.set_ylim(-1.9, (len(METRICS) - 1) * 3.3 + 1.9)
    _month_axis(ax, 20, 266)
    quiet_legend(ax, loc="upper right", scatterpoints=1, markerscale=1.3)
    figure_title(fig, f"Colorado Rocky Mountains   Season Turning Points   {period}")
    return save(fig, path)


def snotel_timing_by_elevation(
    elevation_ft: np.ndarray,
    per_station: dict[str, np.ndarray],
    gradients: dict[str, tuple[float, float, float]],
    band_ft: float,
    path: Path,
) -> Path:
    """Each timing metric against station elevation, with the fitted gradient.

    The band's mean cell elevation is ruled so the correction can be inspected
    rather than trusted — and so a reader can see for themselves that it falls
    inside the fitted span, making it an interpolation.
    """
    fig, axes = plt.subplots(2, 2, figsize=(11.0, 8.4))
    elevation_ft = np.asarray(elevation_ft, dtype=float)
    span = np.linspace(elevation_ft.min(), elevation_ft.max(), 50)
    for ax, metric in zip(axes.ravel(), METRICS):
        style_axes(ax)
        values = np.asarray(per_station[metric], dtype=float)
        slope, intercept, _ = gradients[metric]
        ax.scatter(elevation_ft, values, s=30, color=INK, alpha=0.42,
                   edgecolor="none", zorder=3)
        ax.plot(span, slope * span + intercept, color=INK, linewidth=2.0, zorder=5)
        ax.axvline(band_ft, color=REFERENCE_RULE, linewidth=1.8,
                   linestyle=(0, (4, 2)), zorder=4)
        ax.set_yticks([day for day, _ in _MONTHS])
        ax.set_yticklabels([name for _, name in _MONTHS])
        finite = values[np.isfinite(values)]
        ax.set_ylim(finite.min() - 8, finite.max() + 8)
        ax.set_xlabel("Station Elevation   Feet", color=INK)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
        rate = f"{slope * 1000:+.1f}".replace("-", "−")
        panel_label(ax, f"{METRIC_LABEL[metric]}    {rate} Days per 1,000 Feet")
    axes.ravel()[0].annotate(
        f"Band Mean\n{band_ft:,.0f} ft", xy=(band_ft, 0.06),
        xycoords=("data", "axes fraction"), xytext=(6, 0),
        textcoords="offset points", color=REFERENCE_RULE, fontsize=10.5,
        va="bottom", ha="left",
    )
    figure_title(fig, "Colorado Rocky Mountains   SNOTEL Timing by Elevation", y=1.0)
    fig.subplots_adjust(hspace=0.42, wspace=0.24)
    return save(fig, path)
