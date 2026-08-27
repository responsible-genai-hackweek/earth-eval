from __future__ import annotations

import calendar
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

from .era_products import (
    MonthlyModelField,
    authenticated_cds_client,
    load_reanalysis_field,
    retrieve_reanalysis_field,
)
from .pipeline import (
    MONTH_LABELS,
    MONTH_ORDER,
    SEASON_MONTHS,
    SEASON_ORDER,
)
from .products import (
    TileMapping,
    aggregate_modscag,
    archived_tiles_for_grid,
    build_tile_mapping,
    download_modscag,
    tiles_for_grid,
)
from .reanalysis_checkpoints import (
    MODEL_TIME,
    REFERENCE_PRODUCT,
    aggregation,
    checkpoint_path,
    error_sign,
    load_available_checkpoints,
    write_month_checkpoint,
)
from .reanalysis_config import (
    MODEL_SPECS,
    ReanalysisModelSpec,
    ReanalysisRunConfig,
    month_dates,
)
from .reanalysis_metrics import (
    ReanalysisStatsBlock,
    merge_reanalysis_blocks,
    reanalysis_metrics_for_slot,
    update_reanalysis_stats,
)


METRIC_CSV_FIELDS = [
    "bias_pp",
    "mae_pp",
    "normalized_mean_bias_pct",
    "normalized_mae_pct",
    "model_fsca_mean",
    "modscag_fsca_mean",
    "sum_weight",
    "sum_weighted_modscag",
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
]
COMMON_CSV_FIELDS = [
    "scope",
    "period",
    "water_year",
    "group_type",
    "group",
    "model_id",
    *METRIC_CSV_FIELDS,
    "domain",
    "error_sign",
    "model_product",
    "model_variable",
    "model_time",
    "reference_product",
    "aggregation",
]
OVERALL_CSV_FIELDS = COMMON_CSV_FIELDS
PIXEL_CSV_FIELDS = [
    *COMMON_CSV_FIELDS[:6],
    "cell_id",
    "target_latitude",
    "target_longitude",
    "target_row",
    "target_column",
    *COMMON_CSV_FIELDS[6:],
]


@dataclass(frozen=True)
class ReanalysisRunOutcome:
    complete: bool
    completed_checkpoints: int
    total_checkpoints: int
    overall_rows: dict[str, list[dict[str, object]]] | None = None
    pixel_rows: dict[str, list[dict[str, object]]] | None = None


_WORKER_CONFIG: ReanalysisRunConfig | None = None
_WORKER_CDS_CLIENT: Any = None
_WORKER_MAPPINGS: dict[str, dict[str, TileMapping]] | None = None
_WORKER_ARCHIVE_TILES: dict[str, tuple[str, ...]] | None = None
_WORKER_VALIDATED_TILES: set[tuple[str, str]] | None = None
_WORKER_FTP_SEMAPHORE: Any = None
_WORKER_CDS_SEMAPHORE: Any = None


def _grid_mappings(
    config: ReanalysisRunConfig, spec: ReanalysisModelSpec
) -> tuple[dict[str, TileMapping], tuple[str, ...]]:
    grid = config.target_grid(spec.model_id)
    geometric_tiles = tiles_for_grid(grid)
    archive_tiles = archived_tiles_for_grid(grid)
    if not archive_tiles:
        raise ValueError(
            f"no STC-MODSCAG archive tile intersects the {spec.display_name} grid"
        )
    mappings = {
        tile: build_tile_mapping(None, tile, grid) for tile in geometric_tiles
    }
    all_expected = sum(
        (mapping.expected_counts for mapping in mappings.values()),
        start=np.zeros(grid.size, dtype=np.int64),
    )
    archived_expected = sum(
        (mappings[tile].expected_counts for tile in archive_tiles),
        start=np.zeros(grid.size, dtype=np.int64),
    )
    if np.any(all_expected == 0):
        raise ValueError(
            f"one or more {spec.display_name} cells have no mapped MODSCAG pixels"
        )
    maximum_archive_support = np.divide(
        archived_expected,
        all_expected,
        out=np.zeros(grid.size, dtype=np.float64),
        where=all_expected > 0,
    )
    if not np.any(maximum_archive_support >= config.support_threshold):
        raise ValueError(
            f"no {spec.display_name} cell can meet the configured MODSCAG support rule"
        )
    return mappings, archive_tiles


