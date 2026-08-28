"""Month-task computation, atomic checkpointing, and the resumable scheduler.

The scheduler (`run_scheduler`) is executor-agnostic: it accepts anything
implementing the `concurrent.futures.Executor.submit` interface, so tests can
inject a `ThreadPoolExecutor` with a fake, fast month-runner instead of a real
`ProcessPoolExecutor` doing authenticated network I/O.
"""

from __future__ import annotations

import concurrent.futures
import os
import signal
import tempfile
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from . import checkpoint, config, dates, earthdata, worker

MAX_MONTH_RETRIES = 3  # operational default: not specified by the scientific
# contract; a month that still fails after this many attempts is reported as
# permanently failed rather than requeued forever.


def month_checkpoint_path(results_dir: str, year: int, month: int) -> str:
    return os.path.join(
        results_dir, config.CHECKPOINT_SUBDIR, f"{year:04d}-{month:02d}.csv"
    )


def all_month_tasks() -> list[tuple[int, int, int]]:
    """All 168 (water_year, calendar_year, calendar_month) tuples."""
    return list(dates.iter_calendar_months())


def compute_month(
    water_year: int,
    year: int,
    month: int,
    transport: earthdata.Transport,
    mapping,
    tmp_dir_root: str,
    on_day_processed: Callable[[object, worker.RawDayInputs, worker.DayCellRecord], None] | None = None,
) -> tuple[list[dict], dict]:
    """Compute one month's 73 checkpoint rows + metadata without writing
    anything. Shared by the writing pipeline and examples.py's cross-check
    (which supplies on_day_processed to capture one target day's raw inputs
    and reduced record).
    """
    from . import metrics as metrics_module  # local import avoids a cycle at module load

    cell_stats = [metrics_module.SufficientStats() for _ in range(config.N_CELLS)]

    for d in dates.iter_dates_in_month(year, month):
        with tempfile.TemporaryDirectory(dir=tmp_dir_root) as day_tmp_dir:
            raw = worker.fetch_day(d, transport, day_tmp_dir)
        record = worker.reduce_day(raw, mapping)
        if on_day_processed is not None:
            on_day_processed(d, raw, record)
        for cell_id in range(config.N_CELLS):
            cell_stats[cell_id] = cell_stats[cell_id] + record.stats[cell_id]

    rows, metadata = checkpoint.build_month_checkpoint_rows(water_year, year, month, cell_stats)
    return rows, metadata


@dataclass
class MonthResult:
    water_year: int
    year: int
    month: int
    ok: bool
    errors: list[str] = field(default_factory=list)
    skipped_existing: bool = False


def run_month_task(
    water_year: int,
    year: int,
    month: int,
    transport: earthdata.Transport,
    mapping,
    results_dir: str,
    tmp_dir_root: str,
) -> MonthResult:
    """Resume-aware month task: reuse an existing valid checkpoint, otherwise
    compute and atomically write a new one.
    """
    path = month_checkpoint_path(results_dir, year, month)

    if os.path.exists(path):
        existing = checkpoint.validate_checkpoint(path, water_year, year, month)
        if existing.ok:
            return MonthResult(water_year, year, month, ok=True, skipped_existing=True)

    rows, metadata = compute_month(water_year, year, month, transport, mapping, tmp_dir_root)
    checkpoint.write_checkpoint(path, rows, metadata)
    result = checkpoint.validate_checkpoint(path, water_year, year, month)
    return MonthResult(water_year, year, month, ok=result.ok, errors=result.errors)


@dataclass
class SchedulerReport:
    completed: list[tuple[int, int, int]] = field(default_factory=list)
    failed: list[tuple[int, int, int]] = field(default_factory=list)
    remaining: list[tuple[int, int, int]] = field(default_factory=list)
    paused_cleanly: bool = False


