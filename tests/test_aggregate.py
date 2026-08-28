import math
import os

import pytest

from fsca_eval import aggregate, checkpoint, config, dates, metrics


def _stats(sum_w=10.0, sum_w_error=2.0, sum_w_abs_error=3.0, sum_w_r=5.0, n_calendar_days=1):
    return metrics.SufficientStats(
        sum_w=sum_w, sum_w_error=sum_w_error, sum_w_abs_error=sum_w_abs_error, sum_w_r=sum_w_r,
        valid_pixels=10, expected_pixels=10, observed_pixels=10,
        n_cell_days=1, n_days=1, n_calendar_days=n_calendar_days,
    )


def _build_synthetic_loaded(stats_factory=_stats):
    loaded = []
    for water_year, year, month in dates.iter_calendar_months():
        cell_stats = [stats_factory() for _ in range(config.N_CELLS)]
        loaded.append(aggregate.LoadedCheckpoint(water_year=water_year, year=year, month=month, cell_stats=cell_stats))
    return loaded


def test_build_aggregates_row_counts():
    loaded = _build_synthetic_loaded()
    overall_rows, pixel_rows = aggregate.build_aggregates(loaded)
    assert len(overall_rows) == config.EXPECTED_OVERALL_ROWS == 240
    assert len(pixel_rows) == config.EXPECTED_PER_CELL_ROWS == 17280


def test_build_aggregates_no_duplicate_group_keys():
    loaded = _build_synthetic_loaded()
    overall_rows, _ = aggregate.build_aggregates(loaded)
    keys = [(r["group_type"], r["water_year"], r["period"]) for r in overall_rows]
    assert len(keys) == len(set(keys))


def test_wy_month_group_matches_single_source_checkpoint():
    loaded = _build_synthetic_loaded()
    overall_rows, _ = aggregate.build_aggregates(loaded)
    row = next(r for r in overall_rows if r["group_type"] == "wy_month" and r["water_year"] == 2010 and r["period"] == 10)
    # exactly one checkpoint contributes -> domain row == sum of 72 identical per-cell stats
    assert row["sum_w"] == pytest.approx(10.0 * config.N_CELLS)
    assert row["sum_w_error"] == pytest.approx(2.0 * config.N_CELLS)


def test_climatology_month_group_sums_across_all_water_years():
    loaded = _build_synthetic_loaded()
    overall_rows, _ = aggregate.build_aggregates(loaded)
    row = next(r for r in overall_rows if r["group_type"] == "climatology_month" and r["period"] == 1)
    assert row["water_year"] == aggregate.CLIMATOLOGY_MARKER
    # 14 water years x 72 cells each contributing sum_w=10
    assert row["sum_w"] == pytest.approx(10.0 * config.N_CELLS * config.N_WATER_YEARS)


def test_wy_season_group_sums_three_months():
    loaded = _build_synthetic_loaded()
    overall_rows, _ = aggregate.build_aggregates(loaded)
    row = next(r for r in overall_rows if r["group_type"] == "wy_season" and r["water_year"] == 2010 and r["period"] == "DJF")
    assert row["sum_w"] == pytest.approx(10.0 * config.N_CELLS * 3)


def test_climatology_season_group_sums_14_years_times_3_months():
    loaded = _build_synthetic_loaded()
    overall_rows, _ = aggregate.build_aggregates(loaded)
    row = next(r for r in overall_rows if r["group_type"] == "climatology_season" and r["period"] == "DJF")
    assert row["water_year"] == aggregate.CLIMATOLOGY_MARKER
    assert row["sum_w"] == pytest.approx(10.0 * config.N_CELLS * config.N_WATER_YEARS * 3)


def test_zero_pair_group_gets_nan_row_not_omitted():
    loaded = _build_synthetic_loaded(stats_factory=metrics.SufficientStats)
    overall_rows, pixel_rows = aggregate.build_aggregates(loaded)
    assert len(overall_rows) == config.EXPECTED_OVERALL_ROWS
    row = next(r for r in overall_rows if r["group_type"] == "wy_month" and r["water_year"] == 2010 and r["period"] == 10)
    assert math.isnan(row["bias_pp"])
    assert row["sum_w"] == 0


def test_build_aggregates_raises_on_incomplete_loaded_checkpoints():
    # dropping one month's checkpoint leaves fewer than 240 groups -> must be
    # caught explicitly rather than silently written with a hole in coverage.
    loaded = _build_synthetic_loaded()[:-1]
    with pytest.raises(aggregate.AggregationError):
        aggregate.build_aggregates(loaded)


def test_load_all_checkpoints_raises_when_all_missing(tmp_path):
    with pytest.raises(aggregate.AggregationError) as excinfo:
        aggregate.load_all_checkpoints(str(tmp_path))
    assert f"{config.N_MONTHS} of {config.N_MONTHS}" in str(excinfo.value) or "168" in str(excinfo.value)


def test_load_all_checkpoints_and_write_aggregates_full_round_trip(tmp_path):
    results_dir = str(tmp_path)
    for water_year, year, month in dates.iter_calendar_months():
        n_days = dates.n_calendar_days_in_month(year, month)
        cell_stats = [_stats(n_calendar_days=n_days) for _ in range(config.N_CELLS)]
        rows, metadata = checkpoint.build_month_checkpoint_rows(water_year, year, month, cell_stats)
        path = os.path.join(results_dir, config.CHECKPOINT_SUBDIR, f"{year:04d}-{month:02d}.csv")
        checkpoint.write_checkpoint(path, rows, metadata)

    loaded = aggregate.load_all_checkpoints(results_dir)
    assert len(loaded) == config.N_MONTHS

    overall_path, pixel_path = aggregate.write_aggregates(results_dir, loaded=loaded)
    assert os.path.exists(overall_path)
    assert os.path.exists(pixel_path)

    with open(overall_path) as f:
        lines = f.readlines()
    assert lines[0].startswith("# METADATA")
    assert len(lines) == 1 + 1 + config.EXPECTED_OVERALL_ROWS  # metadata + header + rows

    with open(pixel_path) as f:
        pixel_lines = f.readlines()
    assert len(pixel_lines) == 1 + 1 + config.EXPECTED_PER_CELL_ROWS


def test_load_water_year_checkpoints_raises_when_missing(tmp_path):
    with pytest.raises(aggregate.AggregationError) as excinfo:
        aggregate.load_water_year_checkpoints(str(tmp_path), 2023)
    assert "12 of 12" in str(excinfo.value)


def test_load_water_year_checkpoints_rejects_out_of_range_year(tmp_path):
    with pytest.raises(aggregate.AggregationError):
        aggregate.load_water_year_checkpoints(str(tmp_path), 1999)


def test_load_water_year_checkpoints_loads_only_that_years_12_months(tmp_path):
    results_dir = str(tmp_path)
    for water_year, year, month in dates.iter_calendar_months():
        n_days = dates.n_calendar_days_in_month(year, month)
        cell_stats = [_stats(n_calendar_days=n_days) for _ in range(config.N_CELLS)]
        rows, metadata = checkpoint.build_month_checkpoint_rows(water_year, year, month, cell_stats)
        path = os.path.join(results_dir, config.CHECKPOINT_SUBDIR, f"{year:04d}-{month:02d}.csv")
        checkpoint.write_checkpoint(path, rows, metadata)

    loaded = aggregate.load_water_year_checkpoints(results_dir, 2023)
    assert len(loaded) == 12
    assert {lc.water_year for lc in loaded} == {2023}