def _initialize_worker(
    config: ReanalysisRunConfig, ftp_semaphore: Any, cds_semaphore: Any
) -> None:
    global _WORKER_CONFIG
    global _WORKER_CDS_CLIENT
    global _WORKER_MAPPINGS
    global _WORKER_ARCHIVE_TILES
    global _WORKER_VALIDATED_TILES
    global _WORKER_FTP_SEMAPHORE
    global _WORKER_CDS_SEMAPHORE

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    _WORKER_CONFIG = config
    _WORKER_CDS_CLIENT = authenticated_cds_client()
    _WORKER_MAPPINGS = {}
    _WORKER_ARCHIVE_TILES = {}
    for spec in config.model_specs:
        mappings, archive_tiles = _grid_mappings(config, spec)
        _WORKER_MAPPINGS[spec.model_id] = mappings
        _WORKER_ARCHIVE_TILES[spec.model_id] = archive_tiles
    _WORKER_VALIDATED_TILES = set()
    _WORKER_FTP_SEMAPHORE = ftp_semaphore
    _WORKER_CDS_SEMAPHORE = cds_semaphore


def _validate_downloaded_mapping(
    spec: ReanalysisModelSpec, tile: str, path: Path
) -> None:
    if _WORKER_CONFIG is None or _WORKER_MAPPINGS is None:
        raise RuntimeError("worker was not initialized")
    expected = _WORKER_MAPPINGS[spec.model_id][tile]
    actual = build_tile_mapping(
        path, tile, _WORKER_CONFIG.target_grid(spec.model_id)
    )
    if (
        actual.row_start != expected.row_start
        or actual.row_stop != expected.row_stop
        or actual.col_start != expected.col_start
        or actual.col_stop != expected.col_stop
        or not np.array_equal(actual.target_index, expected.target_index)
        or not np.array_equal(actual.expected_counts, expected.expected_counts)
    ):
        raise ValueError(
            f"computed MODSCAG mapping changed for {spec.display_name} {tile}"
        )


def _load_monthly_model_fields(
    specs: tuple[ReanalysisModelSpec, ...],
    days: tuple[date, ...],
    directory: Path,
) -> dict[str, MonthlyModelField]:
    if _WORKER_CONFIG is None or _WORKER_CDS_CLIENT is None:
        raise RuntimeError("worker CDS access was not initialized")
    fields: dict[str, MonthlyModelField] = {}
    for spec in specs:
        if _WORKER_CDS_SEMAPHORE is None:
            raise RuntimeError("worker CDS semaphore was not initialized")
        with _WORKER_CDS_SEMAPHORE:
            path = retrieve_reanalysis_field(
                _WORKER_CDS_CLIENT,
                spec,
                days,
                _WORKER_CONFIG,
                directory,
                retries=_WORKER_CONFIG.retries,
            )
        fields[spec.model_id] = load_reanalysis_field(
            path,
            spec,
            _WORKER_CONFIG.target_grid(spec.model_id),
            days,
        )
    return fields


