# MERRA-2 vs STC-MODSCAG fSCA comparison (WY2010-2023)

Compares daily fractional snow-covered area (fSCA) from two products over a
fixed Rocky Mountain domain (72 MERRA-2 cells, water years 2010-2023):

- **MERRA-2** `M2T1NXLND` v5.12.4, variable `FRSNO`, time index 15
  (15:00-16:00 UTC), read directly off its native 0.625°x0.5° grid.
- **STC-MODSCAG** `STC_MODSCGDRF_HIST` v1, variable `snow_fraction`, equal-area
  500 m pixels aggregated (pixel-center mean) up to the MERRA grid. MERRA is
  never resampled down to MODIS resolution.

Error is defined as **MERRA-2 minus MODSCAG** everywhere. See
`.claude/skills/snow-hydrology-fsca-evaluation/references/scientific-contract.md`
for the full scientific contract this implementation follows.

## Status

The pipeline (`src/fsca_eval/`), CLI (`cli.py`), and a complete offline test
suite (`tests/`, 142 tests) are implemented and passing:

```
/srv/conda/envs/notebook/bin/python -m pytest -q
```

**Status of real (non-synthetic) verification:**

1. **MERRA-2 fetch: implemented and verified against real Earthdata.**
   `RealTransport.fetch_merra_subset` (`src/fsca_eval/earthdata.py`) is a real
   authenticated HTTPS GET against GES DISC (`data.gesdisc.earthdata.nasa.gov`)
   plus an in-memory h5netcdf decode -- no OPeNDAP or cloud/S3 dependency.
   Confirmed against real granules at both MERRA stream boundaries
   (2009-10-01, stream 300; 2020-02-15, stream 400): decoded domain shape,
   FRSNO value range, and exact lon/lat coordinate match against
   `config.CELL_LON_CENTERS`/`CELL_LAT_CENTERS` (pure index slicing, no
   resampling).
