# Water years 2010–2023 STC-MODSCAG comparison

Status: **implemented and validated with an authenticated month-level smoke test**

Planning date: 2026-08-26; checkpoint/resume revision: 2026-08-26

## 1. Fixed scientific scope

- Water years 2010 through 2023, inclusive
- Dates: 2009-10-01 through 2023-09-30
- 14 water years, 168 calendar months, and 5,113 calendar days
- Domain: 72 MERRA-2 cells centered within 109–104°W and 37–41°N
- Reference: `STC_MODSCGDRF_HIST` v1 `snow_fraction / 100`
- Model: MERRA-2 `M2T1NXLND` v5.12.4 `FRSNO`, index 15
  (15:00–16:00 UTC mean, timestamped 15:30 UTC)
- MERRA filename stream: 300 through 2010; 400 beginning in 2011 except for
  reprocessed stream 401 in September 2020 and June–September 2021
- Error sign: MERRA-2 minus STC-MODSCAG
- Target-cell support: at least 80% of complete-cell 500 m pixel-center support

This avoids splicing the historical STC-MODSCAG output with the different
post-2023 NRT product. The historical output changes its MOD09GA input from
collection 6 to 6.1 on 2021-12-28 but remains one published output product and
version.

## 2. Resumable 16-worker execution

### Calendar-month task unit

Use 168 independent calendar-month tasks in a spawn-based
`ProcessPoolExecutor(max_workers=16)`. A process creates one authenticated
Earthdata session and one static MODIS-to-MERRA mapping, then can accept
multiple month tasks. Within a month it:

1. Processes dates sequentially.
2. Requests the 72-cell MERRA subset for each date.
3. Downloads the three available MODSCAG tiles into a private temporary
   directory.
4. Reads only the relevant tile crops, reduces them, and deletes each granule
   immediately.
5. Atomically writes one validated monthly comparison-statistics checkpoint.

The month is the minimum recomputation unit. No daily tables, collocated
arrays, source granules, regridding caches, or partial-month files are accepted
as checkpoints.

### Planned shutdown and hard interruption

`--max-runtime-minutes 30` stops scheduling new months at the deadline and lets
the at-most-16 in-flight months finish. The command can therefore exceed the
requested duration by one month-task runtime. After `paused cleanly` is printed,
the computer can be shut down. Rerunning the same command validates existing
checkpoints and schedules only missing or invalid months.

Each CSV is written to a uniquely named temporary file, flushed and `fsync`ed,
then promoted with an atomic filesystem replacement. A power loss during a
write cannot turn a partial file into a valid month. Workers ignore `SIGINT` so
the parent can stop submission while in-flight workers finish their current
atomic checkpoints.

### Apple silicon concurrency

macOS assigns runnable processes to performance and efficiency cores; Python
has no supported portable P-core affinity interface. Sixteen normal-priority
processes allow macOS to use the available performance cores. The CLI sets
`VECLIB_MAXIMUM_THREADS=1`, `OMP_NUM_THREADS=1`, and
`OPENBLAS_NUM_THREADS=1` before NumPy is imported to prevent nested numerical
thread teams.

Only 16 tasks are submitted at once. This bounds process memory and enables a
runtime deadline to stop future work promptly. Each worker performs one
sequential MERRA request and one MODSCAG tile download at a time; there is no
nested network pool. All processes share an eight-slot semaphore around FTP
downloads because the archive rejects ten simultaneous connections from one
IP. A 421 response uses staggered 5/10/20-second backoff, and a failed month is
placed at the back of the queue before its second attempt.

## 3. Monthly checkpoint contract

The range-specific checkpoint directory contains `YYYY-MM.csv`. Each of the
168 valid files has 73 statistic rows: 72 MERRA cells and one domain row. Every
row records:

```text
sum_w
sum_w_error
sum_w_abs_error
valid_pixels
expected_pixels
observed_pixels
n_cell_days
n_days
n_calendar_days
bias_pp
mae_pp
support_fraction
direct_observation_fraction
```

The sufficient sums make later monthly, seasonal, and climatological merges
exact; pre-averaged bias and MAE are never averaged together. Checkpoint
metadata includes the cell identity, product versions, error sign, timing,
aggregation, domain, schema version, and a SHA-256 fingerprint of the
scientific configuration.

A checkpoint is reusable only if all of these pass:

1. Exact column schema and 73-row stable slot order
2. Matching configuration fingerprint and comparison metadata
3. Matching cell coordinates, global indices, and stable `cell_id`
4. Correct number of calendar days for that month
5. Nonnegative and internally consistent support/count fields
6. `abs(bias) <= MAE` and agreement between stored metrics and sufficient sums
7. Reconstruction of domain additive statistics from the 72 cell rows

An invalid file is reported and recomputed atomically. Complete checkpoints can
rebuild the final aggregate files without Earthdata access.

## 4. Pixel-level and domain aggregation

For a cell-day, MERRA fSCA is compared with the mean of its accepted equal-area
MODSCAG pixels. Daily errors are weighted by the accepted MODSCAG pixel count.
The domain metric pools those weighted cell-days. Each cell retains its own
paired-day and missing-reference counts; the domain also retains the number of
calendar days with at least one paired cell.

Final groups are:

- 14 water years × 12 months
- 14 water years × 4 meteorological seasons
- pooled WY2010–WY2023 climatology × 12 water-year months
- pooled climatology × 4 seasons

Expected final row counts:

- overall: 240
- per-cell: 17,280

Every cell receives a row for every group. A group with zero pairs uses a null
metric and explicit zero counts rather than omitting the row.

## 5. Persistent artifacts

The resumability request supersedes the earlier three-files-only rule. The
pipeline persists only comparison statistics and final visual output:

1. `results/water_year_2010_2023_monthly_checkpoints/` — 168 month CSVs
2. `results/water_year_2010_2023_overall_stats.csv`
3. `results/water_year_2010_2023_pixel_stats.csv`
4. `results/water_year_2010_2023_bias_mae.png`

The aggregate CSVs and plot are written only when all 168 checkpoints validate.
The plot contains monthly bias/MAE heatmaps and seasonal bias/MAE trajectories.

## 6. Missing-reference policy

- All-fill MODSCAG days are counted as missing and excluded; no new temporal
  interpolation or carry-forward is applied.
- Cell-days below 80% support are null for that cell only.
- Missing-reference counts remain separate for each cell and the domain.
- The known 2022-10-10 through 2022-10-27 all-fill interval must reproduce the
  completed WY2023 count of 18 missing domain-reference days.

## 7. Validation record and remaining full-run gates

Completed during implementation:

- 14 offline tests cover dates, grids, stream boundary, metric weighting,
  domain reconstruction, checkpoint round-trip and config mismatch rejection,
  final row counts, MODSCAG fill masking, and multi-year plot generation.
- Authenticated preflight decoded MERRA subsets on 2009-10-01 (stream 300) and
  2023-09-30 (stream 400), confirming 72-cell coordinates and index 15.
- An authenticated end-to-end run completed October 2009, atomically wrote its
  73-row checkpoint, reloaded it, and left no worker temporary directory.

Gates applied when the record finishes:

1. Verify all 5,113 dates across 168 valid checkpoints.
2. Decode MODSCAG before and after the 2021 MOD09GA collection transition.
3. Verify 240 overall and 17,280 per-cell final rows with no duplicate keys.
4. Reconstruct each overall group from its 72 cell accumulators.
5. Reproduce completed WY2023 domain metrics within floating-point tolerance.
6. Confirm only monthly comparison-stat checkpoints and three final artifacts
   persist.
