#!/usr/bin/env python
"""Thin argparse wiring for the MERRA-2 vs STC-MODSCAG fSCA pipeline.

Subcommands: run, resume, aggregate, figures, examples, setup-credentials.
`run`/`resume`/`examples` require a live authenticated Earthdata session and
network access, neither of which is available in this development
environment -- see README.md for what has and has not been exercised here.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from fsca_eval import aggregate, config, earthdata, figures as figures_module, pipeline, regrid, significance  # noqa: E402


def _default_results_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), config.RESULTS_DIR)


def _default_dem_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "tests", "fixtures", "domain_dem_3dep.tif"
    )


def _bootstrap_mapping(transport: earthdata.Transport, tmp_dir: str) -> regrid.PixelCellMapping:
    """Build the static pixel->cell mapping from one day's MODSCAG tile geometry."""
    from datetime import date

    from fsca_eval import worker

    bootstrap_date = date(config.WY_START - 1, 10, 1)
    raw = worker.fetch_day(bootstrap_date, transport, tmp_dir)
    import numpy as np

    x = np.concatenate([t.pixel_x_sinusoidal for t in raw.modscag_tiles])
    y = np.concatenate([t.pixel_y_sinusoidal for t in raw.modscag_tiles])
    lon, lat = regrid.transform_sinusoidal_to_lonlat(x, y)
    return regrid.build_mapping(lon, lat)


def cmd_run_or_resume(args: argparse.Namespace) -> int:
    import functools
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir_root:
        tasks = pipeline.all_month_tasks()
        if args.water_year is not None:
            tasks = [t for t in tasks if t[0] == args.water_year]

        run_one_month = functools.partial(
            pipeline.run_one_month_worker,
            results_dir=args.results_dir,
            tmp_dir_root=tmp_dir_root,
        )

        executor = pipeline.build_process_pool(
            max_workers=args.max_workers, tmp_dir_root=tmp_dir_root
        )
        try:
            report = pipeline.run_scheduler(
                tasks, run_one_month, executor,
                max_workers=args.max_workers, max_runtime_minutes=args.max_runtime_minutes,
            )
        finally:
            executor.shutdown(wait=True)

    print(f"completed={len(report.completed)} failed={len(report.failed)} remaining={len(report.remaining)}")
    return 0 if not report.failed else 1


def cmd_aggregate(args: argparse.Namespace) -> int:
    overall_path, pixel_path = aggregate.write_aggregates(args.results_dir)
    print(f"wrote {overall_path}")
    print(f"wrote {pixel_path}")
    return 0


def cmd_single_year_figures(args: argparse.Namespace) -> int:
    """Single-water-year diagnostic figures (pooled spatial bias/MAE +
    monthly domain time series + monthly spatial grid) built only from that
    year's checkpoints. This is a QA view of one water year's data, not the
    pooled WY2010-2023 climatology or the wet/dry significance product
    cli.py figures produces.
    """
    loaded = aggregate.load_water_year_checkpoints(args.results_dir, args.water_year)

    dem = None
    if not args.no_dem:
        from fsca_eval import terrain

        dem = terrain.fetch_dem(
            config.DOMAIN_LON_EDGE_MIN, config.DOMAIN_LAT_EDGE_MIN,
            config.DOMAIN_LON_EDGE_MAX, config.DOMAIN_LAT_EDGE_MAX,
            terrain.RealDemTransport(),
        )

    pooled_stats = figures_module.full_climatology_stats(loaded)
    bias_mae_data = figures_module.build_bias_mae_figure_data(pooled_stats)
    bias_mae_path = os.path.join(args.results_dir, f"water_year_{args.water_year}_bias_mae_spatial.png")
    figures_module.render_bias_mae_figure(bias_mae_data, bias_mae_path, dem=dem)
    print(f"wrote {bias_mae_path}")

    series_data = figures_module.build_monthly_domain_series(loaded)
    series_path = os.path.join(args.results_dir, f"water_year_{args.water_year}_monthly_bias_mae.png")
    figures_module.render_monthly_domain_series_figure(
        series_data, series_path, title=f"WY{args.water_year}: monthly domain bias and MAE (MERRA-2 minus MODSCAG)"
    )
    print(f"wrote {series_path}")

    grid_data = figures_module.build_monthly_spatial_grid_data(loaded)
    grid_path = os.path.join(args.results_dir, f"water_year_{args.water_year}_monthly_spatial_grid.png")
    figures_module.render_monthly_spatial_grid_figure(
        grid_data, grid_path, title=f"WY{args.water_year} monthly spatial bias by cell", dem=dem
    )
    print(f"wrote {grid_path}")
    return 0


