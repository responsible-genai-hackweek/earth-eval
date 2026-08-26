from __future__ import annotations

import calendar
import csv
import hashlib
import json
import multiprocessing
import os
import signal
import tempfile
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass, fields
from datetime import date
from pathlib import Path

import numpy as np

from .checkpoints import AGGREGATION, MODSCAG_PRODUCT
from .config import RunConfig
from .products import (
    TileMapping,
    aggregate_modscag,
    archived_tiles_for_grid,
    build_tile_mapping,
    download_modscag,
    tiles_for_grid,
)


MODIS_CHECKPOINT_SCHEMA = "1"
MODIS_FLOAT_FIELDS = ("sum_w", "sum_w_fsca")
MODIS_INTEGER_FIELDS = (
    "valid_pixels",
    "expected_pixels",
    "observed_pixels",
    "n_cell_days",
    "n_days",
    "n_calendar_days",
)
MODIS_STAT_FIELDS = MODIS_FLOAT_FIELDS + MODIS_INTEGER_FIELDS
SELECTED_WATER_YEARS = (2011, 2017, 2019, 2023, 2012, 2013, 2015, 2018)
SELECTED_MONTHS = (11, 12, 1, 2, 3, 4, 5)
MODIS_CHECKPOINT_FIELDS = [
    "checkpoint_schema",
    "config_fingerprint",
    "calendar_month",
    "level",
    "slot",
    "cell_id",
    *MODIS_STAT_FIELDS,
    "mean_modis_fsca_pct",
    "domain",
    "modscag_product",
    "aggregation",
]


class InvalidModisCheckpoint(ValueError):
    pass


@dataclass
class ModisStatsBlock:
    sum_w: np.ndarray
    sum_w_fsca: np.ndarray
    valid_pixels: np.ndarray
    expected_pixels: np.ndarray
    observed_pixels: np.ndarray
    n_cell_days: np.ndarray
    n_days: np.ndarray
    n_calendar_days: np.ndarray

    @classmethod
    def empty(cls, n_cells: int) -> "ModisStatsBlock":
        size = n_cells + 1
        floats = [np.zeros(size, dtype=np.float64) for _ in MODIS_FLOAT_FIELDS]
        integers = [
            np.zeros(size, dtype=np.int64) for _ in MODIS_INTEGER_FIELDS
        ]
        return cls(*floats, *integers)

    @property
    def size(self) -> int:
        return int(self.sum_w.size)

    @property
    def n_cells(self) -> int:
        return self.size - 1

    @property
    def domain_slot(self) -> int:
        return self.n_cells

    def merge(self, other: "ModisStatsBlock") -> None:
        if other.size != self.size:
            raise ValueError("cannot merge MODIS blocks with different sizes")
        for item in fields(self):
            getattr(self, item.name)[:] += getattr(other, item.name)

    def validate(self, expected_calendar_days: int | None = None) -> None:
        shapes = {getattr(self, name).shape for name in MODIS_STAT_FIELDS}
        if shapes != {(self.size,)}:
            raise ValueError("MODIS statistics arrays have inconsistent shapes")
        for name in MODIS_FLOAT_FIELDS:
            if not np.isfinite(getattr(self, name)).all():
                raise ValueError(f"MODIS field {name} contains non-finite values")
        for name in MODIS_INTEGER_FIELDS:
            if np.any(getattr(self, name) < 0):
                raise ValueError(f"MODIS field {name} contains negative values")
        if np.any(self.sum_w_fsca < 0) or np.any(
            self.sum_w_fsca > self.sum_w + 1e-8
        ):
            raise ValueError("weighted MODIS fSCA lies outside [0, sum_w]")
        if not np.allclose(self.sum_w, self.valid_pixels, rtol=0, atol=1e-8):
            raise ValueError("MODIS weights do not match valid pixel counts")
        if np.any(self.valid_pixels > self.expected_pixels):
            raise ValueError("valid MODIS support exceeds expected support")
        if np.any(self.observed_pixels > self.valid_pixels):
            raise ValueError("direct MODIS observations exceed valid support")
        if np.any(self.n_days > self.n_calendar_days):
            raise ValueError("MODIS valid-day count exceeds calendar days")
        if np.any(self.n_cell_days[: self.n_cells] != self.n_days[: self.n_cells]):
            raise ValueError("MODIS cell-day and day counts disagree")
        if expected_calendar_days is not None and np.any(
            self.n_calendar_days != expected_calendar_days
        ):
            raise ValueError("MODIS checkpoint has the wrong calendar-day count")
        domain = self.domain_slot
        for name in (
            *MODIS_FLOAT_FIELDS,
            "valid_pixels",
            "expected_pixels",
            "observed_pixels",
            "n_cell_days",
        ):
            values = getattr(self, name)
            expected = values[:domain].sum()
            matches = (
                np.isclose(values[domain], expected, rtol=1e-12, atol=1e-8)
                if name in MODIS_FLOAT_FIELDS
                else values[domain] == expected
            )
            if not matches:
                raise ValueError(f"domain MODIS {name} does not equal cell sum")