def _process_month(
    year: int,
    month: int,
    checkpoint_directories: dict[str, Path],
    model_ids: tuple[str, ...],
) -> tuple[str, tuple[str, ...]]:
    if (
        _WORKER_CONFIG is None
        or _WORKER_MAPPINGS is None
        or _WORKER_ARCHIVE_TILES is None
        or _WORKER_VALIDATED_TILES is None
    ):
        raise RuntimeError("worker was not initialized")
    config = _WORKER_CONFIG
    specs = tuple(MODEL_SPECS[model_id] for model_id in model_ids)
    stats = {
        spec.model_id: ReanalysisStatsBlock.empty(
            config.target_grid(spec.model_id).size
        )
        for spec in specs
    }
    days = month_dates(year, month)
    label = f"{year:04d}-{month:02d}"
    with tempfile.TemporaryDirectory(
        prefix=f"era-modis-{label}-"
    ) as temporary:
        temporary_path = Path(temporary)
        model_fields = _load_monthly_model_fields(specs, days, temporary_path)
        required_tiles = tuple(
            sorted(
                {
                    tile
                    for spec in specs
                    for tile in _WORKER_ARCHIVE_TILES[spec.model_id]
                }
            )
        )
        for day_number, day in enumerate(days, start=1):
            paths: dict[str, Path] = {}
            try:
                for tile in required_tiles:
                    if _WORKER_FTP_SEMAPHORE is None:
                        raise RuntimeError("worker FTP semaphore was not initialized")
                    with _WORKER_FTP_SEMAPHORE:
                        paths[tile] = download_modscag(
                            tile, day, temporary_path, retries=config.retries
                        )
                for spec in specs:
                    grid = config.target_grid(spec.model_id)
                    model_paths = {
                        tile: paths[tile]
                        for tile in _WORKER_ARCHIVE_TILES[spec.model_id]
                    }
                    for tile, path in model_paths.items():
                        validation_key = (spec.model_id, tile)
                        if validation_key not in _WORKER_VALIDATED_TILES:
                            _validate_downloaded_mapping(spec, tile, path)
                            _WORKER_VALIDATED_TILES.add(validation_key)
                    reference, valid, expected, observed = aggregate_modscag(
                        model_paths,
                        _WORKER_MAPPINGS[spec.model_id],
                        grid,
                    )
                    support = np.divide(
                        valid,
                        expected,
                        out=np.zeros(grid.shape, dtype=np.float64),
                        where=expected > 0,
                    )
                    reference[support < config.support_threshold] = np.nan
                    paired = update_reanalysis_stats(
                        stats[spec.model_id],
                        model_fields[spec.model_id].for_date(day),
                        reference,
                        valid,
                        expected,
                        observed,
                    )
                    if not paired:
                        print(
                            f"worker {os.getpid()}: excluded {spec.display_name} "
                            f"{day.isoformat()} (no target cell met pairing rules)",
                            flush=True,
                        )
            finally:
                for path in paths.values():
                    path.unlink(missing_ok=True)
            if day_number == 1 or day_number % 10 == 0 or day_number == len(days):
                print(
                    f"worker {os.getpid()}: {label} "
                    f"[{','.join(model_ids)}] completed {day_number}/{len(days)} days",
                    flush=True,
                )

    for spec in specs:
        output = checkpoint_path(
            checkpoint_directories[spec.model_id], year, month
        )
        write_month_checkpoint(
            stats[spec.model_id], year, month, config, spec, output
        )
    return label, model_ids


def preflight(config: ReanalysisRunConfig) -> None:
    config.validate()
    client = authenticated_cds_client()
    if len(config.dates) != sum(
        calendar.monthrange(year, month)[1]
        for year, month in config.calendar_months
    ):
        raise ValueError("date and calendar-month inventories disagree")
    eligible_cells: dict[str, int] = {}
    for spec in config.model_specs:
        mappings, archive_tiles = _grid_mappings(config, spec)
        grid = config.target_grid(spec.model_id)
        all_expected = sum(
            (mapping.expected_counts for mapping in mappings.values()),
            start=np.zeros(grid.size, dtype=np.int64),
        )
        archived_expected = sum(
            (mappings[tile].expected_counts for tile in archive_tiles),
            start=np.zeros(grid.size, dtype=np.int64),
        )
        maximum_support = np.divide(
            archived_expected,
            all_expected,
            out=np.zeros(grid.size, dtype=np.float64),
            where=all_expected > 0,
        )
        eligible_cells[spec.model_id] = int(
            np.count_nonzero(maximum_support >= config.support_threshold)
        )
    sample_day = config.start_date
    with tempfile.TemporaryDirectory(prefix="era-modis-preflight-") as temporary:
        directory = Path(temporary)
        for spec in config.model_specs:
            path = retrieve_reanalysis_field(
                client,
                spec,
                (sample_day,),
                config,
                directory,
                retries=config.retries,
            )
            field = load_reanalysis_field(
                path,
                spec,
                config.target_grid(spec.model_id),
                (sample_day,),
            )
            if field.values.shape != (1, *config.target_grid(spec.model_id).shape):
                raise ValueError(
                    f"unexpected {spec.display_name} preflight array shape"
                )
            if not np.isfinite(field.values).any():
                raise ValueError(
                    f"{spec.display_name} preflight returned no usable snow cover"
                )
    grid_summary = ", ".join(
        f"{spec.display_name}={config.target_grid(spec.model_id).size} cells "
        f"at {spec.longitude_step:g} degrees "
        f"({eligible_cells[spec.model_id]} can meet archive support)"
        for spec in config.model_specs
    )
    print(
        "preflight passed: "
        f"{len(config.dates)} dates, {len(config.calendar_months)} months, "
        f"{grid_summary}; hourly snow_cover at 15:00 UTC",
        flush=True,
    )