def cmd_figures(args: argparse.Namespace) -> int:
    loaded = aggregate.load_all_checkpoints(args.results_dir)

    dem = None
    if not args.no_dem:
        from fsca_eval import terrain

        dem = terrain.fetch_dem(
            config.DOMAIN_LON_EDGE_MIN, config.DOMAIN_LAT_EDGE_MIN,
            config.DOMAIN_LON_EDGE_MAX, config.DOMAIN_LAT_EDGE_MAX,
            terrain.LocalFileDemTransport(args.dem_path),
        )

    climatology_stats = figures_module.full_climatology_stats(loaded)
    bias_mae_data = figures_module.build_bias_mae_figure_data(climatology_stats)
    bias_mae_path = os.path.join(args.results_dir, config.BIAS_MAE_FIGURE_FILENAME)
    figures_module.render_bias_mae_figure(bias_mae_data, bias_mae_path, dem=dem)
    print(f"wrote {bias_mae_path}")

    index = significance.build_index(loaded)
    sig = significance.wet_dry_significance(index)
    wet_fsca = significance.pooled_composite_fsca(index, config.WET_WATER_YEARS)
    dry_fsca = significance.pooled_composite_fsca(index, config.DRY_WATER_YEARS)

    wet_dry_data = figures_module.build_wet_dry_figure_data(sig, wet_fsca, dry_fsca)
    wet_dry_path = os.path.join(args.results_dir, "water_year_2010_2023_wet_dry_nmb.png")
    figures_module.render_wet_dry_nmb_figure(wet_dry_data, sig, wet_dry_path, dem=dem)
    print(f"wrote {wet_dry_path}")

    monthly_nmb_data = figures_module.build_monthly_wet_dry_nmb_data(index)
    monthly_nmb_path = os.path.join(args.results_dir, "water_year_2010_2023_monthly_wet_dry_nmb.png")
    figures_module.render_monthly_wet_dry_grid_figure(
        monthly_nmb_data, monthly_nmb_path,
        title="Monthly wet/dry composite NMB (%)", cmap="RdBu_r", diverging=True,
        colorbar_label="NMB (%)", dem=dem,
    )
    print(f"wrote {monthly_nmb_path}")

    monthly_nmae_data = figures_module.build_monthly_wet_dry_nmae_data(index)
    monthly_nmae_path = os.path.join(args.results_dir, "water_year_2010_2023_monthly_wet_dry_nmae.png")
    figures_module.render_monthly_wet_dry_grid_figure(
        monthly_nmae_data, monthly_nmae_path,
        title="Monthly wet/dry composite NMAE (%)", cmap="YlOrRd", diverging=False,
        colorbar_label="NMAE (%)", dem=dem,
    )
    print(f"wrote {monthly_nmae_path}")

    monthly_fsca_data = figures_module.build_monthly_wet_dry_fsca_data(index)
    monthly_fsca_path = os.path.join(args.results_dir, "water_year_2010_2023_monthly_wet_dry_fsca.png")
    figures_module.render_monthly_wet_dry_grid_figure(
        monthly_fsca_data, monthly_fsca_path,
        title="Monthly wet/dry composite MODIS fSCA", cmap="YlOrRd", diverging=False,
        colorbar_label="Composite fSCA", dem=dem,
    )
    print(f"wrote {monthly_fsca_path}")
    return 0