2. **MODSCAG fetch: implemented and verified against the real archive.**
   `RealTransport.fetch_modscag_tiles` downloads each of the 3 domain-relevant
   STC-MODSCAG tiles (`h09v04`, `h09v05`, `h10v04`) via anonymous FTP from
   `sidads.colorado.edu` (no Earthdata login needed for this archive), decodes
   only the domain-cropped pixel region, and deletes the granule immediately.
   Confirmed against real granules for 2009-10-01 and 2020-02-15: correct tile
   set, exact coordinate/grid reconstruction (verified against the real
   granules' own GeoTransform metadata), and a full `regrid.build_mapping`/
   `apply_mapping` integration check giving nonzero expected pixels and
   >99% support for all 72 domain cells on the bootstrap day.
3. **DEM: real terrain data backs every spatial figure, including the pooled
   product.** `src/fsca_eval/terrain.py` supports two `DemTransport`
   implementations: `RealDemTransport` (live USGS 3DEP ImageServer fetch) and
   `LocalFileDemTransport` (reads a local GeoTIFF). A live call against
   `elevation.nationalmap.gov`'s ArcGIS ImageServer from this environment
   returned a full 800x600 grid (100% finite, ~1219-4256 m elevation range,
   consistent with the Rocky Mountain domain) in ~5 seconds; `cli.py
   single-year-figures` and `cli.py examples` fetch this live DEM by default
   (`--no-dem` skips it). `cli.py figures` -- the pooled WY2010-2023 product
   -- defaults instead to `LocalFileDemTransport` reading the checked-in
   `tests/fixtures/domain_dem_3dep.tif` (a real, not synthetic, 3DEP raster
   over the configured domain at the same 800x600 display grid
   `terrain.fetch_dem()` defaults to, sourced via Earth Engine
   (`scripts/earth_engine_dem_export.js`), small enough to check in (~1.6 MB)
   unlike a native-10m export of this domain (several GB)); pass `--dem-path`
   to point at a different raster, or `--no-dem` to skip it. All spatial
   figures draw the same combined hillshade + 2000/3000 m contour overlay.
   `tests/test_terrain.py` exercises `hillshade`/`crop_to_data_extent`/
   `LocalFileDemTransport` against this real raster, in addition to the
   existing synthetic-`DemGrid` coverage in `tests/test_figures.py`.

Before a real run, see `src/fsca_eval/setup_credentials.py`
(`cli.py setup-credentials`) to configure Earthdata login interactively; no
credentials are ever written into this repository.

## Pipeline

```
src/fsca_eval/
  config.py        scientific-contract constants + SHA-256 config fingerprint
  dates.py         water-year/month iteration, MERRA stream-boundary logic
  regrid.py        pixel-center aggregation of MODSCAG pixels onto MERRA cells
  metrics.py       sufficient-statistic accumulation, bias/MAE/NMB/NMAE formulas
  checkpoint.py    monthly 73-row (72 cells + domain) CSV schema, atomic write,
                   domain-row reconstruction, full validity checks
  earthdata.py     earthaccess-based auth, MERRA/MODSCAG fetch, 8-slot FTP
                   semaphore, transient-vs-fatal error handling
  worker.py        fetch_day() [I/O] / reduce_day() [pure aggregation]
  pipeline.py      resumable ProcessPoolExecutor scheduler (16 workers), month
                   task with injectable on_day_processed callback
  aggregate.py     builds the two final CSVs from validated checkpoints
  terrain.py       runtime DEM fetch, hillshade, 2000/3000 m contours, shared
                   and independent color-scale helpers
  significance.py  wet/dry cellwise t-test (df=3, raw p<0.05, no FDR); also
                   the same test/pooling windowed to a single composite month
                   at a time for the monthly wet/dry figures
  figures.py       bias/MAE figure, pooled wet/dry composite NMB figure, and
                   monthly (Nov-May) wet/dry NMB/NMAE/fSCA grid figures
  examples.py      illustrative example-day imagery (2011-01-15 high-snow,
                   2015-06-01 low-snow); cross-checks its recomputation of the
                   target month against the checkpoint already on disk
  setup_credentials.py  one-time interactive earthaccess.login() helper
cli.py             argparse wiring: run, resume, aggregate, figures,
                   single-year-figures, examples, setup-credentials
tests/             offline, synthetic-data only
results/           created at runtime, not checked in
```

## Running

```
cli.py setup-credentials              # one-time, interactive
cli.py run --max-workers 16           # or resume, after an interruption
cli.py run --water-year 2023          # restrict a run/resume to one water year
cli.py aggregate
cli.py figures
cli.py single-year-figures --water-year 2023   # single-WY diagnostic only, see below
cli.py examples                       # writes example NetCDF + PNG imagery
```

`cli.py figures` requires all 168 WY2010-2023 checkpoints and produces the
public scientific product -- five figures:

- the pooled climatology bias/MAE map (`water_year_2010_2023_bias_mae.png`)
- the pooled Nov-May wet/dry composite NMB significance figure
  (`water_year_2010_2023_wet_dry_nmb.png`)
- three monthly (Nov-May rows, wet/dry columns) wet/dry composite grids --
  NMB with the same significance hatching, NMAE, and MODIS fSCA
  (`water_year_2010_2023_monthly_wet_dry_{nmb,nmae,fsca}.png`)

All five draw a hillshade + 2000/3000 m contour terrain background by
default, from the checked-in `tests/fixtures/domain_dem_3dep.tif` DEM; pass
`--dem-path` to use a different raster or `--no-dem` to skip it entirely.

`cli.py single-year-figures` is a QA diagnostic: it loads only one water
year's 12 checkpoints and renders three figures for that year alone -- a
pooled spatial bias/MAE map, a monthly domain bias/MAE time series, and a
small-multiple grid of all 12 monthly spatial bias maps sharing one color
scale. It is not a substitute for the pooled multi-year product and does not
feed the wet/dry significance test, which requires water years as
independent replicates. Its spatial figures draw a live USGS 3DEP hillshade +
contour terrain background by default; pass `--no-dem` to skip the fetch.

## Scientific invariants

See CLAUDE.md and the scientific-contract skill reference for the full list.
Notably:

- Error sign is always MERRA-2 minus MODSCAG.
- MODSCAG is aggregated up to the MERRA grid; MERRA is never resampled down.
- A day only counts toward a cell if at least 80% of expected fine pixels are
  valid (`config.SUPPORT_THRESHOLD`).
- Sufficient statistics (sums/counts) are combined before deriving bias, MAE,
  NMB, NMAE, or composite fSCA -- derived metrics are never averaged directly.
- Years, not spatial cells or fine pixels, are the independent replicates for
  the wet/dry significance test (`config.SIGNIFICANCE_DF = 3`).
- The wet/dry NMB figure uses raw two-sided p < 0.05 hatching with no FDR
  correction.

### `sum_w_r` checkpoint column

Each monthly checkpoint row carries a 14th sufficient-statistic column,
`sum_w_r` (sum of weight times MODSCAG reference fraction), beyond the 13
named in the operational plan's original schema
(`y/repos/agent-test/shared/plans/2026-08-26-merra-modscag-wy2010-2023.md`,
section 3). NMB/NMAE and the composite-fSCA masking thresholds both need
`sum_w_r / sum_w`, and it cannot be reconstructed after the fact from
`bias_pp`/`mae_pp` alone. This is a documented, intentional departure -- see
the note in `src/fsca_eval/config.py` and the corresponding note added to the
operational plan's section 3.
