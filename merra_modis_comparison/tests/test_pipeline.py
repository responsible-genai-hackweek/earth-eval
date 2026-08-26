import calendar

import numpy as np

from merra_modis_comparison.config import RunConfig
from merra_modis_comparison.metrics import StatsBlock, update_stats
from merra_modis_comparison.pipeline import build_final_rows
from merra_modis_comparison.plotting import write_metric_plot


def _synthetic_checkpoints(config: RunConfig) -> dict[tuple[int, int], StatsBlock]:
    result: dict[tuple[int, int], StatsBlock] = {}
    shape = config.target_grid.shape
    for year, month in config.calendar_months:
        stats = StatsBlock.empty(config.target_grid.size)
        for _ in range(calendar.monthrange(year, month)[1]):
            update_stats(
                stats,
                np.full(shape, 0.55),
                np.full(shape, 0.50),
                np.full(shape, 9),
                np.full(shape, 10),
                np.full(shape, 6),
            )
        result[(year, month)] = stats
    return result


def test_final_multiyear_row_counts_and_groups():
    config = RunConfig()
    overall, pixels = build_final_rows(_synthetic_checkpoints(config), config)
    assert len(overall) == 240
    assert len(pixels) == 17_280
    assert overall[0]["period"] == "WY2010"
    assert overall[0]["group"] == "Oct"
    assert overall[15]["group"] == "JJA"
    assert overall[-16]["scope"] == "climatology"
    assert overall[-16]["period"] == "WY2010-WY2023"
    assert all(np.isclose(float(row["bias_pp"]), 5.0) for row in overall)
    assert all(np.isclose(float(row["mae_pp"]), 5.0) for row in overall)


def test_single_water_year_final_rows():
    config = RunConfig(start_water_year=2023, end_water_year=2023, workers=2)
    overall, pixels = build_final_rows(_synthetic_checkpoints(config), config)
    assert len(overall) == 32
    assert len(pixels) == 32 * 72
    seasons = {
        row["group"]: row
        for row in overall
        if row["scope"] == "water_year"
        and row["water_year"] == 2023
        and row["group_type"] == "season"
    }
    assert seasons["SON"]["n_calendar_days"] == 91  # Sep + Oct + Nov
    assert seasons["DJF"]["n_calendar_days"] == 90  # Dec + Jan + Feb
    assert seasons["MAM"]["n_calendar_days"] == 92
    assert seasons["JJA"]["n_calendar_days"] == 92


def test_multiyear_plot_writes_atomically(tmp_path):
    config = RunConfig()
    overall, _ = build_final_rows(_synthetic_checkpoints(config), config)
    output = tmp_path / "bias_mae.png"
    write_metric_plot(overall, output)
    assert output.stat().st_size > 10_000
    assert not list(tmp_path.glob("*.tmp"))
