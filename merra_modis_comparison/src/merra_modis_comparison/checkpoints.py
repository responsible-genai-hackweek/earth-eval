from __future__ import annotations

import calendar
import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path

import numpy as np

from .config import RunConfig
from .metrics import ALL_STAT_FIELDS, FLOAT_STAT_FIELDS, StatsBlock, metrics_for_slot


CHECKPOINT_SCHEMA = "1"
MERRA_PRODUCT = "M2T1NXLND.5.12.4:FRSNO[index=15,15:00-16:00Z]"
MODSCAG_PRODUCT = "STC_MODSCGDRF_HIST_v1:snow_fraction"
ERROR_SIGN = "MERRA2_minus_MODSCAG"
AGGREGATION = "equal_area_MODIS_pixel_center_to_MERRA2_cell"

CHECKPOINT_FIELDS = [
    "checkpoint_schema",
    "config_fingerprint",
    "calendar_month",
    "level",
    "slot",
    "cell_id",
    "merra_latitude",
    "merra_longitude",
    "merra_latitude_index",
    "merra_longitude_index",
    *ALL_STAT_FIELDS,
    "bias_pp",
    "mae_pp",
    "support_fraction",
    "direct_observation_fraction",
    "domain",
    "error_sign",
    "merra_product",
    "modscag_product",
    "aggregation",
]


class InvalidCheckpoint(ValueError):
    pass


def config_fingerprint(config: RunConfig) -> str:
    grid = config.target_grid
    contract = {
        "schema": CHECKPOINT_SCHEMA,
        "west": config.west,
        "east": config.east,
        "south": config.south,
        "north": config.north,
        "support_threshold": config.support_threshold,
        "merra_time_index": config.merra_time_index,
        "lons": grid.lons,
        "lats": grid.lats,
        "lon_indices": grid.lon_indices,
        "lat_indices": grid.lat_indices,
        "merra_product": MERRA_PRODUCT,
        "modscag_product": MODSCAG_PRODUCT,
        "error_sign": ERROR_SIGN,
        "aggregation": AGGREGATION,
    }
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def checkpoint_path(directory: Path, year: int, month: int) -> Path:
    return directory / f"{year:04d}-{month:02d}.csv"


def _identity_for_slot(config: RunConfig, slot: int) -> dict[str, object]:
    grid = config.target_grid
    if slot == grid.size:
        return {
            "level": "domain",
            "cell_id": "DOMAIN",
            "merra_latitude": "",
            "merra_longitude": "",
            "merra_latitude_index": "",
            "merra_longitude_index": "",
        }
    return {"level": "cell", **grid.cell_metadata(slot)}


def _row_for_slot(
    stats: StatsBlock, slot: int, year: int, month: int, config: RunConfig
) -> dict[str, object]:
    row: dict[str, object] = {
        "checkpoint_schema": CHECKPOINT_SCHEMA,
        "config_fingerprint": config_fingerprint(config),
        "calendar_month": f"{year:04d}-{month:02d}",
        "slot": slot,
        **_identity_for_slot(config, slot),
    }
    for name in ALL_STAT_FIELDS:
        value = getattr(stats, name)[slot]
        row[name] = float(value) if name in FLOAT_STAT_FIELDS else int(value)
    metrics = metrics_for_slot(stats, slot)
    row.update(
        {
            "bias_pp": metrics["bias_pp"],
            "mae_pp": metrics["mae_pp"],
            "support_fraction": metrics["support_fraction"],
            "direct_observation_fraction": metrics["direct_observation_fraction"],
            "domain": config.domain_label,
            "error_sign": ERROR_SIGN,
            "merra_product": MERRA_PRODUCT,
            "modscag_product": MODSCAG_PRODUCT,
            "aggregation": AGGREGATION,
        }
    )
    return row


def write_month_checkpoint(
    stats: StatsBlock, year: int, month: int, config: RunConfig, output: Path
) -> None:
    expected_days = calendar.monthrange(year, month)[1]
    stats.validate(expected_calendar_days=expected_days)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        _row_for_slot(stats, slot, year, month, config)
        for slot in range(stats.size)
    ]
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
            writer = csv.DictWriter(temporary, fieldnames=CHECKPOINT_FIELDS)
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


def _parse_optional_float(value: str) -> float | None:
    return None if value == "" else float(value)


def load_month_checkpoint(
    path: Path, year: int, month: int, config: RunConfig
) -> StatsBlock:
    try:
        with path.open("r", encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames != CHECKPOINT_FIELDS:
                raise InvalidCheckpoint("column schema differs")
            rows = list(reader)
        grid = config.target_grid
        if len(rows) != grid.size + 1:
            raise InvalidCheckpoint(
                f"expected {grid.size + 1} rows, found {len(rows)}"
            )
        fingerprint = config_fingerprint(config)
        period = f"{year:04d}-{month:02d}"
        stats = StatsBlock.empty(grid.size)
        for expected_slot, row in enumerate(rows):
            slot = int(row["slot"])
            if slot != expected_slot:
                raise InvalidCheckpoint("rows are not in stable slot order")
            if row["checkpoint_schema"] != CHECKPOINT_SCHEMA:
                raise InvalidCheckpoint("checkpoint schema version differs")
            if row["config_fingerprint"] != fingerprint:
                raise InvalidCheckpoint("scientific configuration differs")
            if row["calendar_month"] != period:
                raise InvalidCheckpoint("calendar month differs")
            expected_identity = _identity_for_slot(config, slot)
            for name, expected in expected_identity.items():
                if row[name] != str(expected):
                    raise InvalidCheckpoint(f"cell identity differs in {name}")
            if row["domain"] != config.domain_label:
                raise InvalidCheckpoint("domain label differs")
            for name, expected in (
                ("error_sign", ERROR_SIGN),
                ("merra_product", MERRA_PRODUCT),
                ("modscag_product", MODSCAG_PRODUCT),
                ("aggregation", AGGREGATION),
            ):
                if row[name] != expected:
                    raise InvalidCheckpoint(f"comparison contract differs in {name}")
            for name in FLOAT_STAT_FIELDS:
                getattr(stats, name)[slot] = float(row[name])
            for name in set(ALL_STAT_FIELDS) - set(FLOAT_STAT_FIELDS):
                getattr(stats, name)[slot] = int(row[name])

            calculated = metrics_for_slot(stats, slot)
            for name in (
                "bias_pp",
                "mae_pp",
                "support_fraction",
                "direct_observation_fraction",
            ):
                stored = _parse_optional_float(row[name])
                expected = calculated[name]
                if stored is None or expected is None:
                    if stored is not expected:
                        raise InvalidCheckpoint(f"null metric mismatch in {name}")
                elif not np.isclose(stored, expected, rtol=1e-12, atol=1e-12):
                    raise InvalidCheckpoint(f"metric mismatch in {name}")
        stats.validate(expected_calendar_days=calendar.monthrange(year, month)[1])
        return stats
    except InvalidCheckpoint:
        raise
    except Exception as exc:
        raise InvalidCheckpoint(str(exc)) from exc


def load_available_checkpoints(
    config: RunConfig, directory: Path
) -> tuple[dict[tuple[int, int], StatsBlock], dict[tuple[int, int], str]]:
    valid: dict[tuple[int, int], StatsBlock] = {}
    invalid: dict[tuple[int, int], str] = {}
    for year, month in config.calendar_months:
        path = checkpoint_path(directory, year, month)
        if not path.exists():
            continue
        try:
            valid[(year, month)] = load_month_checkpoint(path, year, month, config)
        except InvalidCheckpoint as exc:
            invalid[(year, month)] = str(exc)
    return valid, invalid
