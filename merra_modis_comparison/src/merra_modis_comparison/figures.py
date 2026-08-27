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

from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from .snowseason import DailySeries, rank_ascending, water_year_slice

__all__ = [
    "anomaly_bars", "save", "trajectory", "model_agreement_scatter",
    "validation_series",
]

# Validated categorical pair, in fixed order.
ERA5_COLOUR = "#1f6feb"
MERRA2_COLOUR = "#e07000"
# Diverging poles reuse those hues; the midpoint is neutral, never a hue.
DRY_COLOUR = "#e07000"
WET_COLOUR = "#1f6feb"
MID_COLOUR = "#b9b9b4"

INK = "#1b1b18"
INK_SECONDARY = "#55554e"
INK_MUTED = "#8a8a80"
SURFACE = "#fcfcfb"
GRID = "#e6e6e1"


def _style(ax) -> None:
    """Recessive axes and grid; the data carries the ink."""
    ax.set_facecolor(SURFACE)
    ax.grid(True, axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_SECONDARY, labelsize=9, length=0)


def _titles(ax, title: str, subtitle: str) -> None:
    """Place title and subtitle above the axes without letting them collide.

    The subtitle is wrapped to the axes width so a long one does not run off the
    canvas - which a successful render will not tell you about.
    """
    import textwrap

    width_in = ax.get_figure().get_size_inches()[0]
    wrapped = "\n".join(textwrap.wrap(subtitle, width=max(40, int(width_in * 12))))
    lines = wrapped.count("\n") + 1
    ax.text(0.0, 1.10 + 0.055 * lines, title, transform=ax.transAxes, color=INK,
            fontsize=13, fontweight="bold", va="top", ha="left")
    ax.text(0.0, 1.045 + 0.055 * (lines - 1), wrapped, transform=ax.transAxes,
            color=INK_SECONDARY, fontsize=9.5, va="top", ha="left", linespacing=1.4)


