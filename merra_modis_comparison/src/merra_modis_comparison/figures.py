"""Presentation figures for the snowpack comparison.

Colour follows the job it does. The two models are a *categorical* pair, fixed
in order and validated for colour-vision deficiency separation (worst adjacent
pair dE 31.0 protan, 37.3 normal). Water-year anomalies are *diverging*, so they
use those same two hues as poles with a neutral grey midpoint - orange for dry
and blue for wet, which is also the conventional reading for snow.

Every figure is single-axis. Identity is never carried by colour alone: series
are direct-labelled or legended, and the extreme years are annotated.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.patheffects as path_effects
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns

# seaborn sets the style - spines, grid weight, tick treatment, type sizing.
# It does NOT set the colours: those come from the validated palette below,
# which passed colour-vision-deficiency separation checks that a stock
# qualitative palette has not.
sns.set_theme(
    style="ticks",
    context="notebook",
    rc={
        "axes.edgecolor": "#c9c9c3",
        "axes.linewidth": 0.9,
        "grid.color": "#e6e6e1",
        "grid.linewidth": 0.8,
        "xtick.color": "#55554e",
        "ytick.color": "#55554e",
        "font.size": 12,
        "axes.labelsize": 12.5,
        "xtick.labelsize": 11,
        "ytick.labelsize": 11,
        "legend.fontsize": 11,
    },
)

from .snowseason import DailySeries, rank_ascending, water_year_slice

__all__ = [
    "anomaly_bars", "collect_pdf", "model_agreement_scatter", "save",
    "spaghetti", "validation_series",
]

# Validated categorical pair, in fixed order.
ERA5_COLOUR = "#1f6feb"
MERRA2_COLOUR = "#e07000"
# Diverging poles reuse those hues; the midpoint is neutral, never a hue.
DRY_COLOUR = "#e07000"
WET_COLOUR = "#1f6feb"
MID_COLOUR = "#b9b9b4"

#: Ranked shades within each pole, most extreme first. Stepping lightness
#: rather than hue keeps each ramp reading as one family - these are degrees of
#: the same thing, not separate identities - while staying separable enough to
#: match a curve to a legend row.
DRY_SHADES = ("#8f4500", "#e07000", "#f6ad5e")
WET_SHADES = ("#123c86", "#1f6feb", "#7fadf6")

INK = "#1b1b18"
INK_SECONDARY = "#55554e"
INK_MUTED = "#8a8a80"
SURFACE = "#fcfcfb"
GRID = "#e6e6e1"


def _style(ax, *, grid_axis: str = "y") -> None:
    """Recessive axes and grid; the data carries the ink."""
    ax.set_facecolor(SURFACE)
    ax.grid(True, axis=grid_axis, color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    sns.despine(ax=ax, top=True, right=True)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c9c9c3")
    ax.tick_params(colors=INK_SECONDARY, labelsize=9, length=3, width=0.9)


def _titles(ax, title: str) -> None:
    """Place the title above the axes.

    Titles only. Explanatory prose belongs in a figure caption, where it can be
    edited without re-rendering and where a reader expects to find it.
    """
    ax.text(0.0, 1.08, title, transform=ax.transAxes, color=INK,
            fontsize=15, fontweight="bold", va="top", ha="left")


#: When set, every saved figure is also appended to this multi-page document.
_COLLECTOR = None


@contextmanager
def collect_pdf(path: Path):
    """Collect every figure saved inside this block into one PDF document."""
    global _COLLECTOR
    from matplotlib.backends.backend_pdf import PdfPages

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp{os.getpid()}.pdf")
    with PdfPages(tmp) as pages:
        _COLLECTOR = pages
        try:
            yield
        finally:
            _COLLECTOR = None
    tmp.replace(path)


def save(fig, path: Path) -> Path:
    """Write a figure atomically, as both a raster and a vector document.

    PDF is the better artefact for these plots: a spaghetti panel is dozens of
    hairline strokes, and rasterising them loses exactly the thin lines the
    figure is made of. The PNG stays for quick viewing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in (".png", ".pdf"):
        target = path.with_suffix(suffix)
        tmp = target.with_suffix(f".tmp{os.getpid()}{suffix}")
        fig.savefig(
            tmp,
            dpi=170 if suffix == ".png" else None,
            bbox_inches="tight",
            facecolor=SURFACE,
        )
        tmp.replace(target)
    if _COLLECTOR is not None:
        _COLLECTOR.savefig(fig, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return path.with_suffix(".png")


def anomaly_bars(
    water_years: list[int],
    values: np.ndarray,
    *,
    title: str,
    unit: str,
    highlight: tuple[int, ...] = (),
    path: Path,
) -> Path:
    """One bar per water year, coloured by departure from the record mean.

    Polarity is the job here - which years were dry and which were wet - so the
    scale diverges from a neutral midpoint at the mean rather than ramping.
    """
    values = np.asarray(values, dtype=float)
    mean = float(np.nanmean(values))
    spread = float(np.nanstd(values))
    ranks = rank_ascending(values)

    fig, ax = plt.subplots(figsize=(11, 4.6))
    _style(ax)

    colours = []
    for v in values:
        if not np.isfinite(v) or spread == 0:
            colours.append(MID_COLOUR)
            continue
        z = (v - mean) / spread
        weight = float(np.clip(abs(z) / 2.0, 0.0, 1.0))
        pole = WET_COLOUR if z >= 0 else DRY_COLOUR
        colours.append(_blend(MID_COLOUR, pole, weight))

    ax.bar(water_years, values, color=colours, width=0.74, zorder=3)
    ax.axhline(mean, color=INK, linewidth=1.6, zorder=4)
    label = ax.annotate(
        "Mean", xy=(max(water_years), mean), xytext=(0, 5),
        textcoords="offset points", ha="right", color=INK,
        fontsize=10.5, zorder=7,
    )
    label.set_path_effects(
        [path_effects.withStroke(linewidth=3.0, foreground=SURFACE)]
    )

    # Headroom for the three-line callouts, which otherwise run off the top.
    finite = values[np.isfinite(values)]
    if finite.size:
        ax.set_ylim(0, float(finite.max()) * 1.30)

    for wy in highlight:
        if wy not in water_years or not np.isfinite(values[water_years.index(wy)]):
            continue
        i = water_years.index(wy)
        ax.annotate(
            str(wy), xy=(wy, values[i]), xytext=(0, 6),
            textcoords="offset points", ha="center", fontsize=10.5, color=INK,
        )

    ax.set_xlabel("Water Year", color=INK_SECONDARY)
    ax.set_ylabel(unit, color=INK_SECONDARY)
    ax.set_xlim(min(water_years) - 1, max(water_years) + 1)
    _titles(ax, title)
    return save(fig, path)


def model_agreement_scatter(
    water_years: list[int],
    era5: np.ndarray,
    merra2: np.ndarray,
    *,
    rho: float,
    p_value: float,
    title: str,
    highlight: tuple[int, ...] = (),
    path: Path,
) -> Path:
    """Rank-versus-rank agreement between the two models.

    Ranks rather than values, because the models differ in magnitude by a factor
    that itself varies with how thin the snowpack is. Rank is the claim that
    survives that; plotting raw values would imply an agreement that is not there.
    """
    era5_rank = rank_ascending(np.asarray(era5, dtype=float))
    merra2_rank = rank_ascending(np.asarray(merra2, dtype=float))

    fig, ax = plt.subplots(figsize=(5.6, 5.6))
    _style(ax)
    ax.grid(True, axis="x", color=GRID, linewidth=0.8, zorder=0)

    n = len(water_years)
    ax.plot([0, n + 1], [0, n + 1], color=GRID, linewidth=1.4, zorder=2)
    ax.scatter(era5_rank, merra2_rank, s=42, color=ERA5_COLOUR, alpha=0.75,
               edgecolor=SURFACE, linewidth=1.2, zorder=4)

    for wy in highlight:
        if wy not in water_years:
            continue
        i = water_years.index(wy)
        if not (np.isfinite(era5_rank[i]) and np.isfinite(merra2_rank[i])):
            continue
        ax.scatter([era5_rank[i]], [merra2_rank[i]], s=90, color=MERRA2_COLOUR,
                   edgecolor=SURFACE, linewidth=1.4, zorder=5)
        ax.annotate(f"WY{wy}", xy=(era5_rank[i], merra2_rank[i]),
                    xytext=(7, 4), textcoords="offset points",
                    fontsize=9, color=INK)

    ax.set_xlabel("ERA5 Rank (1 = Lowest)", color=INK_SECONDARY)
    ax.set_ylabel("MERRA-2 Rank (1 = Lowest)", color=INK_SECONDARY)
    ax.set_xlim(0, n + 1)
    ax.set_ylim(0, n + 1)
    ax.set_aspect("equal")
    _titles(ax, title)
    ax.annotate(
        f"Spearman rho = {rho:.3f}   "
        f"p {'< 1e-16' if p_value == 0 else f'= {p_value:.1e}'}   n = {n}",
        xy=(0.03, 0.03), xycoords="axes fraction",
        fontsize=9, color=INK_SECONDARY,
    )
    return save(fig, path)


def spaghetti(
    series: DailySeries,
    water_years: list[int],
    *,
    low: tuple[int, ...] = (),
    high: tuple[int, ...] = (),
    title: str,
    unit: str,
    path: Path,
) -> Path:
    """Every water year as one thin line, with chosen years brought forward.

    The background years are a single *population*, not many series, so they
    share one neutral hue. Giving them separate colours would be a cycled-hue
    rainbow, and the outliers would then compete with noise rather than stand
    out. Overlap does the work a percentile band would otherwise do: where many
    years coincide the ink darkens, and unlike a band - which is computed per
    day-of-year and traces a path no real year followed - every curve here is a
    trajectory that actually happened.

    ``low`` and ``high`` are ranked outliers, most extreme first. Each group
    shades from its pole toward the surface, so rank is legible from weight
    alone, and each line is labelled with its year rather than a sentence.

    The ensemble mean is the one black line: the reference every other curve is
    read against.
    """
    fig, ax = plt.subplots(figsize=(11, 5))
    _style(ax)

    def curve(wy: int):
        year = water_year_slice(series, wy)
        if len(year) == 0:
            return None, None
        return np.array([_water_day(d, wy) for d in year.dates]), year.values

    outliers = set(low) | set(high)
    stack = []
    for wy in water_years:
        x, y = curve(wy)
        if x is None:
            continue
        if wy not in outliers:
            ax.plot(x, y, color=INK_MUTED, linewidth=0.7, alpha=0.28, zorder=2,
                    solid_capstyle="round")
        stack.append(y)

    # The ensemble mean, in the one black line on the canvas.
    if stack:
        width = max(len(y) for y in stack)
        grid = np.full((len(stack), width), np.nan)
        for i, y in enumerate(stack):
            grid[i, : len(y)] = y
        filled = np.any(np.isfinite(grid), axis=0)
        mean = np.full(width, np.nan)
        mean[filled] = np.nanmean(grid[:, filled], axis=0)
        ax.plot(np.arange(width), mean, color=INK, linewidth=2.6, zorder=5,
                solid_capstyle="round", label="Mean")

    # Outliers carry their identity in a legend rather than in labels pinned to
    # the curve. Extreme years peak within days of each other, so a label at the
    # peak sits in a thicket of near-identical lines and cannot be traced back
    # to one of them.
    for group, shades in ((high, WET_SHADES), (low, DRY_SHADES)):
        for rank, wy in enumerate(group):
            x, y = curve(wy)
            if x is None:
                continue
            ax.plot(x, y, color=shades[min(rank, len(shades) - 1)],
                    linewidth=2.1, zorder=6 - rank * 0.1,
                    solid_capstyle="round", label=str(wy))

    ticks = [0, 31, 61, 92, 123, 151, 182, 212, 243, 273]
    ax.set_xticks(ticks)
    ax.set_xticklabels(["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May",
                        "Jun", "Jul"])
    ax.set_xlim(0, 290)
    ax.set_ylim(bottom=0)
    ax.set_ylabel(unit, color=INK_SECONDARY)
    _titles(ax, title)
    legend = ax.legend(
        frameon=False, loc="upper left", ncol=2, handlelength=1.7,
        columnspacing=1.5, labelspacing=0.35, borderpad=0.0,
    )
    for text in legend.get_texts():
        text.set_color(INK_SECONDARY)
    return save(fig, path)


def validation_series(
    days: list[date],
    series: dict[str, np.ndarray],
    *,
    wy: int,
    title: str,
    path: Path,
) -> Path:
    """Daily fractional snow cover from the satellite reference and each model.

    The reference is drawn heaviest because it is the thing being validated
    against, not a third opinion. Gaps are left as gaps: a day with no usable
    reference is not interpolated across, since the whole point of the panel is
    to show where the models and the observation part company.
    """
    fig, ax = plt.subplots(figsize=(10.5, 4.6))
    _style(ax)

    x = np.array([_water_day(d, wy) for d in days])
    styles = {
        "MODSCAG": dict(color=INK, linewidth=2.2, zorder=6),
        "ERA5": dict(color=ERA5_COLOUR, linewidth=1.8, zorder=5),
        "MERRA-2": dict(color=MERRA2_COLOUR, linewidth=1.8, zorder=5),
    }
    for name, values in series.items():
        ax.plot(x, values, label=name, **styles.get(name, dict(linewidth=1.6)))

    reference = series.get("MODSCAG")
    if reference is not None:
        missing = ~np.isfinite(reference)
        if np.any(missing):
            ax.fill_between(
                x, 0, 1, where=missing, color=MID_COLOUR, alpha=0.30,
                linewidth=0, zorder=1, label="No Usable Reference",
            )

    ticks = [0, 31, 61, 92, 123, 151, 182, 212, 243, 273, 304, 334]
    ax.set_xticks(ticks)
    ax.set_xticklabels(["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May",
                        "Jun", "Jul", "Aug", "Sep"])
    ax.set_xlim(0, 365)
    ax.set_ylim(0, 1)
    ax.set_ylabel("Fractional Snow Cover", color=INK_SECONDARY)
    _titles(ax, title)
    legend = ax.legend(frameon=False, fontsize=9, loc="upper right", ncol=2)
    for text in legend.get_texts():
        text.set_color(INK_SECONDARY)
    return save(fig, path)


def _water_day(day: date, wy: int) -> int:
    return (day - date(wy - 1, 10, 1)).days


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def _blend(base: str, pole: str, weight: float) -> tuple[float, float, float]:
    a = np.array(matplotlib.colors.to_rgb(base))
    b = np.array(matplotlib.colors.to_rgb(pole))
    return tuple(a + (b - a) * weight)
