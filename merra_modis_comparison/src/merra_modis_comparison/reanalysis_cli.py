from __future__ import annotations

import os

for _thread_variable in (
    "VECLIB_MAXIMUM_THREADS",
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
):
    os.environ[_thread_variable] = "1"

import argparse
from pathlib import Path

from .pipeline import write_csv
from .products import AuthenticationRequired
from .reanalysis_config import MODEL_SPECS, ReanalysisRunConfig
from .reanalysis_pipeline import (
    OVERALL_CSV_FIELDS,
    PIXEL_CSV_FIELDS,
    preflight,
    run,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare selected 15Z reanalysis snow-cover products with daily "
            "STC-MODSCAG on each product's native distribution grid"
        )
    )
    parser.add_argument(
        "--models",
        nargs="+",
        choices=tuple(MODEL_SPECS),
        default=["era5", "era5-land"],
        help="models to evaluate together (default: era5 era5-land)",
    )
    parser.add_argument("--start-water-year", type=int, default=2010)
    parser.add_argument("--end-water-year", type=int, default=2023)
    parser.add_argument(
        "--water-year",
        type=int,
        help="single-water-year shortcut; overrides both range options",
    )
    parser.add_argument("--west", type=float, default=-109.0)
    parser.add_argument("--east", type=float, default=-104.0)
    parser.add_argument("--south", type=float, default=37.0)
    parser.add_argument("--north", type=float, default=41.0)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument(
        "--ftp-connections",
        type=int,
        default=8,
        help="shared MODSCAG FTP connection limit (default: 8; maximum: 9)",
    )
    parser.add_argument(
        "--model-connections",
        "--cds-connections",
        dest="cds_connections",
        type=int,
        default=4,
        help="maximum concurrent remote model requests (default: 4)",
    )
    parser.add_argument("--support-threshold", type=float, default=0.8)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--month-attempts", type=int, default=2)
    parser.add_argument(
        "--max-runtime-minutes",
        type=float,
        help=(
            "stop scheduling new months after this duration, finish in-flight "
            "months, and exit with resumable stats-only checkpoints"
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("results"),
        help="directory for model-specific checkpoints and final CSVs",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="validate CDS credentials, requests, timing, grids, and variables",
    )
    return parser


def _paths(
    output_root: Path,
    model_id: str,
    start_water_year: int,
    end_water_year: int,
) -> tuple[Path, Path, Path]:
    slug = model_id.replace("-", "_")
    stem = f"{slug}_modis_water_year_{start_water_year}_{end_water_year}"
    return (
        output_root / f"{stem}_monthly_checkpoints",
        output_root / f"{stem}_overall_stats.csv",
        output_root / f"{stem}_pixel_stats.csv",
    )


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.water_year is None:
        start_water_year = args.start_water_year
        end_water_year = args.end_water_year
    else:
        start_water_year = end_water_year = args.water_year
    model_ids = tuple(dict.fromkeys(args.models))
    config = ReanalysisRunConfig(
        start_water_year=start_water_year,
        end_water_year=end_water_year,
        model_ids=model_ids,
        west=args.west,
        east=args.east,
        south=args.south,
        north=args.north,
        workers=args.workers,
        ftp_connections=args.ftp_connections,
        cds_connections=args.cds_connections,
        support_threshold=args.support_threshold,
        retries=args.retries,
        month_attempts=args.month_attempts,
    )
    paths = {
        model_id: _paths(
            args.output_root,
            model_id,
            start_water_year,
            end_water_year,
        )
        for model_id in model_ids
    }
    try:
        if args.preflight_only:
            preflight(config)
            return
        outcome = run(
            config,
            {model_id: model_paths[0] for model_id, model_paths in paths.items()},
            max_runtime_minutes=args.max_runtime_minutes,
        )
        if not outcome.complete:
            print(
                f"paused cleanly with {outcome.completed_checkpoints}/"
                f"{outcome.total_checkpoints} model-month checkpoints; final "
                "aggregates were not written. Rerun the same command to resume."
            )
            return
        if outcome.overall_rows is None or outcome.pixel_rows is None:
            raise RuntimeError("complete run returned no final statistics")
        for model_id in model_ids:
            _, overall_output, pixel_output = paths[model_id]
            write_csv(
                outcome.overall_rows[model_id], overall_output, OVERALL_CSV_FIELDS
            )
            write_csv(
                outcome.pixel_rows[model_id], pixel_output, PIXEL_CSV_FIELDS
            )
            print(f"wrote {overall_output}")
            print(f"wrote {pixel_output}")
    except AuthenticationRequired as exc:
        parser.exit(2, f"authentication required: {exc}\n")
    except KeyboardInterrupt:
        parser.exit(
            130,
            "interrupted; completed monthly statistics checkpoints were preserved. "
            "Rerun the same command to resume.\n",
        )


if __name__ == "__main__":
    main()
