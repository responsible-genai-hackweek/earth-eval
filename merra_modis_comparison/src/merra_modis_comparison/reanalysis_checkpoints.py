from __future__ import annotations

import calendar
import csv
import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .reanalysis_config import ReanalysisModelSpec, ReanalysisRunConfig
from .reanalysis_metrics import (
    ALL_STAT_FIELDS,
    FLOAT_STAT_FIELDS,
    ReanalysisStatsBlock,
    reanalysis_metrics_for_slot,
)


CHECKPOINT_SCHEMA = "2"
REFERENCE_PRODUCT = "STC_MODSCGDRF_HIST_v1:snow_fraction"
MODEL_TIME = "hourly field at 15:00 UTC"

DERIVED_METRIC_FIELDS = [
    "bias_pp",
    "mae_pp",
    "normalized_mean_bias_pct",
    "normalized_mae_pct",
    "model_fsca_mean",
    "modscag_fsca_mean",
    "support_fraction",
    "direct_observation_fraction",
]
CHECKPOINT_FIELDS = [
    "checkpoint_schema",
    "config_fingerprint",
    "calendar_month",
    "model_id",
    "level",
    "slot",
    "cell_id",
    "target_latitude",
    "target_longitude",
    "target_row",
    "target_column",
    *ALL_STAT_FIELDS,
    *DERIVED_METRIC_FIELDS,
    "domain",
    "error_sign",
    "model_product",
    "model_variable",
    "model_time",
    "reference_product",
    "aggregation",
]


class InvalidReanalysisCheckpoint(ValueError):
    pass


def error_sign(spec: ReanalysisModelSpec) -> str:
    return f"{spec.model_id}_minus_MODSCAG"


def aggregation(spec: ReanalysisModelSpec) -> str:
    return f"equal_area_MODIS_pixel_center_to_{spec.model_id}_CDS_grid"


def config_fingerprint(
    config: ReanalysisRunConfig, spec: ReanalysisModelSpec
) -> str:
    grid = config.target_grid(spec.model_id)
    contract = {
        "schema": CHECKPOINT_SCHEMA,
        "model": asdict(spec),
        "west": config.west,
        "east": config.east,
        "south": config.south,
        "north": config.north,
        "support_threshold": config.support_threshold,
        "lons": grid.lons,
        "lats": grid.lats,
        "reference_product": REFERENCE_PRODUCT,
        "error_sign": error_sign(spec),
        "aggregation": aggregation(spec),
    }
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def checkpoint_path(directory: Path, year: int, month: int) -> Path:
    return directory / f"{year:04d}-{month:02d}.csv"


def _identity_for_slot(
    config: ReanalysisRunConfig, spec: ReanalysisModelSpec, slot: int
) -> dict[str, object]:
    grid = config.target_grid(spec.model_id)
    if slot == grid.size:
        return {
            "level": "domain",
            "cell_id": "DOMAIN",
            "target_latitude": "",
            "target_longitude": "",
            "target_row": "",
            "target_column": "",
        }
    return {"level": "cell", **grid.cell_metadata(slot)}


def _row_for_slot(
    stats: ReanalysisStatsBlock,
    slot: int,
    year: int,
    month: int,
    config: ReanalysisRunConfig,
    spec: ReanalysisModelSpec,
) -> dict[str, object]:
    row: dict[str, object] = {
        "checkpoint_schema": CHECKPOINT_SCHEMA,
        "config_fingerprint": config_fingerprint(config, spec),
        "calendar_month": f"{year:04d}-{month:02d}",
        "model_id": spec.model_id,
        "slot": slot,
        **_identity_for_slot(config, spec, slot),
    }
    for name in ALL_STAT_FIELDS:
        value = getattr(stats, name)[slot]
        row[name] = float(value) if name in FLOAT_STAT_FIELDS else int(value)
    metrics = reanalysis_metrics_for_slot(stats, slot)
    row.update({name: metrics[name] for name in DERIVED_METRIC_FIELDS})
    row.update(
        {
            "domain": config.domain_label,
            "error_sign": error_sign(spec),
            "model_product": spec.product_description,
            "model_variable": spec.variable,
            "model_time": MODEL_TIME,
            "reference_product": REFERENCE_PRODUCT,
            "aggregation": aggregation(spec),
        }
    )
    return row


