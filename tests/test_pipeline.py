import concurrent.futures

import numpy as np
import pytest

from fsca_eval import checkpoint, config, dates, earthdata, pipeline, regrid


def _build_full_domain_mapping(n_per_cell=4):
    lons, lats = [], []
    for lon_idx in range(config.N_LON_CELLS):
        for lat_idx in range(config.N_LAT_CELLS):
            lons.extend([config.CELL_LON_CENTERS[lon_idx]] * n_per_cell)
            lats.extend([config.CELL_LAT_CENTERS[lat_idx]] * n_per_cell)
    lon = np.array(lons)
    lat = np.array(lats)
    mapping = regrid.build_mapping(lon, lat)
    return mapping, len(lon)


class FakeTransport:
    def __init__(self, n_pixels, snow_fraction=40.0, merra_value=0.5, fail_dates=None):
        self.n_pixels = n_pixels
        self.snow_fraction = snow_fraction
        self.merra_value = merra_value
        self.fail_dates = fail_dates or set()
        self.merra_calls = []
        self.modscag_calls = []

    def fetch_merra_subset(self, d, stream):
        self.merra_calls.append(d)
        if d in self.fail_dates:
            raise earthdata.TransientFetchError("simulated failure")
        frsno = np.full((config.N_LAT_CELLS, config.N_LON_CELLS), self.merra_value)
        return earthdata.MerraSubset(
            frsno=frsno,
            lon_centers=np.array(config.CELL_LON_CENTERS),
            lat_centers=np.array(config.CELL_LAT_CENTERS),
            stream=stream,
        )

    def fetch_modscag_tiles(self, d, tmp_dir):
        self.modscag_calls.append(d)
        snow = np.full(self.n_pixels, self.snow_fraction)
        days_without_obs = np.zeros(self.n_pixels)
        tile = earthdata.ModscagTile(
            pixel_x_sinusoidal=np.zeros(self.n_pixels),
            pixel_y_sinusoidal=np.zeros(self.n_pixels),
            snow_fraction=snow,
            days_without_observation=days_without_obs,
        )
        return [tile]


def test_compute_month_produces_full_support_valid_checkpoint(tmp_path):
    mapping, n_pixels = _build_full_domain_mapping(n_per_cell=4)
    transport = FakeTransport(n_pixels, snow_fraction=40.0, merra_value=0.5)

    rows, metadata = pipeline.compute_month(2020, 2020, 2, transport, mapping, str(tmp_path))

    assert len(rows) == config.ROWS_PER_MONTH
    n_days = dates.n_calendar_days_in_month(2020, 2)
    assert n_days == 29  # leap year
    assert rows[0]["n_calendar_days"] == n_days
    assert rows[0]["n_days"] == n_days
    assert rows[0]["support_fraction"] == pytest.approx(1.0)
    # error sign is MERRA (0.5) minus MODSCAG (0.4) = +0.1 -> bias_pp = +10
    assert rows[0]["bias_pp"] == pytest.approx(10.0)
    assert metadata["calendar_year"] == 2020
    assert metadata["calendar_month"] == 2
    assert len(transport.merra_calls) == n_days
    assert len(transport.modscag_calls) == n_days


def test_compute_month_on_day_processed_called_for_every_day():
    mapping, n_pixels = _build_full_domain_mapping(n_per_cell=2)
    transport = FakeTransport(n_pixels)
    seen_dates = []

    def on_day_processed(d, raw, record):
        seen_dates.append(d)
        assert raw.date == d
        assert record.date == d
        assert len(record.stats) == config.N_CELLS

    pipeline.compute_month(2021, 2021, 4, transport, mapping, "/tmp", on_day_processed=on_day_processed)
    assert seen_dates == list(dates.iter_dates_in_month(2021, 4))


def test_compute_month_writes_pass_checkpoint_validation(tmp_path):
    mapping, n_pixels = _build_full_domain_mapping(n_per_cell=4)
    transport = FakeTransport(n_pixels, snow_fraction=40.0, merra_value=0.5)
    rows, metadata = pipeline.compute_month(2020, 2020, 2, transport, mapping, str(tmp_path))

    path = str(tmp_path / "ck.csv")
    checkpoint.write_checkpoint(path, rows, metadata)
    result = checkpoint.validate_checkpoint(path, expected_water_year=2020, expected_year=2020, expected_month=2)
    assert result.ok, result.errors


def test_run_month_task_writes_then_skips_existing_valid_checkpoint(tmp_path):
    mapping, n_pixels = _build_full_domain_mapping(n_per_cell=4)
    transport = FakeTransport(n_pixels)
    results_dir = str(tmp_path / "results")

    first = pipeline.run_month_task(2020, 2020, 2, transport, mapping, results_dir, str(tmp_path))
    assert first.ok
    assert not first.skipped_existing
    calls_after_first = len(transport.merra_calls)

    second = pipeline.run_month_task(2020, 2020, 2, transport, mapping, results_dir, str(tmp_path))
    assert second.ok
    assert second.skipped_existing
    assert len(transport.merra_calls) == calls_after_first  # no re-fetch on skip


def _fake_clock(values):
    state = {"values": list(values)}

    def clock():
        if len(state["values"]) > 1:
            return state["values"].pop(0)
        return state["values"][0]

    return clock


def test_run_scheduler_pauses_cleanly_at_deadline_and_leaves_remaining_queued():
    months = [(2020, 2020, m) for m in range(1, 6)]
    printed = []

    def run_one_month(wy, y, m):
        return pipeline.MonthResult(wy, y, m, ok=True)

    clock = _fake_clock([0, 1, 100, 100, 100, 100, 100])

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        report = pipeline.run_scheduler(
            months, run_one_month, executor,
            max_workers=1, max_runtime_minutes=1.0,
            monotonic=clock, poll_timeout=0.05, print_fn=printed.append,
        )

    assert report.completed == [months[0]]
    assert report.remaining == months[1:]
    assert report.paused_cleanly is True
    assert printed == ["paused cleanly"]


def test_run_scheduler_completes_all_months_without_deadline():
    months = [(2020, 2020, m) for m in range(1, 4)]

    def run_one_month(wy, y, m):
        return pipeline.MonthResult(wy, y, m, ok=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        report = pipeline.run_scheduler(months, run_one_month, executor, max_workers=2)

    assert sorted(report.completed) == sorted(months)
    assert report.failed == []
    assert report.remaining == []
    assert report.paused_cleanly is False


def test_run_scheduler_requeues_failures_and_gives_up_after_max_retries():
    months = [(2020, 2020, 1)]
    attempts = {"n": 0}

    def run_one_month(wy, y, m):
        attempts["n"] += 1
        raise RuntimeError("always fails")

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        report = pipeline.run_scheduler(months, run_one_month, executor, max_workers=1)

    assert attempts["n"] == pipeline.MAX_MONTH_RETRIES + 1
    assert report.failed == months
    assert report.completed == []
    assert report.remaining == []


def test_run_scheduler_requeues_transient_failure_then_succeeds():
    months = [(2020, 2020, 1), (2020, 2020, 2)]
    attempts = {"n": 0}

    def run_one_month(wy, y, m):
        if (y, m) == (2020, 1):
            attempts["n"] += 1
            if attempts["n"] < 2:
                return pipeline.MonthResult(2020, y, m, ok=False, errors=["transient"])
        return pipeline.MonthResult(2020, y, m, ok=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        report = pipeline.run_scheduler(months, run_one_month, executor, max_workers=1)

    assert sorted(report.completed) == sorted(months)
    assert report.failed == []
    assert attempts["n"] == 2