def cmd_examples(args: argparse.Namespace) -> int:
    import tempfile

    from fsca_eval import examples as examples_module

    session = earthdata.create_session()
    ftp_pool = earthdata.FtpSlotPool(config.FTP_SEMAPHORE_SLOTS)
    transport = earthdata.RealTransport(session, ftp_pool)

    dem = None
    if not args.no_dem:
        from fsca_eval import terrain

        dem = terrain.fetch_dem(
            config.DOMAIN_LON_EDGE_MIN, config.DOMAIN_LAT_EDGE_MIN,
            config.DOMAIN_LON_EDGE_MAX, config.DOMAIN_LAT_EDGE_MAX,
            terrain.RealDemTransport(),
        )

    with tempfile.TemporaryDirectory() as tmp_dir_root:
        mapping = _bootstrap_mapping(transport, tmp_dir_root)

        for date_str, label in config.EXAMPLE_DAYS:
            from datetime import date as date_cls

            d = date_cls.fromisoformat(date_str)
            result = examples_module.generate_example(d, label, transport, mapping, args.results_dir, tmp_dir_root)
            if not result.cross_check_ok:
                print(f"{d} ({label}): cross-check FAILED: {result.cross_check_errors}")
                return 1

            nc_path = os.path.join(args.results_dir, f"water_year_2010_2023_example_{label}_{d.strftime('%Y%m%d')}.nc")
            png_path = os.path.join(args.results_dir, f"water_year_2010_2023_example_{label}_{d.strftime('%Y%m%d')}.png")
            examples_module.write_example_netcdf(result, nc_path)
            examples_module.render_example_figure(result, png_path, dem=dem)
            print(f"wrote {nc_path}")
            print(f"wrote {png_path}")

    return 0


def cmd_setup_credentials(_args: argparse.Namespace) -> int:
    from fsca_eval import setup_credentials

    return setup_credentials.main()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("run", "resume"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--results-dir", default=_default_results_dir())
        sub.add_argument("--max-workers", type=int, default=config.DEFAULT_MAX_WORKERS)
        sub.add_argument("--max-runtime-minutes", type=float, default=None)
        sub.add_argument(
            "--water-year", type=int, default=None,
            help="restrict to a single water year (e.g. 2023) instead of the full WY2010-2023 range",
        )
        sub.set_defaults(func=cmd_run_or_resume)

    sub = subparsers.add_parser("aggregate")
    sub.add_argument("--results-dir", default=_default_results_dir())
    sub.set_defaults(func=cmd_aggregate)

    sub = subparsers.add_parser("figures")
    sub.add_argument("--results-dir", default=_default_results_dir())
    sub.add_argument("--dem-path", default=_default_dem_path())
    sub.add_argument("--no-dem", action="store_true", help="skip the hillshade/contour overlay")
    sub.set_defaults(func=cmd_figures)

    sub = subparsers.add_parser(
        "single-year-figures",
        help="diagnostic pooled-spatial and monthly bias/MAE figures for one water year's checkpoints",
    )
    sub.add_argument("--results-dir", default=_default_results_dir())
    sub.add_argument("--water-year", type=int, required=True)
    sub.add_argument("--no-dem", action="store_true", help="skip the USGS 3DEP hillshade/contour overlay")
    sub.set_defaults(func=cmd_single_year_figures)

    sub = subparsers.add_parser("examples")
    sub.add_argument("--results-dir", default=_default_results_dir())
    sub.add_argument("--no-dem", action="store_true", help="skip the USGS 3DEP hillshade/contour overlay")
    sub.set_defaults(func=cmd_examples)

    sub = subparsers.add_parser("setup-credentials")
    sub.set_defaults(func=cmd_setup_credentials)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
