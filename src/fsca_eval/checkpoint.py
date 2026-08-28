"""Monthly checkpoint schema, atomic writes, and validity checks.

One checkpoint file = one calendar month = 73 rows (72 MERRA cells + 1 domain
row) in a stable slot order. See scientific-contract.md and the operational
plan (section 3) for the schema this encodes. `sum_w_r` is one additional
column beyond the original plan text -- see the note in config.py.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import tempfile
from dataclasses import dataclass, field

from . import config, dates, metrics, regrid

IDENTITY_COLUMNS = ("cell_id", "lon_center", "lat_center")
ALL_COLUMNS = IDENTITY_COLUMNS + config.CHECKPOINT_COLUMNS
DOMAIN_CELL_ID = -1

_FLOAT_COLUMNS = frozenset(
    {
        "lon_center",
        "lat_center",
        "sum_w",
        "sum_w_error",
        "sum_w_abs_error",
        "sum_w_r",
        "bias_pp",
        "mae_pp",
        "support_fraction",
        "direct_observation_fraction",
    }
)
_INT_COLUMNS = frozenset(
    {
        "cell_id",
        "valid_pixels",
        "expected_pixels",
        "observed_pixels",
        "n_cell_days",
        "n_days",
        "n_calendar_days",
    }
)

_TOLERANCE = 1e-9


def build_metadata(water_year: int, year: int, month: int) -> dict:
    return {
        "schema_version": config.CHECKPOINT_SCHEMA_VERSION,
        "config_fingerprint": config.config_fingerprint(),
        "error_sign": config.ERROR_SIGN,
        "water_year": water_year,
        "calendar_year": year,
        "calendar_month": month,
        "merra_collection": config.MERRA_COLLECTION,
        "merra_version": config.MERRA_VERSION,
        "merra_variable": config.MERRA_VARIABLE,
        "merra_time_index": config.MERRA_TIME_INDEX,
        "modscag_product": config.MODSCAG_PRODUCT,
        "modscag_version": config.MODSCAG_VERSION,
        "modscag_variable": config.MODSCAG_VARIABLE,
        "domain_edges": [
            config.DOMAIN_LON_EDGE_MIN,
            config.DOMAIN_LON_EDGE_MAX,
            config.DOMAIN_LAT_EDGE_MIN,
            config.DOMAIN_LAT_EDGE_MAX,
        ],
        "aggregation": "equal_area_pixel_center_mean",
        "support_threshold": config.SUPPORT_THRESHOLD,
    }


def row_from_stats(cell_id: int, lon_center: float, lat_center: float, stats: metrics.SufficientStats) -> dict:
    return {
        "cell_id": cell_id,
        "lon_center": lon_center,
        "lat_center": lat_center,
        "sum_w": stats.sum_w,
        "sum_w_error": stats.sum_w_error,
        "sum_w_abs_error": stats.sum_w_abs_error,
        "sum_w_r": stats.sum_w_r,
        "valid_pixels": stats.valid_pixels,
        "expected_pixels": stats.expected_pixels,
        "observed_pixels": stats.observed_pixels,
        "n_cell_days": stats.n_cell_days,
        "n_days": stats.n_days,
        "n_calendar_days": stats.n_calendar_days,
        "bias_pp": metrics.bias_pp(stats),
        "mae_pp": metrics.mae_pp(stats),
        "support_fraction": metrics.support_fraction(stats),
        "direct_observation_fraction": metrics.direct_observation_fraction(stats),
    }


def stats_from_row(row: dict) -> metrics.SufficientStats:
    return metrics.SufficientStats(
        sum_w=float(row["sum_w"]),
        sum_w_error=float(row["sum_w_error"]),
        sum_w_abs_error=float(row["sum_w_abs_error"]),
        sum_w_r=float(row["sum_w_r"]),
        valid_pixels=int(row["valid_pixels"]),
        expected_pixels=int(row["expected_pixels"]),
        observed_pixels=int(row["observed_pixels"]),
        n_cell_days=int(row["n_cell_days"]),
        n_days=int(row["n_days"]),
        n_calendar_days=int(row["n_calendar_days"]),
    )


def domain_row_from_cells(cell_rows: list[dict]) -> dict:
    combined = metrics.SufficientStats()
    for row in cell_rows:
        combined = combined + stats_from_row(row)
    # n_calendar_days is a shared per-checkpoint constant (every cell observes
    # the same set of calendar days each day, valid or not) -- it is not a
    # spatially additive quantity, so summing it across N_CELLS cells would
    # inflate it by N_CELLS. Every cell row carries the same value by
    # construction (see metrics.cell_day_contribution); take it directly.
    if cell_rows:
        combined.n_calendar_days = cell_rows[0]["n_calendar_days"]
    return row_from_stats(DOMAIN_CELL_ID, float("nan"), float("nan"), combined)


def build_month_checkpoint_rows(water_year: int, year: int, month: int, cell_stats: list[metrics.SufficientStats]) -> tuple[list[dict], dict]:
    """Build the 73 rows (72 cells in stable order + domain row) and metadata."""
    if len(cell_stats) != config.N_CELLS:
        raise ValueError(f"expected {config.N_CELLS} cell stats, got {len(cell_stats)}")

    cell_rows = []
    for cell_id in range(config.N_CELLS):
        lon_center, lat_center = regrid.cell_id_to_center(cell_id)
        cell_rows.append(row_from_stats(cell_id, lon_center, lat_center, cell_stats[cell_id]))

    domain_row = domain_row_from_cells(cell_rows)
    metadata = build_metadata(water_year, year, month)
    return cell_rows + [domain_row], metadata


def _format_value(column: str, value) -> str:
    if column in _FLOAT_COLUMNS:
        v = float(value)
        return "nan" if math.isnan(v) else repr(v)
    return str(int(value))


def _parse_value(column: str, raw: str):
    if column in _FLOAT_COLUMNS:
        return float(raw)
    return int(raw)


def write_checkpoint(path: str, rows: list[dict], metadata: dict) -> None:
    """Atomically write a checkpoint: temp file, flush, fsync, then rename."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-checkpoint-", dir=directory)
    try:
        with os.fdopen(fd, "w", newline="") as f:
            f.write("# METADATA " + json.dumps(metadata, sort_keys=True) + "\n")
            writer = csv.writer(f)
            writer.writerow(ALL_COLUMNS)
            for row in rows:
                writer.writerow([_format_value(c, row[c]) for c in ALL_COLUMNS])
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def read_checkpoint(path: str) -> tuple[dict, list[dict]]:
    with open(path, "r", newline="") as f:
        first_line = f.readline()
        if not first_line.startswith("# METADATA "):
            raise ValueError(f"{path}: missing metadata header line")
        metadata = json.loads(first_line[len("# METADATA "):])

        reader = csv.reader(f)
        header = next(reader)
        if tuple(header) != ALL_COLUMNS:
            raise ValueError(f"{path}: unexpected column header {header}")

        rows = []
        for raw_row in reader:
            row = {c: _parse_value(c, v) for c, v in zip(ALL_COLUMNS, raw_row)}
            rows.append(row)

    return metadata, rows


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)


