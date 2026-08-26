from __future__ import annotations

import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


MONTHS = ("Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep")
SEASONS = ("SON", "DJF", "MAM", "JJA")


def _finite_max(values: np.ndarray, fallback: float = 1.0) -> float:
    finite = values[np.isfinite(values)]
    return fallback if finite.size == 0 else max(float(np.max(finite)), 1e-9)


def write_metric_plot(rows: list[dict[str, object]], output: Path) -> None:
    yearly = [row for row in rows if row["scope"] == "water_year"]
    water_years = sorted({int(row["water_year"]) for row in yearly})
    if not water_years:
        raise ValueError("plot requires water-year statistics")
    lookup = {
        (int(row["water_year"]), str(row["group_type"]), str(row["group"])): row
        for row in yearly
    }
    bias = np.full((len(water_years), len(MONTHS)), np.nan)
    mae = np.full_like(bias, np.nan)
    for row_index, water_year in enumerate(water_years):
        for column, month in enumerate(MONTHS):
            row = lookup[(water_year, "month", month)]
            if row["bias_pp"] is not None:
                bias[row_index, column] = float(row["bias_pp"])
            if row["mae_pp"] is not None:
                mae[row_index, column] = float(row["mae_pp"])

    output.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(15.5, 10.2))
    bias_limit = _finite_max(np.abs(bias), fallback=1.0)
    bias_image = axes[0, 0].imshow(
        bias,
        aspect="auto",
        cmap="RdBu_r",
        vmin=-bias_limit,
        vmax=bias_limit,
        interpolation="nearest",
    )
    mae_image = axes[0, 1].imshow(
        mae,
        aspect="auto",
        cmap="YlOrRd",
        vmin=0,
        vmax=_finite_max(mae, fallback=1.0),
        interpolation="nearest",
    )
    year_positions = np.arange(len(water_years))
    for axis, title in zip(
        axes[0], ("Monthly bias", "Monthly mean absolute error"), strict=True
    ):
        axis.set_xticks(np.arange(len(MONTHS)), MONTHS)
        axis.set_yticks(year_positions, water_years)
        axis.set_xlabel("Water-year month")
        axis.set_ylabel("Water year")
        axis.set_title(title)
    fig.colorbar(bias_image, ax=axes[0, 0], label="Percentage points", shrink=0.88)
    fig.colorbar(mae_image, ax=axes[0, 1], label="Percentage points", shrink=0.88)

    colors = {
        "SON": "#4c78a8",
        "DJF": "#72b7b2",
        "MAM": "#f58518",
        "JJA": "#e45756",
    }
    for metric, axis, title in (
        ("bias_pp", axes[1, 0], "Seasonal bias"),
        ("mae_pp", axes[1, 1], "Seasonal mean absolute error"),
    ):
        axis.axhline(0, color="#5b6573", linewidth=0.8)
        for season in SEASONS:
            values = [
                lookup[(water_year, "season", season)][metric]
                for water_year in water_years
            ]
            axis.plot(
                water_years,
                [np.nan if value is None else float(value) for value in values],
                marker="o",
                linewidth=1.9,
                markersize=4,
                label=season,
                color=colors[season],
            )
        axis.set_title(title)
        axis.set_xlabel("Water year")
        axis.set_ylabel("Percentage points")
        axis.set_xticks(water_years[::2] if len(water_years) > 8 else water_years)
        axis.grid(axis="y", color="#d8dde5", linewidth=0.7)
        axis.legend(frameon=False, ncol=4, loc="best")

    fig.suptitle(
        "MERRA-2 vs daily STC-MODSCAG fractional snow cover\n"
        f"Water years {water_years[0]}–{water_years[-1]}; "
        "109–104°W, 37–41°N; MERRA-2 15:00–16:00 UTC mean",
        fontsize=15,
    )
    fig.text(
        0.5,
        0.012,
        "Valid equal-area 500 m MODSCAG pixels provide the weights; error sign is MERRA-2 minus MODSCAG.",
        ha="center",
        fontsize=9,
        color="#4c5664",
    )
    fig.tight_layout(rect=(0, 0.035, 1, 0.925))
    with tempfile.NamedTemporaryFile(
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".png",
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        fig.savefig(temporary_path, dpi=180, bbox_inches="tight", facecolor="white")
        temporary_path.replace(output)
        output.chmod(0o644)
    finally:
        plt.close(fig)
        temporary_path.unlink(missing_ok=True)