def update_modis_stats(
    stats: ModisStatsBlock,
    modis_fsca: np.ndarray,
    valid_pixels: np.ndarray,
    expected_pixels: np.ndarray,
    observed_pixels: np.ndarray,
) -> bool:
    shape = modis_fsca.shape
    for name, values in (
        ("valid_pixels", valid_pixels),
        ("expected_pixels", expected_pixels),
        ("observed_pixels", observed_pixels),
    ):
        if values.shape != shape:
            raise ValueError(f"{name} shape differs from MODIS fSCA")
    if modis_fsca.size != stats.n_cells:
        raise ValueError("MODIS statistics block differs from target grid")

    stats.n_calendar_days += 1
    flat_fsca = modis_fsca.ravel()
    flat_valid = valid_pixels.ravel()
    flat_expected = expected_pixels.ravel()
    flat_observed = observed_pixels.ravel()
    usable = (
        np.isfinite(flat_fsca)
        & (flat_fsca >= 0)
        & (flat_fsca <= 1)
        & (flat_valid > 0)
        & (flat_expected > 0)
    )
    if not usable.any():
        return False

    slots = np.flatnonzero(usable)
    weights = flat_valid[usable].astype(np.float64)
    weighted_fsca = weights * flat_fsca[usable]
    stats.sum_w[slots] += weights
    stats.sum_w_fsca[slots] += weighted_fsca
    stats.valid_pixels[slots] += flat_valid[usable]
    stats.expected_pixels[slots] += flat_expected[usable]
    stats.observed_pixels[slots] += flat_observed[usable]
    stats.n_cell_days[slots] += 1
    stats.n_days[slots] += 1

    domain = stats.domain_slot
    stats.sum_w[domain] += weights.sum()
    stats.sum_w_fsca[domain] += weighted_fsca.sum()
    stats.valid_pixels[domain] += flat_valid[usable].sum()
    stats.expected_pixels[domain] += flat_expected[usable].sum()
    stats.observed_pixels[domain] += flat_observed[usable].sum()
    stats.n_cell_days[domain] += int(usable.sum())
    stats.n_days[domain] += 1
    return True


def merge_modis_blocks(
    blocks: list[ModisStatsBlock] | tuple[ModisStatsBlock, ...],
) -> ModisStatsBlock:
    if not blocks:
        raise ValueError("at least one MODIS statistics block is required")
    merged = ModisStatsBlock.empty(blocks[0].n_cells)
    for block in blocks:
        merged.merge(block)
    merged.validate()
    return merged


def mean_modis_fsca_pct(stats: ModisStatsBlock, slot: int) -> float | None:
    if not 0 <= slot < stats.size:
        raise IndexError(slot)
    weight = float(stats.sum_w[slot])
    if weight <= 0:
        return None
    return 100.0 * float(stats.sum_w_fsca[slot]) / weight


