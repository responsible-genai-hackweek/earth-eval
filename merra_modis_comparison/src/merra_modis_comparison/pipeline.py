from __future__ import annotations

import calendar
import csv
import multiprocessing
import os
import signal
import tempfile
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from .checkpoints import (
    AGGREGATION,
    ERROR_SIGN,
    MERRA_PRODUCT,
    MODSCAG_PRODUCT,
    checkpoint_path,
    load_available_checkpoints,
    write_month_checkpoint,
)
from .config import RunConfig, season_for_month
from .metrics import StatsBlock, merge_blocks, metrics_for_slot, update_stats
from .products import (
    TileMapping,
    aggregate_modscag,
    archived_tiles_for_grid,
    authenticated_earthdata_session,
    build_tile_mapping,
    download_modscag,
    read_merra_frsno,
    tiles_for_grid,
)


COMMON_CSV_FIELDS = [
    "scope",
    "period",
    "water_year",
    "group_type",
    "group",
    "bias_pp",
    "mae_pp",
    "sum_weight",
    "sum_weighted_error",
    "sum_weighted_absolute_error",
    "n_cell_days",
    "n_days",
    "n_calendar_days",
    "n_missing_reference_days",
    "paired_modscag_pixel_days",
    "expected_modscag_pixel_days",
    "direct_observation_pixel_days",
    "support_fraction",
    "direct_observation_fraction",
    "domain",
    "error_sign",
    "merra_product",
    "modscag_product",
    "aggregation",
]
OVERALL_CSV_FIELDS = COMMON_CSV_FIELDS
PIXEL_CSV_FIELDS = [
    *COMMON_CSV_FIELDS[:5],
    "cell_id",
    "merra_latitude",
    "merra_longitude",
    "merra_latitude_index",
    "merra_longitude_index",
    *COMMON_CSV_FIELDS[5:],
]

MONTH_ORDER = (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9)
MONTH_LABELS = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}
SEASON_ORDER = ("SON", "DJF", "MAM", "JJA")
SEASON_MONTHS = {
    "SON": (9, 10, 11),
    "DJF": (12, 1, 2),
    "MAM": (3, 4, 5),
    "JJA": (6, 7, 8),
}


@dataclass(frozen=True)
class RunOutcome:
    complete: bool
    completed_months: int
    total_months: int
    overall_rows: list[dict[str, object]] | None = None
    pixel_rows: list[dict[str, object]] | None = None


_WORKER_CONFIG: RunConfig | None = None
_WORKER_SESSION: Any = None
_WORKER_MAPPINGS: dict[str, TileMapping] | None = None
_WORKER_ARCHIVE_TILES: tuple[str, ...] = ()
_WORKER_VALIDATED_TILES: set[str] | None = None
_WORKER_FTP_SEMAPHORE: Any = None


def _initialize_worker(config: RunConfig, ftp_semaphore: Any) -> None:
    global _WORKER_CONFIG
    global _WORKER_SESSION
    global _WORKER_MAPPINGS
    global _WORKER_ARCHIVE_TILES
    global _WORKER_VALIDATED_TILES
    global _WORKER_FTP_SEMAPHORE

    # Only the parent handles Ctrl-C. Workers finish their current month so an
    # interrupt cannot leave a partially trusted checkpoint under its final name.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    _WORKER_CONFIG = config
    _WORKER_SESSION = authenticated_earthdata_session()
    grid = config.target_grid
    _WORKER_ARCHIVE_TILES = archived_tiles_for_grid(grid)
    _WORKER_MAPPINGS = {
        tile: build_tile_mapping(None, tile, grid) for tile in tiles_for_grid(grid)
    }
    _WORKER_VALIDATED_TILES = set()
    _WORKER_FTP_SEMAPHORE = ftp_semaphore
    expected = sum(
        (mapping.expected_counts for mapping in _WORKER_MAPPINGS.values()),
        start=np.zeros(grid.size, dtype=np.int64),
    )
    if np.any(expected == 0):
        raise ValueError("one or more target cells have no mapped MODSCAG pixels")


def _validate_downloaded_mapping(tile: str, path: Path) -> None:
    if _WORKER_CONFIG is None or _WORKER_MAPPINGS is None:
        raise RuntimeError("worker was not initialized")
    expected = _WORKER_MAPPINGS[tile]
    actual = build_tile_mapping(path, tile, _WORKER_CONFIG.target_grid)
    if (
        actual.row_start != expected.row_start
        or actual.row_stop != expected.row_stop
        or actual.col_start != expected.col_start
        or actual.col_stop != expected.col_stop
        or not np.array_equal(actual.target_index, expected.target_index)
        or not np.array_equal(actual.expected_counts, expected.expected_counts)
    ):
        raise ValueError(f"computed mapping changed for {tile}")


