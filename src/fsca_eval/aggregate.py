"""Build the two final aggregate CSVs from validated monthly checkpoints.

Final groups (operational plan section 4):
- 14 water years x 12 water-year months            = 168
- 14 water years x 4 meteorological seasons         =  56
- pooled WY2010-2023 climatology x 12 calendar months = 12
- pooled WY2010-2023 climatology x 4 seasons        =   4
Total groups = 240. Every group gets one domain row (-> overall_stats.csv,
240 rows) and 72 cell rows (-> pixel_stats.csv, 17,280 rows). A group with
zero paired cell-days still gets a row: sufficient-stat combination naturally
yields a null (NaN) metric and explicit zero counts, never an omitted row.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from dataclasses import dataclass

from . import checkpoint, config, dates, metrics

SEASON_OF_MONTH = {
    12: "DJF", 1: "DJF", 2: "DJF",
    3: "MAM", 4: "MAM", 5: "MAM",
    6: "JJA", 7: "JJA", 8: "JJA",
    9: "SON", 10: "SON", 11: "SON",
}
SEASON_CODES = ("DJF", "MAM", "JJA", "SON")

CLIMATOLOGY_MARKER = "ALL"

GROUP_FIELDS = ("group_type", "water_year", "period")
IDENTITY_FIELDS = ("cell_id", "lon_center", "lat_center")
OVERALL_FIELDNAMES = GROUP_FIELDS + IDENTITY_FIELDS + config.CHECKPOINT_COLUMNS
PIXEL_FIELDNAMES = OVERALL_FIELDNAMES


class AggregationError(Exception):
    """Raised when the checkpoint set is incomplete or any checkpoint is invalid."""


@dataclass(frozen=True)
class LoadedCheckpoint:
    water_year: int
    year: int
    month: int
    cell_stats: list  # length N_CELLS, metrics.SufficientStats


def _load_checkpoints(
    results_dir: str, months: list[tuple[int, int, int]]
) -> list[LoadedCheckpoint]:
    """Read and validate exactly the given (water_year, year, month) checkpoints.
    Raises AggregationError listing every missing or invalid month if any are
    not usable.
    """
    loaded: list[LoadedCheckpoint] = []
    problems: list[str] = []

    for water_year, year, month in months:
        path = os.path.join(
            results_dir, config.CHECKPOINT_SUBDIR, f"{year:04d}-{month:02d}.csv"
        )
        if not os.path.exists(path):
            problems.append(f"{year:04d}-{month:02d}: missing checkpoint file")
            continue

        result = checkpoint.validate_checkpoint(
            path, expected_water_year=water_year, expected_year=year, expected_month=month
        )
        if not result.ok:
            problems.append(f"{year:04d}-{month:02d}: invalid ({'; '.join(result.errors)})")
            continue

        _, rows = checkpoint.read_checkpoint(path)
        cell_stats = [checkpoint.stats_from_row(rows[cell_id]) for cell_id in range(config.N_CELLS)]
        loaded.append(LoadedCheckpoint(water_year=water_year, year=year, month=month, cell_stats=cell_stats))

    if problems:
        raise AggregationError(
            f"{len(problems)} of {len(months)} checkpoints are not usable:\n"
            + "\n".join(problems)
        )
    if len(loaded) != len(months):
        raise AggregationError(f"expected {len(months)} checkpoints, loaded {len(loaded)}")

    return loaded


def load_all_checkpoints(results_dir: str) -> list[LoadedCheckpoint]:
    """Read and validate all 168 expected WY2010-2023 checkpoints. Raises
    AggregationError listing every missing or invalid month if any are not
    usable.
    """
    return _load_checkpoints(results_dir, list(dates.iter_calendar_months()))


def load_water_year_checkpoints(results_dir: str, water_year: int) -> list[LoadedCheckpoint]:
    """Read and validate the 12 checkpoints for a single water year. This is a
    single-water-year diagnostic loader, not a substitute for the pooled
    WY2010-2023 climatology that `load_all_checkpoints` feeds -- callers must
    not treat its output as a replacement for the full-archive product.
    """
    months = [(wy, year, month) for wy, year, month in dates.iter_calendar_months() if wy == water_year]
    if not months:
        raise AggregationError(f"water_year {water_year} is outside the configured WY{config.WY_START}-{config.WY_END} range")
    return _load_checkpoints(results_dir, months)


def _combine_cell_stats(stat_lists: list[list]) -> list:
    combined = [metrics.SufficientStats() for _ in range(config.N_CELLS)]
    for stat_list in stat_lists:
        for cell_id in range(config.N_CELLS):
            combined[cell_id] = combined[cell_id] + stat_list[cell_id]
    return combined


def _group_rows(group_type: str, water_year, period, cell_stats: list) -> tuple[dict, list[dict]]:
    cell_rows = []
    combined = metrics.SufficientStats()
    for cell_id in range(config.N_CELLS):
        lon_center, lat_center = _cell_center(cell_id)
        row = checkpoint.row_from_stats(cell_id, lon_center, lat_center, cell_stats[cell_id])
        row.update(group_type=group_type, water_year=water_year, period=period)
        cell_rows.append(row)
        combined = combined + cell_stats[cell_id]

    # n_calendar_days is shared uniformly across cells (see the note in
    # checkpoint.domain_row_from_cells) -- take it directly rather than
    # summing it N_CELLS times over.
    if cell_stats:
        combined.n_calendar_days = cell_stats[0].n_calendar_days

    domain_row = checkpoint.row_from_stats(checkpoint.DOMAIN_CELL_ID, float("nan"), float("nan"), combined)
    domain_row.update(group_type=group_type, water_year=water_year, period=period)
    return domain_row, cell_rows


def _cell_center(cell_id: int) -> tuple[float, float]:
    from . import regrid

    return regrid.cell_id_to_center(cell_id)


def build_aggregates(loaded: list[LoadedCheckpoint]) -> tuple[list[dict], list[dict]]:
    """Build (overall_rows, pixel_rows): 240 domain rows and 17,280 cell rows."""
    overall_rows: list[dict] = []
    pixel_rows: list[dict] = []

    by_wy_month: dict[tuple[int, int], list] = {}
    by_month_climatology: dict[int, list] = {}
    for lc in loaded:
        by_wy_month.setdefault((lc.water_year, lc.month), []).append(lc.cell_stats)
        by_month_climatology.setdefault(lc.month, []).append(lc.cell_stats)

    # 1. wy_month: 14 x 12 = 168
    for water_year in dates.iter_water_years():
        for _, _, month in _water_year_months(water_year, loaded):
            cell_stats = _combine_cell_stats(by_wy_month[(water_year, month)])
            domain_row, cell_rows = _group_rows("wy_month", water_year, month, cell_stats)
            overall_rows.append(domain_row)
            pixel_rows.extend(cell_rows)

    # 2. wy_season: 14 x 4 = 56
    for water_year in dates.iter_water_years():
        months_in_wy = [m for _, _, m in _water_year_months(water_year, loaded)]
        for season in SEASON_CODES:
            season_months = [m for m in months_in_wy if SEASON_OF_MONTH[m] == season]
            cell_stats = _combine_cell_stats(
                [s for m in season_months for s in by_wy_month[(water_year, m)]]
            )
            domain_row, cell_rows = _group_rows("wy_season", water_year, season, cell_stats)
            overall_rows.append(domain_row)
            pixel_rows.extend(cell_rows)

    # 3. climatology_month: 12
    for month in range(1, 13):
        cell_stats = _combine_cell_stats(by_month_climatology[month])
        domain_row, cell_rows = _group_rows("climatology_month", CLIMATOLOGY_MARKER, month, cell_stats)
        overall_rows.append(domain_row)
        pixel_rows.extend(cell_rows)

    # 4. climatology_season: 4
    for season in SEASON_CODES:
        season_months = [m for m in range(1, 13) if SEASON_OF_MONTH[m] == season]
        cell_stats = _combine_cell_stats([s for m in season_months for s in by_month_climatology[m]])
        domain_row, cell_rows = _group_rows("climatology_season", CLIMATOLOGY_MARKER, season, cell_stats)
        overall_rows.append(domain_row)
        pixel_rows.extend(cell_rows)

    if len(overall_rows) != config.EXPECTED_OVERALL_ROWS:
        raise AggregationError(f"overall row count {len(overall_rows)} != {config.EXPECTED_OVERALL_ROWS}")
    if len(pixel_rows) != config.EXPECTED_PER_CELL_ROWS:
        raise AggregationError(f"pixel row count {len(pixel_rows)} != {config.EXPECTED_PER_CELL_ROWS}")

    return overall_rows, pixel_rows


def _water_year_months(water_year: int, loaded: list[LoadedCheckpoint]) -> list[tuple[int, int, int]]:
    return [(lc.water_year, lc.year, lc.month) for lc in loaded if lc.water_year == water_year]


def _format_cell(column: str, value) -> str:
    if column in ("cell_id",):
        return str(int(value))
    if column in ("water_year",):
        return str(value)
    if column in ("lon_center", "lat_center") or column in checkpoint._FLOAT_COLUMNS:
        v = float(value)
        return "nan" if v != v else repr(v)
    if column in checkpoint._INT_COLUMNS:
        return str(int(value))
    return str(value)


def _write_csv(path: str, rows: list[dict], fieldnames: tuple[str, ...], metadata: dict) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-aggregate-", dir=directory)
    try:
        with os.fdopen(fd, "w", newline="") as f:
            f.write("# METADATA " + json.dumps(metadata, sort_keys=True) + "\n")
            writer = csv.writer(f)
            writer.writerow(fieldnames)
            for row in rows:
                writer.writerow([_format_cell(c, row[c]) for c in fieldnames])
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def write_aggregates(results_dir: str, loaded: list[LoadedCheckpoint] | None = None) -> tuple[str, str]:
    """Build and atomically write both aggregate CSVs. Returns their paths."""
    if loaded is None:
        loaded = load_all_checkpoints(results_dir)
    overall_rows, pixel_rows = build_aggregates(loaded)

    metadata = {
        "config_fingerprint": config.config_fingerprint(),
        "error_sign": config.ERROR_SIGN,
        "n_source_checkpoints": len(loaded),
        "n_overall_rows": len(overall_rows),
        "n_pixel_rows": len(pixel_rows),
    }

    overall_path = os.path.join(results_dir, config.OVERALL_STATS_FILENAME)
    pixel_path = os.path.join(results_dir, config.PIXEL_STATS_FILENAME)
    _write_csv(overall_path, overall_rows, OVERALL_FIELDNAMES, metadata)
    _write_csv(pixel_path, pixel_rows, PIXEL_FIELDNAMES, metadata)
    return overall_path, pixel_path