def _run_missing_months(
    config: ReanalysisRunConfig,
    checkpoint_directories: dict[str, Path],
    tasks: list[tuple[int, int, tuple[str, ...]]],
    already_complete: int,
    max_runtime_minutes: float | None,
) -> None:
    if not tasks:
        return
    deadline = (
        None
        if max_runtime_minutes is None
        else time.monotonic() + max_runtime_minutes * 60.0
    )
    queue = deque(tasks)
    attempts = {(year, month): 0 for year, month, _ in tasks}
    failures: dict[tuple[int, int], BaseException] = {}
    total = len(config.calendar_months) * len(config.model_ids)
    completed_this_run = 0
    stop_submitting = False
    context = multiprocessing.get_context("spawn")
    ftp_semaphore = context.BoundedSemaphore(config.ftp_connections)
    cds_semaphore = context.BoundedSemaphore(config.cds_connections)
    executor = ProcessPoolExecutor(
        max_workers=min(config.workers, len(tasks)),
        mp_context=context,
        initializer=_initialize_worker,
        initargs=(config, ftp_semaphore, cds_semaphore),
    )
    futures: dict[
        Future[tuple[str, tuple[str, ...]]], tuple[int, int, tuple[str, ...]]
    ] = {}

    def fill_worker_slots() -> None:
        nonlocal stop_submitting
        if deadline is not None and time.monotonic() >= deadline:
            stop_submitting = True
        while not stop_submitting and queue and len(futures) < config.workers:
            task = queue.popleft()
            year, month, model_ids = task
            attempts[(year, month)] += 1
            future = executor.submit(
                _process_month,
                year,
                month,
                checkpoint_directories,
                model_ids,
            )
            futures[future] = task

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
                year, month, model_ids = futures.pop(future)
                period = (year, month)
                try:
                    label, saved_models = future.result()
                except BaseException as exc:
                    if attempts[period] < config.month_attempts:
                        queue.append((year, month, model_ids))
                        if not stop_submitting:
                            print(
                                f"month {year:04d}-{month:02d} "
                                f"[{','.join(model_ids)}] failed; retrying attempt "
                                f"{attempts[period] + 1}/{config.month_attempts}: {exc}",
                                flush=True,
                            )
                    else:
                        failures[period] = exc
                        stop_submitting = True
                else:
                    completed_this_run += len(saved_models)
                    print(
                        f"checkpoints saved: {label} "
                        f"[{','.join(saved_models)}] "
                        f"({already_complete + completed_this_run}/{total})",
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
            "their atomic statistics checkpoints",
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
            f"runtime limit reached; {len(queue)} unscheduled month tasks remain. "
            "Rerun the same command to resume.",
            flush=True,
        )


def _month_period_for_water_year(water_year: int, month: int) -> tuple[int, int]:
    return (water_year - 1 if month >= 10 else water_year, month)


def _metadata_row(
    stats: ReanalysisStatsBlock,
    slot: int,
    config: ReanalysisRunConfig,
    spec: ReanalysisModelSpec,
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
        "model_id": spec.model_id,
        **reanalysis_metrics_for_slot(stats, slot),
        "domain": config.domain_label,
        "error_sign": error_sign(spec),
        "model_product": spec.product_description,
        "model_variable": spec.variable,
        "model_time": MODEL_TIME,
        "reference_product": REFERENCE_PRODUCT,
        "aggregation": aggregation(spec),
    }