def _process_month(year: int, month: int, checkpoint_directory: Path) -> str:
    if (
        _WORKER_CONFIG is None
        or _WORKER_MAPPINGS is None
        or _WORKER_VALIDATED_TILES is None
    ):
        raise RuntimeError("worker was not initialized")
    config = _WORKER_CONFIG
    grid = config.target_grid
    stats = StatsBlock.empty(grid.size)
    days_in_month = calendar.monthrange(year, month)[1]
    label = f"{year:04d}-{month:02d}"
    with tempfile.TemporaryDirectory(prefix=f"merra-modis-{label}-") as temporary:
        temporary_path = Path(temporary)
        for day_number in range(1, days_in_month + 1):
            day = date(year, month, day_number)
            paths: dict[str, Path] = {}
            try:
                merra = read_merra_frsno(
                    day, grid, _WORKER_SESSION, retries=config.retries
                )
                for tile in _WORKER_ARCHIVE_TILES:
                    if _WORKER_FTP_SEMAPHORE is None:
                        raise RuntimeError("worker FTP semaphore was not initialized")
                    with _WORKER_FTP_SEMAPHORE:
                        paths[tile] = download_modscag(
                            tile, day, temporary_path, retries=config.retries
                        )
                for tile, path in paths.items():
                    if tile not in _WORKER_VALIDATED_TILES:
                        _validate_downloaded_mapping(tile, path)
                        _WORKER_VALIDATED_TILES.add(tile)
                modscag, valid_pixels, expected_pixels, observed_pixels = (
                    aggregate_modscag(paths, _WORKER_MAPPINGS, grid)
                )
                support = np.divide(
                    valid_pixels,
                    expected_pixels,
                    out=np.zeros(grid.shape, dtype=np.float64),
                    where=expected_pixels > 0,
                )
                modscag[support < config.support_threshold] = np.nan
                paired = update_stats(
                    stats,
                    merra,
                    modscag,
                    valid_pixels,
                    expected_pixels,
                    observed_pixels,
                )
                if not paired:
                    print(
                        f"worker {os.getpid()}: excluded {day.isoformat()} "
                        "(no target cell met MODSCAG support requirements)",
                        flush=True,
                    )
            finally:
                for path in paths.values():
                    path.unlink(missing_ok=True)
            if day_number == 1 or day_number % 10 == 0 or day_number == days_in_month:
                print(
                    f"worker {os.getpid()}: {label} completed "
                    f"{day_number}/{days_in_month} days",
                    flush=True,
                )
    output = checkpoint_path(checkpoint_directory, year, month)
    write_month_checkpoint(stats, year, month, config, output)
    return label


def preflight(config: RunConfig) -> None:
    config.validate()
    grid = config.target_grid
    geometric_tiles = tiles_for_grid(grid)
    archive_tiles = archived_tiles_for_grid(grid)
    if not archive_tiles:
        raise ValueError("no STC-MODSCAG archive tile intersects the target grid")
    if len(config.dates) != sum(
        calendar.monthrange(year, month)[1]
        for year, month in config.calendar_months
    ):
        raise ValueError("date and calendar-month inventories disagree")
    session = authenticated_earthdata_session()
    reprocessed_samples = (date(2020, 9, 1), date(2021, 6, 1))
    sample_days = [config.start_date, config.end_date]
    sample_days.extend(
        day for day in reprocessed_samples if config.start_date <= day <= config.end_date
    )
    for sample_day in dict.fromkeys(sample_days):
        sample = read_merra_frsno(
            sample_day,
            grid,
            session,
            retries=config.retries,
            validate_coordinates=True,
        )
        if sample.shape != grid.shape or not np.isfinite(sample).any():
            raise ValueError(
                f"MERRA-2 preflight returned no usable FRSNO on {sample_day}"
            )
    print(
        "preflight passed: "
        f"{len(config.dates)} dates, {len(config.calendar_months)} months, "
        f"{grid.size} MERRA-2 cells, archive tiles={','.join(archive_tiles)}, "
        f"support geometry={','.join(geometric_tiles)}, "
        "FRSNO index 15 (15:00-16:00 UTC; timestamp 15:30 UTC)",
        flush=True,
    )


