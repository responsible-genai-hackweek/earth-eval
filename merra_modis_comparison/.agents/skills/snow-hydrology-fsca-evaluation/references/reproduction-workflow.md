# Reproduction workflow

Use this reference to reproduce, resume, or regenerate the analysis efficiently.

## Inspect before running

Read:

- `README.md` for the public experiment description;
- `research/FSCA_PRODUCT_NOTES.md` for product research;
- `research/ERA5_PRODUCT_NOTES.md` for ERA product research;
- `research/NARR_PRODUCT_NOTES.md` for NARR product and grid research;
- `plan/FSCA_PIPELINE_PLAN.md` and `plan/MULTIYEAR_2010_2023_PLAN.md` for the
  research-plan-implement record;
- `plan/ERA5_ERA5_LAND_PLAN.md` for the multi-model extension;
- `plan/NARR_EXTENSION_PLAN.md` for the projected-grid/backend extension;
- `src/merra_modis_comparison/config.py` for the domain and operational limits;
- `src/merra_modis_comparison/products.py` for data access and regridding; and
- checkpoint metadata before assuming an existing file is compatible.

## Environment and authentication

The tested interpreter is:

```text
/Users/clintonalden/miniconda3/envs/env1/bin/python
```

Install with `python -m pip install -e '.[test]'`. MERRA-2 access requires NASA
Earthdata credentials through `~/.netrc` or `EARTHDATA_TOKEN`. MODSCAG is
downloaded from a public FTP archive. ERA5 access requires a CDS personal
access token through `~/.cdsapirc` or `CDSAPI_KEY`, plus accepted ERA5 and
ERA5-Land licences. Never print, copy, or commit credentials.
NARR access through NOAA PSL OPeNDAP is public and requires no credentials.

Run the preflight before a fresh download campaign:

```bash
python -m merra_modis_comparison \
  --start-water-year 2010 --end-water-year 2023 \
  --preflight-only
```

## Main comparison

For a complete run:

```bash
./run_to_completion.zsh
```

For an interruptible session:

```bash
./run_30min.zsh
```

The latter stops scheduling new monthly tasks after about 30 minutes but lets
in-flight tasks finish. Wait for `paused cleanly` before shutting down. Running
the same command again validates and skips completed checkpoints.

Operational defaults:

- 16 monthly worker processes;
- eight shared MODSCAG FTP slots, kept below the archive's ten-connection cap;
- four daily network retries and two full-month attempts;
- atomic checkpoint writes; and
- no raw-data cache.

Do not increase FTP slots to match CPU workers. The limiting resource is the
archive connection policy, not local CPU availability.

For the shared ERA5/ERA5-Land run, use:

```bash
./run_era5_era5_land_to_completion.zsh
```

It retains the same 16 workers and eight FTP slots, adds a four-request CDS
gate, downloads MODSCAG once per day for both grids, and writes independent
model-month checkpoints. Monthly CDS NetCDF subsets are task-local temporary
files and must never be moved into `results/`.

For NARR on its native Lambert conformal grid, use:

```bash
./run_narr_to_completion.zsh
```

It uses the same 16 workers and eight FTP slots, limits concurrent public NOAA
OPeNDAP reads to four, reads one monthly 15Z subset into memory per task, and
writes only model-specific monthly sufficient-statistic checkpoints and final
CSVs.

## Checkpoint logic

The main run produces 168 monthly CSVs in
`results/water_year_2010_2023_monthly_checkpoints/`. A checkpoint is reusable
only if its schema, products, error sign, aggregation, domain, cell identities,
counts, and domain reconstruction validate.

Daily MODSCAG files live only inside the worker's temporary directory and are
unlinked after the day. MERRA is remotely subset and not cached. Preserve this
streaming design when extending the pipeline.

When a requested statistic can be reconstructed from `sum_w`,
`sum_w_error`, `sum_w_abs_error`, `sum_w_fsca`, counts, and day totals, derive it
from checkpoints. Reprocess raw days only if a required sufficient statistic is
absent or the scientific contract changes.

## Derived outputs

Run in this order when rebuilding everything from completed comparison
checkpoints:

1. `./download_coarse_dem.zsh` only if the included DEM is missing or needs
   refreshing.
2. `./plot_nov2022_may2023_spatial.zsh` for the seven-month bias/MAE and
   elevation figures.
3. `./plot_wet_dry_composites.zsh` to build or resume the 56 MODSCAG-only
   monthly checkpoints and generate wet/dry spatial and elevation composites.
4. `./plot_bias_significance.zsh` for the wet/dry normalized-bias t-test figure
   and cellwise CSV.
5. `./plot_one_day_regridding.zsh` when a visual audit of grid aggregation is
   useful. Its daily granules are temporary.

## Verification

Run:

```bash
python -m pytest -q
```

After changing a figure, inspect the rendered PNG rather than relying only on a
successful plotting command. Check titles, month order, masks, color limits,
hatching, terrain visibility, whitespace, and axis labels.

After a scientific change, spot-check the output CSV metadata and confirm that
the number and identity of target cells remain 72 for MERRA-2 or 185 for NARR
unless the domain was intentionally changed.