def validate_checkpoint(path: str, expected_water_year: int | None = None, expected_year: int | None = None, expected_month: int | None = None) -> ValidationResult:
    errors: list[str] = []

    try:
        metadata, rows = read_checkpoint(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return ValidationResult(ok=False, errors=[f"unreadable or malformed checkpoint: {exc}"])

    if metadata.get("schema_version") != config.CHECKPOINT_SCHEMA_VERSION:
        errors.append(
            f"schema_version mismatch: {metadata.get('schema_version')!r} != "
            f"{config.CHECKPOINT_SCHEMA_VERSION!r}"
        )
    if metadata.get("config_fingerprint") != config.config_fingerprint():
        errors.append("config_fingerprint mismatch: checkpoint was written under a different scientific configuration")
    if metadata.get("error_sign") != config.ERROR_SIGN:
        errors.append(f"error_sign mismatch: {metadata.get('error_sign')!r} != {config.ERROR_SIGN!r}")

    if expected_water_year is not None and metadata.get("water_year") != expected_water_year:
        errors.append(f"water_year mismatch: {metadata.get('water_year')!r} != {expected_water_year!r}")
    if expected_year is not None and metadata.get("calendar_year") != expected_year:
        errors.append(f"calendar_year mismatch: {metadata.get('calendar_year')!r} != {expected_year!r}")
    if expected_month is not None and metadata.get("calendar_month") != expected_month:
        errors.append(f"calendar_month mismatch: {metadata.get('calendar_month')!r} != {expected_month!r}")

    if len(rows) != config.ROWS_PER_MONTH:
        errors.append(f"row count mismatch: {len(rows)} != {config.ROWS_PER_MONTH}")
        return ValidationResult(ok=False, errors=errors)

    cell_rows = rows[: config.N_CELLS]
    domain_row = rows[config.N_CELLS]

    for expected_cell_id, row in enumerate(cell_rows):
        if row["cell_id"] != expected_cell_id:
            errors.append(f"row slot {expected_cell_id}: cell_id {row['cell_id']} out of stable order")
            continue
        expected_lon, expected_lat = regrid.cell_id_to_center(expected_cell_id)
        if not math.isclose(row["lon_center"], expected_lon, abs_tol=_TOLERANCE):
            errors.append(f"cell {expected_cell_id}: lon_center {row['lon_center']} != {expected_lon}")
        if not math.isclose(row["lat_center"], expected_lat, abs_tol=_TOLERANCE):
            errors.append(f"cell {expected_cell_id}: lat_center {row['lat_center']} != {expected_lat}")

    if domain_row["cell_id"] != DOMAIN_CELL_ID:
        errors.append(f"final row cell_id {domain_row['cell_id']} != {DOMAIN_CELL_ID} (domain row)")

    calendar_year = metadata.get("calendar_year")
    calendar_month = metadata.get("calendar_month")
    if isinstance(calendar_year, int) and isinstance(calendar_month, int):
        expected_days = dates.n_calendar_days_in_month(calendar_year, calendar_month)
        for row in rows:
            if row["n_calendar_days"] != expected_days:
                errors.append(
                    f"cell {row['cell_id']}: n_calendar_days {row['n_calendar_days']} != {expected_days}"
                )

    for row in rows:
        cid = row["cell_id"]
        if row["valid_pixels"] < 0 or row["expected_pixels"] < 0 or row["observed_pixels"] < 0:
            errors.append(f"cell {cid}: negative pixel counts")
        if row["valid_pixels"] > row["expected_pixels"] and row["expected_pixels"] > 0:
            errors.append(f"cell {cid}: valid_pixels {row['valid_pixels']} > expected_pixels {row['expected_pixels']}")
        if row["observed_pixels"] > row["valid_pixels"]:
            errors.append(f"cell {cid}: observed_pixels {row['observed_pixels']} > valid_pixels {row['valid_pixels']}")
        if row["sum_w"] > row["valid_pixels"] + _TOLERANCE:
            errors.append(f"cell {cid}: sum_w {row['sum_w']} exceeds valid_pixels {row['valid_pixels']}")
        # This ordering only holds per individual cell: n_calendar_days is a
        # shared per-checkpoint constant (see domain_row_from_cells), while
        # n_cell_days/n_days are pooled sums across N_CELLS cells for the
        # domain row and can legitimately exceed it.
        if cid != DOMAIN_CELL_ID and not (row["n_cell_days"] <= row["n_days"] <= row["n_calendar_days"]):
            errors.append(
                f"cell {cid}: day counts out of order "
                f"(n_cell_days={row['n_cell_days']}, n_days={row['n_days']}, "
                f"n_calendar_days={row['n_calendar_days']})"
            )

        stats = stats_from_row(row)
        recomputed_bias = metrics.bias_pp(stats)
        recomputed_mae = metrics.mae_pp(stats)
        recomputed_support = metrics.support_fraction(stats)
        recomputed_direct = metrics.direct_observation_fraction(stats)

        if not _close_or_both_nan(recomputed_bias, row["bias_pp"]):
            errors.append(f"cell {cid}: stored bias_pp {row['bias_pp']} != recomputed {recomputed_bias}")
        if not _close_or_both_nan(recomputed_mae, row["mae_pp"]):
            errors.append(f"cell {cid}: stored mae_pp {row['mae_pp']} != recomputed {recomputed_mae}")
        if not math.isclose(recomputed_support, row["support_fraction"], abs_tol=_TOLERANCE):
            errors.append(f"cell {cid}: stored support_fraction {row['support_fraction']} != recomputed {recomputed_support}")
        if not math.isclose(recomputed_direct, row["direct_observation_fraction"], abs_tol=_TOLERANCE):
            errors.append(
                f"cell {cid}: stored direct_observation_fraction {row['direct_observation_fraction']} != "
                f"recomputed {recomputed_direct}"
            )

        if not math.isnan(row["bias_pp"]) and not math.isnan(row["mae_pp"]):
            if abs(row["bias_pp"]) > row["mae_pp"] + _TOLERANCE:
                errors.append(f"cell {cid}: abs(bias_pp)={abs(row['bias_pp'])} > mae_pp={row['mae_pp']}")

    reconstructed_domain = domain_row_from_cells(cell_rows)
    for column in config.CHECKPOINT_COLUMNS:
        stored = domain_row[column]
        expected = reconstructed_domain[column]
        if column in _FLOAT_COLUMNS:
            if not _close_or_both_nan(stored, expected):
                errors.append(f"domain row: {column} {stored} != reconstructed {expected}")
        else:
            if stored != expected:
                errors.append(f"domain row: {column} {stored} != reconstructed {expected}")

    return ValidationResult(ok=(len(errors) == 0), errors=errors)


def _close_or_both_nan(a: float, b: float) -> bool:
    if math.isnan(a) and math.isnan(b):
        return True
    if math.isnan(a) or math.isnan(b):
        return False
    return math.isclose(a, b, abs_tol=_TOLERANCE, rel_tol=1e-9)