def write_month_checkpoint(
    stats: ReanalysisStatsBlock,
    year: int,
    month: int,
    config: ReanalysisRunConfig,
    spec: ReanalysisModelSpec,
    output: Path,
) -> None:
    stats.validate(expected_calendar_days=calendar.monthrange(year, month)[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        _row_for_slot(stats, slot, year, month, config, spec)
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


def _optional_float(value: str) -> float | None:
    return None if value == "" else float(value)


def load_month_checkpoint(
    path: Path,
    year: int,
    month: int,
    config: ReanalysisRunConfig,
    spec: ReanalysisModelSpec,
) -> ReanalysisStatsBlock:
    try:
        with path.open("r", encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames != CHECKPOINT_FIELDS:
                raise InvalidReanalysisCheckpoint("column schema differs")
            rows = list(reader)
        grid = config.target_grid(spec.model_id)
        if len(rows) != grid.size + 1:
            raise InvalidReanalysisCheckpoint(
                f"expected {grid.size + 1} rows, found {len(rows)}"
            )
        fingerprint = config_fingerprint(config, spec)
        period = f"{year:04d}-{month:02d}"
        stats = ReanalysisStatsBlock.empty(grid.size)
        contract = {
            "domain": config.domain_label,
            "error_sign": error_sign(spec),
            "model_product": spec.product_description,
            "model_variable": spec.variable,
            "model_time": MODEL_TIME,
            "reference_product": REFERENCE_PRODUCT,
            "aggregation": aggregation(spec),
        }
        for expected_slot, row in enumerate(rows):
            slot = int(row["slot"])
            if slot != expected_slot:
                raise InvalidReanalysisCheckpoint("rows are not in stable slot order")
            if row["checkpoint_schema"] != CHECKPOINT_SCHEMA:
                raise InvalidReanalysisCheckpoint("checkpoint schema version differs")
            if row["config_fingerprint"] != fingerprint:
                raise InvalidReanalysisCheckpoint("scientific configuration differs")
            if row["calendar_month"] != period:
                raise InvalidReanalysisCheckpoint("calendar month differs")
            if row["model_id"] != spec.model_id:
                raise InvalidReanalysisCheckpoint("model identifier differs")
            expected_identity = _identity_for_slot(config, spec, slot)
            for name, expected in expected_identity.items():
                if row[name] != str(expected):
                    raise InvalidReanalysisCheckpoint(
                        f"cell identity differs in {name}"
                    )
            for name, expected in contract.items():
                if row[name] != expected:
                    raise InvalidReanalysisCheckpoint(
                        f"comparison contract differs in {name}"
                    )
            for name in FLOAT_STAT_FIELDS:
                getattr(stats, name)[slot] = float(row[name])
            for name in set(ALL_STAT_FIELDS) - set(FLOAT_STAT_FIELDS):
                getattr(stats, name)[slot] = int(row[name])
            calculated = reanalysis_metrics_for_slot(stats, slot)
            for name in DERIVED_METRIC_FIELDS:
                stored = _optional_float(row[name])
                expected = calculated[name]
                if stored is None or expected is None:
                    if stored is not expected:
                        raise InvalidReanalysisCheckpoint(
                            f"null metric mismatch in {name}"
                        )
                elif not np.isclose(stored, expected, rtol=1e-12, atol=1e-12):
                    raise InvalidReanalysisCheckpoint(f"metric mismatch in {name}")
        stats.validate(expected_calendar_days=calendar.monthrange(year, month)[1])
        return stats
    except InvalidReanalysisCheckpoint:
        raise
    except Exception as exc:
        raise InvalidReanalysisCheckpoint(str(exc)) from exc


def load_available_checkpoints(
    config: ReanalysisRunConfig,
    spec: ReanalysisModelSpec,
    directory: Path,
) -> tuple[
    dict[tuple[int, int], ReanalysisStatsBlock], dict[tuple[int, int], str]
]:
    valid: dict[tuple[int, int], ReanalysisStatsBlock] = {}
    invalid: dict[tuple[int, int], str] = {}
    for year, month in config.calendar_months:
        path = checkpoint_path(directory, year, month)
        if not path.exists():
            continue
        try:
            valid[(year, month)] = load_month_checkpoint(
                path, year, month, config, spec
            )
        except InvalidReanalysisCheckpoint as exc:
            invalid[(year, month)] = str(exc)
    return valid, invalid