def modis_checkpoint_path(directory: Path, year: int, month: int) -> Path:
    return directory / f"{year:04d}-{month:02d}.csv"


def _fingerprint(config: RunConfig) -> str:
    grid = config.target_grid
    contract = {
        "schema": MODIS_CHECKPOINT_SCHEMA,
        "domain": config.domain_label,
        "support_threshold": config.support_threshold,
        "lons": grid.lons,
        "lats": grid.lats,
        "modscag_product": MODSCAG_PRODUCT,
        "aggregation": AGGREGATION,
        "statistic": "valid_MODSCAG_pixel_day_weighted_mean_fSCA",
    }
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _identity(config: RunConfig, slot: int) -> tuple[str, str]:
    if slot == config.target_grid.size:
        return "domain", "DOMAIN"
    return "cell", str(config.target_grid.cell_metadata(slot)["cell_id"])


def write_modis_checkpoint(
    stats: ModisStatsBlock,
    year: int,
    month: int,
    config: RunConfig,
    output: Path,
) -> None:
    stats.validate(expected_calendar_days=calendar.monthrange(year, month)[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for slot in range(stats.size):
        level, cell_id = _identity(config, slot)
        row: dict[str, object] = {
            "checkpoint_schema": MODIS_CHECKPOINT_SCHEMA,
            "config_fingerprint": _fingerprint(config),
            "calendar_month": f"{year:04d}-{month:02d}",
            "level": level,
            "slot": slot,
            "cell_id": cell_id,
            "mean_modis_fsca_pct": mean_modis_fsca_pct(stats, slot),
            "domain": config.domain_label,
            "modscag_product": MODSCAG_PRODUCT,
            "aggregation": AGGREGATION,
        }
        for name in MODIS_STAT_FIELDS:
            value = getattr(stats, name)[slot]
            row[name] = float(value) if name in MODIS_FLOAT_FIELDS else int(value)
        rows.append(row)

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
            writer = csv.DictWriter(temporary, fieldnames=MODIS_CHECKPOINT_FIELDS)
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


def load_modis_checkpoint(
    path: Path, year: int, month: int, config: RunConfig
) -> ModisStatsBlock:
    try:
        with path.open("r", encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames != MODIS_CHECKPOINT_FIELDS:
                raise InvalidModisCheckpoint("column schema differs")
            rows = list(reader)
        if len(rows) != config.target_grid.size + 1:
            raise InvalidModisCheckpoint("row count differs")
        stats = ModisStatsBlock.empty(config.target_grid.size)
        expected_fingerprint = _fingerprint(config)
        expected_period = f"{year:04d}-{month:02d}"
        for expected_slot, row in enumerate(rows):
            slot = int(row["slot"])
            if slot != expected_slot:
                raise InvalidModisCheckpoint("rows are not in slot order")
            level, cell_id = _identity(config, slot)
            for name, expected in (
                ("checkpoint_schema", MODIS_CHECKPOINT_SCHEMA),
                ("config_fingerprint", expected_fingerprint),
                ("calendar_month", expected_period),
                ("level", level),
                ("cell_id", cell_id),
                ("domain", config.domain_label),
                ("modscag_product", MODSCAG_PRODUCT),
                ("aggregation", AGGREGATION),
            ):
                if row[name] != expected:
                    raise InvalidModisCheckpoint(f"{name} differs")
            for name in MODIS_FLOAT_FIELDS:
                getattr(stats, name)[slot] = float(row[name])
            for name in MODIS_INTEGER_FIELDS:
                getattr(stats, name)[slot] = int(row[name])
            stored = None if row["mean_modis_fsca_pct"] == "" else float(
                row["mean_modis_fsca_pct"]
            )
            calculated = mean_modis_fsca_pct(stats, slot)
            if stored is None or calculated is None:
                if stored is not calculated:
                    raise InvalidModisCheckpoint("null fSCA metric differs")
            elif not np.isclose(stored, calculated, rtol=1e-12, atol=1e-12):
                raise InvalidModisCheckpoint("fSCA metric differs")
        stats.validate(expected_calendar_days=calendar.monthrange(year, month)[1])
        return stats
    except InvalidModisCheckpoint:
        raise
    except Exception as exc:
        raise InvalidModisCheckpoint(str(exc)) from exc


def selected_calendar_months() -> tuple[tuple[int, int], ...]:
    periods = {
        (water_year - 1 if month >= 10 else water_year, month)
        for water_year in SELECTED_WATER_YEARS
        for month in SELECTED_MONTHS
    }
    return tuple(sorted(periods))


_WORKER_CONFIG: RunConfig | None = None
_WORKER_MAPPINGS: dict[str, TileMapping] | None = None
_WORKER_ARCHIVE_TILES: tuple[str, ...] = ()
_WORKER_VALIDATED_TILES: set[str] | None = None
_WORKER_FTP_SEMAPHORE: object | None = None


def _initialize_worker(config: RunConfig, ftp_semaphore: object) -> None:
    global _WORKER_CONFIG
    global _WORKER_MAPPINGS
    global _WORKER_ARCHIVE_TILES
    global _WORKER_VALIDATED_TILES
    global _WORKER_FTP_SEMAPHORE
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    _WORKER_CONFIG = config
    grid = config.target_grid
    _WORKER_ARCHIVE_TILES = archived_tiles_for_grid(grid)
    _WORKER_MAPPINGS = {
        tile: build_tile_mapping(None, tile, grid) for tile in tiles_for_grid(grid)
    }
    _WORKER_VALIDATED_TILES = set()
    _WORKER_FTP_SEMAPHORE = ftp_semaphore


def _validate_mapping(tile: str, path: Path) -> None:
    if _WORKER_CONFIG is None or _WORKER_MAPPINGS is None:
        raise RuntimeError("MODIS worker was not initialized")
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
        raise ValueError(f"computed MODIS mapping changed for {tile}")


def _process_month(year: int, month: int, checkpoint_directory: Path) -> str:
    if (
        _WORKER_CONFIG is None
        or _WORKER_MAPPINGS is None
        or _WORKER_VALIDATED_TILES is None
    ):
        raise RuntimeError("MODIS worker was not initialized")
    config = _WORKER_CONFIG
    grid = config.target_grid
    stats = ModisStatsBlock.empty(grid.size)
    days_in_month = calendar.monthrange(year, month)[1]
    label = f"{year:04d}-{month:02d}"
    with tempfile.TemporaryDirectory(prefix=f"modis-fsca-{label}-") as temporary:
        temporary_path = Path(temporary)
        for day_number in range(1, days_in_month + 1):
            day = date(year, month, day_number)
            paths: dict[str, Path] = {}
            try:
                for tile in _WORKER_ARCHIVE_TILES:
                    semaphore = _WORKER_FTP_SEMAPHORE
                    if semaphore is None:
                        raise RuntimeError("FTP semaphore was not initialized")
                    with semaphore:  # type: ignore[attr-defined]
                        paths[tile] = download_modscag(
                            tile, day, temporary_path, retries=config.retries
                        )
                for tile, path in paths.items():
                    if tile not in _WORKER_VALIDATED_TILES:
                        _validate_mapping(tile, path)
                        _WORKER_VALIDATED_TILES.add(tile)
                fsca, valid, expected, observed = aggregate_modscag(
                    paths, _WORKER_MAPPINGS, grid
                )
                support = np.divide(
                    valid,
                    expected,
                    out=np.zeros(grid.shape, dtype=np.float64),
                    where=expected > 0,
                )
                fsca[support < config.support_threshold] = np.nan
                update_modis_stats(stats, fsca, valid, expected, observed)
            finally:
                for path in paths.values():
                    path.unlink(missing_ok=True)
            if day_number == 1 or day_number % 10 == 0 or day_number == days_in_month:
                print(
                    f"MODIS worker {os.getpid()}: {label} "
                    f"completed {day_number}/{days_in_month} days",
                    flush=True,
                )
    output = modis_checkpoint_path(checkpoint_directory, year, month)
    write_modis_checkpoint(stats, year, month, config, output)
    return label


def _run_missing_months(
    config: RunConfig,
    checkpoint_directory: Path,
    months: list[tuple[int, int]],
    already_complete: int,
) -> None:
    if not months:
        return
    queue = deque(months)
    attempts = {period: 0 for period in months}
    failures: dict[tuple[int, int], BaseException] = {}
    context = multiprocessing.get_context("spawn")
    ftp_semaphore = context.BoundedSemaphore(config.ftp_connections)
    executor = ProcessPoolExecutor(
        max_workers=min(config.workers, len(months)),
        mp_context=context,
        initializer=_initialize_worker,
        initargs=(config, ftp_semaphore),
    )
    futures: dict[Future[str], tuple[int, int]] = {}

    def fill_slots() -> None:
        while queue and len(futures) < config.workers:
            period = queue.popleft()
            attempts[period] += 1
            futures[
                executor.submit(
                    _process_month, period[0], period[1], checkpoint_directory
                )
            ] = period

    try:
        fill_slots()
        completed = 0
        while futures:
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                period = futures.pop(future)
                try:
                    label = future.result()
                except BaseException as exc:
                    if attempts[period] < config.month_attempts:
                        queue.append(period)
                        print(
                            f"MODIS month {period[0]:04d}-{period[1]:02d} failed; "
                            f"retrying: {exc}",
                            flush=True,
                        )
                    else:
                        failures[period] = exc
                else:
                    completed += 1
                    print(
                        f"MODIS checkpoint saved: {label} "
                        f"({already_complete + completed}/"
                        f"{len(selected_calendar_months())})",
                        flush=True,
                    )
            if failures:
                queue.clear()
            fill_slots()
    except KeyboardInterrupt:
        queue.clear()
        for future in futures:
            future.cancel()
        print(
            "interrupt received; waiting for in-flight MODIS months to save",
            flush=True,
        )
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    if failures:
        period = sorted(failures)[0]
        raise RuntimeError(
            f"MODIS month {period[0]:04d}-{period[1]:02d} failed after "
            f"{attempts[period]} attempts; completed checkpoints were preserved"
        ) from failures[period]


def run(config: RunConfig, checkpoint_directory: Path) -> None:
    config.validate()
    checkpoint_directory.mkdir(parents=True, exist_ok=True)
    periods = selected_calendar_months()
    complete: dict[tuple[int, int], ModisStatsBlock] = {}
    for year, month in periods:
        path = modis_checkpoint_path(checkpoint_directory, year, month)
        if not path.exists():
            continue
        try:
            complete[(year, month)] = load_modis_checkpoint(
                path, year, month, config
            )
        except InvalidModisCheckpoint as exc:
            print(f"reprocessing invalid MODIS checkpoint {path}: {exc}", flush=True)
    missing = [period for period in periods if period not in complete]
    print(
        f"validated {len(complete)}/{len(periods)} monthly MODIS checkpoints; "
        f"processing {len(missing)} with {config.workers} workers",
        flush=True,
    )
    _run_missing_months(
        config, checkpoint_directory, missing, already_complete=len(complete)
    )
    for year, month in periods:
        load_modis_checkpoint(
            modis_checkpoint_path(checkpoint_directory, year, month),
            year,
            month,
            config,
        )


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Build resumable monthly MODIS fSCA statistics for composites"
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=Path("results/wet_dry_modis_fsca_monthly_checkpoints"),
    )
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--ftp-connections", type=int, default=8)
    args = parser.parse_args(argv)
    config = RunConfig(
        workers=args.workers,
        ftp_connections=args.ftp_connections,
    )
    run(config, args.checkpoint_dir)
    print(f"validated all MODIS fSCA checkpoints in {args.checkpoint_dir}")


if __name__ == "__main__":
    main()