def run_scheduler(
    months: list[tuple[int, int, int]],
    run_one_month: Callable[[int, int, int], MonthResult],
    executor: concurrent.futures.Executor,
    max_workers: int = config.DEFAULT_MAX_WORKERS,
    max_runtime_minutes: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    poll_timeout: float = 0.05,
    print_fn: Callable[[str], None] = print,
) -> SchedulerReport:
    """Schedule month tasks up to `max_workers` concurrently.

    Stops submitting new months once `max_runtime_minutes` has elapsed,
    letting in-flight months finish (the run can therefore exceed the
    requested duration by one month-task runtime), then prints
    "paused cleanly". A month that raises or reports failure is requeued to
    the back of the queue, up to MAX_MONTH_RETRIES, after which it is
    reported as permanently failed.
    """
    queue: deque[tuple[int, int, int]] = deque(months)
    in_flight: dict[concurrent.futures.Future, tuple[int, int, int]] = {}
    retry_counts: dict[tuple[int, int, int], int] = {}
    completed: list[tuple[int, int, int]] = []
    failed: list[tuple[int, int, int]] = []

    start = monotonic()
    deadline = None if max_runtime_minutes is None else start + max_runtime_minutes * 60

    def deadline_passed() -> bool:
        return deadline is not None and monotonic() >= deadline

    while queue or in_flight:
        while queue and len(in_flight) < max_workers and not deadline_passed():
            month = queue.popleft()
            future = executor.submit(run_one_month, *month)
            in_flight[future] = month

        if not in_flight:
            break  # queue is non-empty only because the deadline stopped scheduling

        done, _ = concurrent.futures.wait(
            list(in_flight.keys()),
            timeout=poll_timeout,
            return_when=concurrent.futures.FIRST_COMPLETED,
        )
        for future in done:
            month = in_flight.pop(future)
            try:
                result = future.result()
                ok = result.ok
            except Exception:  # noqa: BLE001 - any worker exception is a month failure
                ok = False

            if ok:
                completed.append(month)
            else:
                retry_counts[month] = retry_counts.get(month, 0) + 1
                if retry_counts[month] > MAX_MONTH_RETRIES:
                    failed.append(month)
                else:
                    queue.append(month)

    paused_cleanly = bool(queue) and deadline_passed()
    if paused_cleanly:
        print_fn("paused cleanly")

    return SchedulerReport(
        completed=completed, failed=failed, remaining=list(queue), paused_cleanly=paused_cleanly
    )


_worker_transport = None
_worker_mapping = None


def _build_worker_transport_and_mapping(tmp_dir_root: str):
    """Build one authenticated session + static MODIS-to-MERRA mapping,
    for exclusive use by the current worker process. Mirrors
    cli.py's _bootstrap_mapping but lives here so it never needs to cross
    a process boundary (live sessions cannot be pickled).
    """
    from datetime import date

    import numpy as np

    from . import earthdata, regrid, worker

    session = earthdata.create_session()
    ftp_pool = earthdata.FtpSlotPool(config.FTP_SEMAPHORE_SLOTS)
    transport = earthdata.RealTransport(session, ftp_pool)

    bootstrap_date = date(config.WY_START - 1, 10, 1)
    raw = worker.fetch_day(bootstrap_date, transport, tmp_dir_root)
    x = np.concatenate([t.pixel_x_sinusoidal for t in raw.modscag_tiles])
    y = np.concatenate([t.pixel_y_sinusoidal for t in raw.modscag_tiles])
    lon, lat = regrid.transform_sinusoidal_to_lonlat(x, y)
    mapping = regrid.build_mapping(lon, lat)
    return transport, mapping


def _worker_initializer(tmp_dir_root: str) -> None:
    """ProcessPoolExecutor initializer: ignore SIGINT (parent stops submission
    while in-flight workers finish their current atomic checkpoint) and build
    the one-per-process session + static mapping in THIS process, so nothing
    unpicklable (sessions, locks) ever needs to cross into a worker.
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    global _worker_transport, _worker_mapping
    _worker_transport, _worker_mapping = _build_worker_transport_and_mapping(tmp_dir_root)


def run_one_month_worker(
    water_year: int, year: int, month: int, results_dir: str, tmp_dir_root: str
) -> MonthResult:
    """Top-level, picklable task entry point for ProcessPoolExecutor. Reads
    the per-process transport/mapping built by _worker_initializer instead
    of receiving them as arguments.
    """
    return run_month_task(
        water_year, year, month, _worker_transport, _worker_mapping, results_dir, tmp_dir_root
    )


def build_process_pool(
    max_workers: int = config.DEFAULT_MAX_WORKERS, tmp_dir_root: str | None = None
) -> concurrent.futures.ProcessPoolExecutor:
    return concurrent.futures.ProcessPoolExecutor(
        max_workers=max_workers, initializer=_worker_initializer, initargs=(tmp_dir_root,)
    )