def _run_missing_months(
    config: RunConfig,
    checkpoint_directory: Path,
    months: list[tuple[int, int]],
    already_complete: int,
    max_runtime_minutes: float | None,
) -> None:
    if not months:
        return
    deadline = (
        None
        if max_runtime_minutes is None
        else time.monotonic() + max_runtime_minutes * 60.0
    )
    queue = deque(months)
    attempts = {period: 0 for period in months}
    failures: dict[tuple[int, int], BaseException] = {}
    total = len(config.calendar_months)
    completed_this_run = 0
    stop_submitting = False
    context = multiprocessing.get_context("spawn")
    ftp_semaphore = context.BoundedSemaphore(config.ftp_connections)
    executor = ProcessPoolExecutor(
        max_workers=min(config.workers, len(months)),
        mp_context=context,
        initializer=_initialize_worker,
        initargs=(config, ftp_semaphore),
    )
    futures: dict[Future[str], tuple[int, int]] = {}

    def fill_worker_slots() -> None:
        nonlocal stop_submitting
        if deadline is not None and time.monotonic() >= deadline:
            stop_submitting = True
        while not stop_submitting and queue and len(futures) < config.workers:
            period = queue.popleft()
            attempts[period] += 1
            year, month = period
            future = executor.submit(
                _process_month, year, month, checkpoint_directory
            )
            futures[future] = period

    try:
        fill_worker_slots()
        while futures:
            if deadline is not None and time.monotonic() >= deadline:
                stop_submitting = True
            done, _ = wait(
                futures,
                timeout=1.0 if deadline is not None else None,
                return_when=FIRST_COMPLETED,
            )
            if not done:
                continue
            for future in done:
                period = futures.pop(future)
                try:
                    label = future.result()
                except BaseException as exc:
                    if attempts[period] < config.month_attempts:
                        # Put transient failures at the back so a busy archive
                        # has time to recover before the full month is retried.
                        queue.append(period)
                        if not stop_submitting:
                            print(
                                f"month {period[0]:04d}-{period[1]:02d} failed; "
                                f"retrying attempt {attempts[period] + 1}/"
                                f"{config.month_attempts}: {exc}",
                                flush=True,
                            )
                    else:
                        failures[period] = exc
                        stop_submitting = True
                else:
                    completed_this_run += 1
                    print(
                        f"checkpoint saved: {label} "
                        f"({already_complete + completed_this_run}/{total} months)",
                        flush=True,
                    )
            fill_worker_slots()
    except KeyboardInterrupt:
        stop_submitting = True
        queue.clear()
        for future in futures:
            future.cancel()
        print(
            "interrupt received; waiting for in-flight calendar months to finish "
            "their atomic checkpoints",
            flush=True,
        )
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    if failures:
        period = sorted(failures)[0]
        raise RuntimeError(
            f"calendar month {period[0]:04d}-{period[1]:02d} failed after "
            f"{attempts[period]} attempts; completed checkpoints were preserved"
        ) from failures[period]
    if queue:
        print(
            f"runtime limit reached; {len(queue)} unscheduled months remain. "
            "Rerun the same command to resume.",
            flush=True,
        )


def _month_period_for_water_year(water_year: int, month: int) -> tuple[int, int]:
    return (water_year - 1 if month >= 10 else water_year, month)


def _metadata_row(
    stats: StatsBlock,
    slot: int,
    config: RunConfig,
    scope: str,
    period: str,
    water_year: int | str,
    group_type: str,
    group: str,
) -> dict[str, object]:
    return {
        "scope": scope,
        "period": period,
        "water_year": water_year,
        "group_type": group_type,
        "group": group,
        **metrics_for_slot(stats, slot),
        "domain": config.domain_label,
        "error_sign": ERROR_SIGN,
        "merra_product": MERRA_PRODUCT,
        "modscag_product": MODSCAG_PRODUCT,
        "aggregation": AGGREGATION,
    }


def _append_group_rows(
    overall_rows: list[dict[str, object]],
    pixel_rows: list[dict[str, object]],
    stats: StatsBlock,
    config: RunConfig,
    scope: str,
    period: str,
    water_year: int | str,
    group_type: str,
    group: str,
) -> None:
    grid = config.target_grid
    overall_rows.append(
        _metadata_row(
            stats,
            stats.domain_slot,
            config,
            scope,
            period,
            water_year,
            group_type,
            group,
        )
    )
    for slot in range(grid.size):
        pixel_rows.append(
            {
                **_metadata_row(
                    stats,
                    slot,
                    config,
                    scope,
                    period,
                    water_year,
                    group_type,
                    group,
                ),
                **grid.cell_metadata(slot),
            }
        )


