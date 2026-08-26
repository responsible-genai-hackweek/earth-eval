# MERRA-2 / MODSCAG fractional snow-cover comparison

This project compares daily MERRA-2 land snow-cover fraction with daily 500 m
STC-MODSCAG on-ground snow fraction. The configured experiment covers water
years 2010–2023 over the 72 MERRA-2 cells centered from 109–104°W and 37–41°N.

The research-plan-implement record is kept in:

- [`research/FSCA_PRODUCT_NOTES.md`](research/FSCA_PRODUCT_NOTES.md)
- [`plan/FSCA_PIPELINE_PLAN.md`](plan/FSCA_PIPELINE_PLAN.md)
- [`plan/MULTIYEAR_2010_2023_PLAN.md`](plan/MULTIYEAR_2010_2023_PLAN.md)
- [`plan/MULTIYEAR_2010_2025_PLAN.md`](plan/MULTIYEAR_2010_2025_PLAN.md)
  (superseded)

## Daily comparison contract

- Reference: `STC_MODSCGDRF_HIST` v1 `snow_fraction`, including the product's
  documented spatiotemporal interpolation; `days_without_observation` is
  retained as a coverage diagnostic.
- Model: MERRA-2 `M2T1NXLND` v5.12.4 `FRSNO`, time index 15. This hourly
  time-averaged field represents 15:00–16:00 UTC and is timestamped 15:30 UTC.
- Historical MERRA stream naming is resolved by date: stream 300 through 2010,
  stream 400 beginning in 2011, and reprocessed stream 401 for September 2020
  and June–September 2021.
- Spatial matching: equal-area 500 m MODIS sinusoidal pixel centers are binned
  into each complete MERRA-2 cell selected by its center.
- Error sign: MERRA-2 minus MODSCAG.
- Summaries: paired-fine-pixel-area weighted bias and MAE in percentage points,
  pooled by water-year month and meteorological season for each MERRA cell and
  for the whole domain.
- Missing-reference policy: an existing daily granule whose `snow_fraction` is
  all fill is excluded rather than interpolated again. Calendar, paired, and
  missing-reference day counts are retained.

## Installation

The tested environment is Python 3.12. Install the package and its test tools:

```bash
/Users/clintonalden/miniconda3/envs/env1/bin/python -m pip install -e '.[test]'
```

Configure NASA Earthdata Login with either `~/.netrc` or `EARTHDATA_TOKEN`.
The program never accepts credentials as command-line arguments or writes them
to its outputs.

## Run for about 30 minutes and resume later

Run this command from the project directory:

```bash
/Users/clintonalden/miniconda3/envs/env1/bin/python -m merra_modis_comparison \
  --start-water-year 2010 --end-water-year 2023 \
  --west -109 --east -104 --south 37 --north 41 \
  --workers 16 \
  --ftp-connections 8 \
  --max-runtime-minutes 30
```

The equivalent repeatable launcher is:

```bash
./run_30min.zsh
```

The 30-minute limit stops submission of new calendar months. Months already in
flight finish and save their atomic checkpoints, so the command can run a few
minutes longer than the requested limit. Wait for the `paused cleanly` message,
then it is safe to shut down the computer. Run the exact same command tomorrow;
validated months are skipped automatically.

Every calendar month is one recoverable task. A successful monthly checkpoint
contains mergeable comparison statistics and bias/MAE for the domain and all
72 MERRA cells. A checkpoint is accepted on resume only if its schema,
scientific configuration, cell identities, counts, metrics, and domain-from-cell
reconstruction all validate. An interrupted temporary file is never mistaken
for a completed month.

The 16 processes share an eight-slot MODSCAG FTP gate. The archive rejects ten
or more simultaneous connections from one IP, so this keeps MERRA requests and
local reductions parallel without overrunning the remote service. Connection-
limit responses receive a longer staggered backoff, and a failed month is moved
to the back of the work queue before its second attempt.

Downloaded MODSCAG granules and MERRA subsets are not cached. They remain in a
worker's temporary directory only while that day is being processed and are
deleted immediately. The persistent artifacts are:

- 168 monthly comparison-statistics CSV checkpoints under
  `results/water_year_2010_2023_monthly_checkpoints/`
- `results/water_year_2010_2023_overall_stats.csv`
- `results/water_year_2010_2023_pixel_stats.csv`
- `results/water_year_2010_2023_bias_mae.png`

## MODSCAG regridding diagnostic

`plot_one_day_regridding.zsh` downloads the three archived MODSCAG tiles for
15 January 2023 into a temporary directory and writes
`results/modscag_merra_grid_diagnostic_2023-01-15.png`. The figure shows the
native 500 m sinusoidal pixels, a one-cell zoom, and the arithmetic pixel-center
mean on the 0.625° × 0.5° MERRA-2 grid after the normal 80% support mask. The
downloaded granules are deleted when plotting finishes.

The three aggregate artifacts are written atomically only after all 168 months
have passed validation. Existing complete checkpoints can also rebuild them
without contacting Earthdata.

## Verification

```bash
/Users/clintonalden/miniconda3/envs/env1/bin/python -m pytest -q
/Users/clintonalden/miniconda3/envs/env1/bin/python -m merra_modis_comparison \
  --start-water-year 2010 --end-water-year 2023 --preflight-only
```

## November 2022–May 2023 spatial figure

`plot_nov2022_may2023_spatial.zsh` validates the seven monthly cell-stat
checkpoints concurrently and writes both the 14-panel bias/MAE map and a
two-panel elevation-dependence figure. The included coarse GeoTIFF is a 100 ×
90 EPSG:4326 subset of the USGS 3DEP bare-earth DEM. Subtle hillshade is shown
beneath the mostly opaque metric cells, with labeled 2000 and 3000 m contours.
Refresh the DEM with
`download_coarse_dem.zsh` if needed.

## Wet- and dry-year composite figures

`plot_wet_dry_composites.zsh` loads and validates the 56 November–May monthly
comparison checkpoints with 16 threads. It also builds a separate resumable set
of monthly MODIS fSCA statistics; downloaded daily granules are deleted
immediately and only the aggregate statistics persist. It combines sufficient
statistics before deriving the metrics, so the composites remain weighted by
valid MODSCAG pixel-days.
The wet composite uses water years 2011, 2017, 2019, and 2023; the dry composite
uses water years 2012, 2013, 2015, and 2018. It writes a shared-scale 7 × 6
spatial comparison and a shared-axis 2 × 3 elevation-dependence comparison,
including standalone MODIS fSCA, normalized mean bias, and normalized MAE.
Normalized metrics use the paired MODIS snow signal as their denominator and
are masked wherever the corresponding composite MODIS fSCA is below 5%.

## Wet/dry cellwise normalized-bias t-test

`plot_bias_significance.zsh` creates 14 November–May panels: wet WY2011, 2017,
2019, and 2023 beside dry WY2012, 2013, 2015, and 2018. Color represents pooled
normalized mean bias, `100 * sum_w_error / sum_w_modis_fsca`, on one shared
red/blue scale. Solid black cells have pooled group-month MODIS fSCA below 0.10.
For each non-masked cell, the two-sided one-sample t-test uses the four annual
NMB values as replicates, giving three degrees of freedom where all four years
are available. Hatching marks the uncorrected two-sided `p < 0.05` decision;
no multiple-testing or FDR correction is applied. Panel annotations report the
number of raw significant results among unmasked cells. The companion CSV
retains pooled NMB and MODIS fSCA, the mean annual NMB, masking status, t
statistic, raw p value and decision, sample size, and degrees of freedom.