def save(fig, path: Path) -> Path:
    """Write a figure atomically so a failed render cannot replace a good one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.png")
    fig.savefig(tmp, dpi=170, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    tmp.replace(path)
    return path


def anomaly_bars(
    water_years: list[int],
    values: np.ndarray,
    *,
    title: str,
    subtitle: str,
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
    ax.axhline(mean, color=INK_MUTED, linewidth=1.2, linestyle=(0, (4, 3)), zorder=4)
    ax.annotate(
        f"{len(water_years)}-year mean  {mean:.3g} {unit}",
        xy=(max(water_years), mean),
        xytext=(0, 6),
        textcoords="offset points",
        ha="right",
        color=INK_SECONDARY,
        fontsize=8.5,
    )

    for wy in highlight:
        if wy not in water_years:
            continue
        i = water_years.index(wy)
        if not np.isfinite(values[i]):
            continue
        rank = int(ranks[i]) if np.isfinite(ranks[i]) else 0
        n = len(water_years)
        end = "lowest" if rank <= n / 2 else "highest"
        shown = rank if rank <= n / 2 else n - rank + 1
        # rank 1 reads "lowest of 46", not "1st lowest of 46"
        phrase = f"{end} of {n}" if shown == 1 else f"{_ordinal(shown)} {end} of {n}"
        ax.annotate(
            f"WY{wy}\n{values[i]:.3g} {unit}\n{phrase}",
            xy=(wy, values[i]),
            xytext=(0, 9),
            textcoords="offset points",
            ha="center",
            fontsize=8.5,
            color=INK,
            linespacing=1.35,
        )

    ax.set_xlabel("water year", color=INK_SECONDARY, fontsize=9.5)
    ax.set_ylabel(unit, color=INK_SECONDARY, fontsize=9.5)
    ax.set_xlim(min(water_years) - 1, max(water_years) + 1)
    _titles(ax, title, subtitle)
    return save(fig, path)


def trajectory(
    series: DailySeries,
    water_years: list[int],
    feature_years: tuple[int, ...],
    *,
    title: str,
    subtitle: str,
    unit: str,
    path: Path,
) -> Path:
    """Daily trajectories for chosen years against the record's spread.

    The band is the record's day-of-year range, so a featured year is read
    against what the domain normally does rather than against a single number.
    """
    fig, ax = plt.subplots(figsize=(10, 4.8))
    _style(ax)

    stacked = []
    for wy in water_years:
        year = water_year_slice(series, wy)
        if len(year) < 300:
            continue
        by_doy = np.full(366, np.nan)
        for d, v in zip(year.dates, year.values):
            by_doy[_water_day(d, wy)] = v
        stacked.append(by_doy)

    if stacked:
        grid = np.vstack(stacked)
        # A day-of-year slot can be empty for every year - 29 February outside a
        # leap year, or days past the end of a partial record. Reducing those
        # explicitly says so, rather than leaning on an all-NaN warning.
        filled = np.any(np.isfinite(grid), axis=0)
        lo = np.full(grid.shape[1], np.nan)
        hi = np.full(grid.shape[1], np.nan)
        mid = np.full(grid.shape[1], np.nan)
        if np.any(filled):
            lo[filled] = np.nanpercentile(grid[:, filled], 10, axis=0)
            hi[filled] = np.nanpercentile(grid[:, filled], 90, axis=0)
            mid[filled] = np.nanmedian(grid[:, filled], axis=0)
        x = np.arange(366)
        ax.fill_between(x, lo, hi, color=MID_COLOUR, alpha=0.35, linewidth=0, zorder=2,
                        label=f"10th-90th percentile, WY{min(water_years)}-{max(water_years)}")
        ax.plot(x, mid, color=INK_MUTED, linewidth=1.4, zorder=3, label="median")

    palette = (WET_COLOUR, DRY_COLOUR, "#5b7f3a")
    for i, wy in enumerate(feature_years):
        year = water_year_slice(series, wy)
        if len(year) == 0:
            continue
        x = np.array([_water_day(d, wy) for d in year.dates])
        ax.plot(x, year.values, color=palette[i % len(palette)], linewidth=2.0,
                zorder=5, label=f"WY{wy}")

    ticks = [0, 31, 61, 92, 123, 151, 182, 212, 243, 273, 304, 334]
    ax.set_xticks(ticks)
    ax.set_xticklabels(["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May",
                        "Jun", "Jul", "Aug", "Sep"])
    ax.set_xlim(0, 305)
    ax.set_ylabel(unit, color=INK_SECONDARY, fontsize=9.5)
    _titles(ax, title, subtitle)
    legend = ax.legend(frameon=False, fontsize=9, loc="upper left")
    for text in legend.get_texts():
        text.set_color(INK_SECONDARY)
    return save(fig, path)


def model_agreement_scatter(
    water_years: list[int],
    era5: np.ndarray,
    merra2: np.ndarray,
    *,
    rho: float,
    p_value: float,
    title: str,
    subtitle: str,
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

    ax.set_xlabel("ERA5 rank  (1 = lowest)", color=INK_SECONDARY, fontsize=9.5)
    ax.set_ylabel("MERRA-2 rank  (1 = lowest)", color=INK_SECONDARY, fontsize=9.5)
    ax.set_xlim(0, n + 1)
    ax.set_ylim(0, n + 1)
    ax.set_aspect("equal")
    _titles(ax, title, subtitle)
    ax.annotate(
        f"Spearman rho = {rho:.3f}   "
        f"p {'< 1e-16' if p_value == 0 else f'= {p_value:.1e}'}   n = {n}",
        xy=(0.03, 0.03), xycoords="axes fraction",
        fontsize=9, color=INK_SECONDARY,
    )
    return save(fig, path)


def validation_series(
    days: list[date],
    series: dict[str, np.ndarray],
    *,
    wy: int,
    title: str,
    subtitle: str,
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
                linewidth=0, zorder=1, label="no usable reference",
            )

    ticks = [0, 31, 61, 92, 123, 151, 182, 212, 243, 273, 304, 334]
    ax.set_xticks(ticks)
    ax.set_xticklabels(["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May",
                        "Jun", "Jul", "Aug", "Sep"])
    ax.set_xlim(0, 365)
    ax.set_ylim(0, 1)
    ax.set_ylabel("fractional snow cover", color=INK_SECONDARY, fontsize=9.5)
    _titles(ax, title, subtitle)
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