def build_final_rows(
    checkpoints: dict[tuple[int, int], StatsBlock], config: RunConfig
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    expected_periods = set(config.calendar_months)
    if set(checkpoints) != expected_periods:
        missing = sorted(expected_periods - set(checkpoints))
        raise ValueError(f"cannot finalize with missing calendar months: {missing[:3]}")
    overall_rows: list[dict[str, object]] = []
    pixel_rows: list[dict[str, object]] = []

    for water_year in config.water_years:
        period = f"WY{water_year}"
        for month in MONTH_ORDER:
            stats = checkpoints[_month_period_for_water_year(water_year, month)]
            _append_group_rows(
                overall_rows,
                pixel_rows,
                stats,
                config,
                "water_year",
                period,
                water_year,
                "month",
                MONTH_LABELS[month],
            )
        for season in SEASON_ORDER:
            stats = merge_blocks(
                [
                    checkpoints[_month_period_for_water_year(water_year, month)]
                    for month in SEASON_MONTHS[season]
                ]
            )
            _append_group_rows(
                overall_rows,
                pixel_rows,
                stats,
                config,
                "water_year",
                period,
                water_year,
                "season",
                season,
            )

    climatology_period = (
        f"WY{config.start_water_year}-WY{config.end_water_year}"
    )
    for month in MONTH_ORDER:
        stats = merge_blocks(
            [
                checkpoints[_month_period_for_water_year(water_year, month)]
                for water_year in config.water_years
            ]
        )
        _append_group_rows(
            overall_rows,
            pixel_rows,
            stats,
            config,
            "climatology",
            climatology_period,
            "",
            "month",
            MONTH_LABELS[month],
        )
    for season in SEASON_ORDER:
        stats = merge_blocks(
            [
                checkpoints[_month_period_for_water_year(water_year, month)]
                for water_year in config.water_years
                for month in SEASON_MONTHS[season]
            ]
        )
        _append_group_rows(
            overall_rows,
            pixel_rows,
            stats,
            config,
            "climatology",
            climatology_period,
            "",
            "season",
            season,
        )

    expected_overall = len(config.water_years) * 16 + 16
    expected_pixel = expected_overall * config.target_grid.size
    if len(overall_rows) != expected_overall or len(pixel_rows) != expected_pixel:
        raise ValueError("final row counts differ from the configured experiment")
    return overall_rows, pixel_rows


def run(
    config: RunConfig,
    checkpoint_directory: Path,
    max_runtime_minutes: float | None = None,
) -> RunOutcome:
    config.validate()
    if max_runtime_minutes is not None and max_runtime_minutes <= 0:
        raise ValueError("maximum runtime must be greater than zero minutes")
    checkpoint_directory = checkpoint_directory.resolve()
    checkpoint_directory.mkdir(parents=True, exist_ok=True)
    existing, invalid = load_available_checkpoints(config, checkpoint_directory)
    for period, reason in sorted(invalid.items()):
        print(
            f"checkpoint {period[0]:04d}-{period[1]:02d} is invalid and will be "
            f"recomputed: {reason}",
            flush=True,
        )
    missing = [period for period in config.calendar_months if period not in existing]
    print(
        f"resume inventory: {len(existing)}/{len(config.calendar_months)} "
        "validated monthly checkpoints",
        flush=True,
    )
    if missing:
        preflight(config)
        _run_missing_months(
            config,
            checkpoint_directory,
            missing,
            len(existing),
            max_runtime_minutes,
        )
    complete, invalid_after = load_available_checkpoints(config, checkpoint_directory)
    if invalid_after:
        period = sorted(invalid_after)[0]
        raise RuntimeError(
            f"checkpoint {period[0]:04d}-{period[1]:02d} failed post-write validation: "
            f"{invalid_after[period]}"
        )
    if len(complete) != len(config.calendar_months):
        return RunOutcome(
            complete=False,
            completed_months=len(complete),
            total_months=len(config.calendar_months),
        )
    overall_rows, pixel_rows = build_final_rows(complete, config)
    return RunOutcome(
        complete=True,
        completed_months=len(complete),
        total_months=len(config.calendar_months),
        overall_rows=overall_rows,
        pixel_rows=pixel_rows,
    )


def write_csv(
    rows: list[dict[str, object]], output: Path, fieldnames: list[str]
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            writer = csv.DictWriter(temporary, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.replace(output)
        output.chmod(0o644)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