def _append_group_rows(
    overall_rows: list[dict[str, object]],
    pixel_rows: list[dict[str, object]],
    stats: ReanalysisStatsBlock,
    config: ReanalysisRunConfig,
    spec: ReanalysisModelSpec,
    scope: str,
    period: str,
    water_year: int | str,
    group_type: str,
    group: str,
) -> None:
    grid = config.target_grid(spec.model_id)
    overall_rows.append(
        _metadata_row(
            stats,
            stats.domain_slot,
            config,
            spec,
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
                    spec,
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
    checkpoints: dict[tuple[int, int], ReanalysisStatsBlock],
    config: ReanalysisRunConfig,
    spec: ReanalysisModelSpec,
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
                spec,
                "water_year",
                period,
                water_year,
                "month",
                MONTH_LABELS[month],
            )
        for season in SEASON_ORDER:
            stats = merge_reanalysis_blocks(
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
                spec,
                "water_year",
                period,
                water_year,
                "season",
                season,
            )

    climatology_period = f"WY{config.start_water_year}-WY{config.end_water_year}"
    for month in MONTH_ORDER:
        stats = merge_reanalysis_blocks(
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
            spec,
            "climatology",
            climatology_period,
            "",
            "month",
            MONTH_LABELS[month],
        )
    for season in SEASON_ORDER:
        stats = merge_reanalysis_blocks(
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
            spec,
            "climatology",
            climatology_period,
            "",
            "season",
            season,
        )

    expected_overall = len(config.water_years) * 16 + 16
    expected_pixel = expected_overall * config.target_grid(spec.model_id).size
    if len(overall_rows) != expected_overall or len(pixel_rows) != expected_pixel:
        raise ValueError("final row counts differ from the configured experiment")
    return overall_rows, pixel_rows


def run(
    config: ReanalysisRunConfig,
    checkpoint_directories: dict[str, Path],
    max_runtime_minutes: float | None = None,
) -> ReanalysisRunOutcome:
    config.validate()
    if max_runtime_minutes is not None and max_runtime_minutes <= 0:
        raise ValueError("maximum runtime must be greater than zero minutes")
    if set(checkpoint_directories) != set(config.model_ids):
        raise ValueError("checkpoint directories must match configured models")
    checkpoint_directories = {
        model_id: directory.resolve()
        for model_id, directory in checkpoint_directories.items()
    }
    for directory in checkpoint_directories.values():
        directory.mkdir(parents=True, exist_ok=True)

    inventories: dict[str, dict[tuple[int, int], ReanalysisStatsBlock]] = {}
    existing_count = 0
    for spec in config.model_specs:
        existing, invalid = load_available_checkpoints(
            config, spec, checkpoint_directories[spec.model_id]
        )
        inventories[spec.model_id] = existing
        existing_count += len(existing)
        for period, reason in sorted(invalid.items()):
            print(
                f"{spec.model_id} checkpoint {period[0]:04d}-{period[1]:02d} "
                f"is invalid and will be recomputed: {reason}",
                flush=True,
            )
    total = len(config.calendar_months) * len(config.model_ids)
    print(
        f"resume inventory: {existing_count}/{total} validated model-month "
        "statistics checkpoints",
        flush=True,
    )
    tasks = [
        (
            year,
            month,
            tuple(
                model_id
                for model_id in config.model_ids
                if (year, month) not in inventories[model_id]
            ),
        )
        for year, month in config.calendar_months
    ]
    tasks = [task for task in tasks if task[2]]
    if tasks:
        preflight(config)
        _run_missing_months(
            config,
            checkpoint_directories,
            tasks,
            existing_count,
            max_runtime_minutes,
        )

    completed: dict[str, dict[tuple[int, int], ReanalysisStatsBlock]] = {}
    completed_count = 0
    for spec in config.model_specs:
        valid, invalid = load_available_checkpoints(
            config, spec, checkpoint_directories[spec.model_id]
        )
        if invalid:
            period = sorted(invalid)[0]
            raise RuntimeError(
                f"{spec.model_id} checkpoint {period[0]:04d}-{period[1]:02d} "
                f"failed post-write validation: {invalid[period]}"
            )
        completed[spec.model_id] = valid
        completed_count += len(valid)
    if completed_count != total:
        return ReanalysisRunOutcome(
            complete=False,
            completed_checkpoints=completed_count,
            total_checkpoints=total,
        )

    overall_rows: dict[str, list[dict[str, object]]] = {}
    pixel_rows: dict[str, list[dict[str, object]]] = {}
    for spec in config.model_specs:
        overall, pixels = build_final_rows(
            completed[spec.model_id], config, spec
        )
        overall_rows[spec.model_id] = overall
        pixel_rows[spec.model_id] = pixels
    return ReanalysisRunOutcome(
        complete=True,
        completed_checkpoints=completed_count,
        total_checkpoints=total,
        overall_rows=overall_rows,
        pixel_rows=pixel_rows,
    )
