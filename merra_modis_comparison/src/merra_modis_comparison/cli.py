from __future__ import annotations

import os

# Set these before importing NumPy-backed project modules. Sixteen worker
# processes should each have one numerical thread, not their own BLAS team.
for _thread_variable in (
    "VECLIB_MAXIMUM_THREADS",
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
):
    os.environ[_thread_variable] = "1"

import argparse
from pathlib import Path

from .config import RunConfig
from .pipeline import (
    OVERALL_CSV_FIELDS,
    PIXEL_CSV_FIELDS,
    preflight,
    run,
    write_csv,
)
from .products import AuthenticationRequired


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare daily MERRA-2 FRSNO with daily STC-MODSCAG fSCA using "
            "atomic monthly checkpoints"
        )
    )
    parser.add_argument(
        "--start-water-year", type=int, default=2010,
        help="first water year, inclusive (default: 2010)",
    )
    parser.add_argument(
        "--end-water-year", type=int, default=2023,
        help="last water year, inclusive (default: 2023)",
    )
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
        help=(
            "shared MODSCAG FTP connection limit across workers; must remain "
            "below the archive's 10-per-IP cap (default: 8)"
        ),
    )
    parser.add_argument("--support-threshold", type=float, default=0.8)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument(
        "--month-attempts",
        type=int,
        default=2,
        help="maximum full-month attempts after daily network retries",
    )
    parser.add_argument(
        "--max-runtime-minutes",
        type=float,
        help=(
            "stop scheduling new months after this duration, finish in-flight "
            "months, and exit with resumable checkpoints"
        ),
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        help="monthly checkpoint directory (default is range-specific under results)",
    )
    parser.add_argument(
        "--overall-output", type=Path,
        help="final overall-statistics CSV (written only when all months exist)",
    )
    parser.add_argument(
        "--pixel-output", type=Path,
        help="final per-MERRA-cell statistics CSV (written only when complete)",
    )
    parser.add_argument(
        "--plot", type=Path,
        help="final multi-year bias/MAE plot (written only when complete)",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="validate credentials, products, timing, grid, and variables",
    )
    return parser


def _default_paths(
    start_water_year: int, end_water_year: int
) -> tuple[Path, Path, Path, Path]:
    stem = f"water_year_{start_water_year}_{end_water_year}"
    results = Path("results")
    return (
        results / f"{stem}_monthly_checkpoints",
        results / f"{stem}_overall_stats.csv",
        results / f"{stem}_pixel_stats.csv",
        results / f"{stem}_bias_mae.png",
    )


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.water_year is None:
        start_water_year = args.start_water_year
        end_water_year = args.end_water_year
    else:
        start_water_year = end_water_year = args.water_year
    defaults = _default_paths(start_water_year, end_water_year)
    checkpoint_directory = args.checkpoint_dir or defaults[0]
    overall_output = args.overall_output or defaults[1]
    pixel_output = args.pixel_output or defaults[2]
    plot_output = args.plot or defaults[3]

    config = RunConfig(
        start_water_year=start_water_year,
        end_water_year=end_water_year,
        west=args.west,
        east=args.east,
        south=args.south,
        north=args.north,
        workers=args.workers,
        ftp_connections=args.ftp_connections,
        support_threshold=args.support_threshold,
        retries=args.retries,
        month_attempts=args.month_attempts,
    )
    try:
        if args.preflight_only:
            preflight(config)
            return
        outcome = run(
            config,
            checkpoint_directory,
            max_runtime_minutes=args.max_runtime_minutes,
        )
        if not outcome.complete:
            print(
                f"paused cleanly with {outcome.completed_months}/"
                f"{outcome.total_months} monthly checkpoints; no final aggregate "
                "was written. Rerun the same command to resume."
            )
            return
        if outcome.overall_rows is None or outcome.pixel_rows is None:
            raise RuntimeError("complete run returned no final statistics")
        write_csv(outcome.overall_rows, overall_output, OVERALL_CSV_FIELDS)
        write_csv(outcome.pixel_rows, pixel_output, PIXEL_CSV_FIELDS)
        from .plotting import write_metric_plot

        write_metric_plot(outcome.overall_rows, plot_output)
    except AuthenticationRequired as exc:
        parser.exit(2, f"authentication required: {exc}\n")
    except KeyboardInterrupt:
        parser.exit(
            130,
            "interrupted; completed monthly checkpoints were preserved. "
            "Rerun the same command to resume.\n",
        )
    print(f"wrote {overall_output}")
    print(f"wrote {pixel_output}")
    print(f"wrote {plot_output}")
