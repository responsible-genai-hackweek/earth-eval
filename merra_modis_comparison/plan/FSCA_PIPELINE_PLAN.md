# Daily fSCA comparison pipeline — implementation plan

Status: **implemented and trialed successfully for water year 2023**

## 1. Trial contract

- Water year: 2023 (2022-10-01 through 2023-09-30)
- Domain: complete MERRA-2 cells whose centers lie within 109–104°W and 37–41°N
- Model: daily MERRA-2 `M2T1NXLND` v5.12.4 `FRSNO`, time index 15
  (15:00–16:00 mean, stamped 15:30 UTC)
- Reference: daily `STC_MODSCGDRF_HIST` v1 `snow_fraction / 100`
- MODSCAG tiles: `h09v04`, `h09v05`, `h10v04`
- Target-cell support: at least 80% of the expected 500 m pixel-center support
- Error: `FRSNO - snow_fraction`
- Metrics: paired-fine-pixel-area weighted bias and MAE, pooled over all valid
  cell-day pairs for each water-year month and meteorological season

For a group of paired cell-day values:

```text
error = FRSNO_merra2_15Z - fSCA_modscag_on_merra_grid
bias  = sum(valid_modscag_pixel_count * error) / sum(valid_modscag_pixel_count)
MAE   = sum(valid_modscag_pixel_count * abs(error)) / sum(valid_modscag_pixel_count)
```

The constant MODIS pixel area cancels in both ratios. Results are multiplied by
100 and reported in percentage points.

## 2. Spatial aggregation

1. Select the 72 target MERRA-2 cells from published coordinate centers and
   derive their complete cell edges.
2. For each required MODIS sinusoidal tile, crop in projected coordinates to
   the target-grid envelope.
3. Transform cropped 500 m pixel centers to longitude/latitude once per worker
   and map them to target cells. Pixel centers are the repeatable boundary rule.
4. For each day, use the precomputed mapping to reduce valid `snow_fraction`
   values with `bincount`; reduce `days_without_observation == 0` in parallel.
5. Reject target cell-days below the configured support threshold, then compare
   the aggregated MODSCAG fraction with MERRA-2 `FRSNO`.

The source projection is equal area, so pixel counts are valid area weights.
Only a one-pixel fringe at target-cell boundaries is approximated.

## 3. Streaming and parallel execution

- Authenticate and read one tiny MERRA-2 subset before starting source-data
  downloads. This makes missing credentials or a changed schema fail fast.
- Split the ordered dates into contiguous chunks and submit one chunk per
  bounded process-pool worker. The default is two workers to balance local I/O
  with archive load.
- Each worker keeps only static pixel-to-cell index arrays and small sufficient
  statistics. For each date it downloads three MODSCAG files into a private
  `TemporaryDirectory`, reads cropped arrays, requests the 72-cell MERRA-2
  subset, updates month/season accumulators, and deletes all three files.
- Workers return only `sum_w`, `sum_w_error`, `sum_w_abs_error`, counts, and
  observation diagnostics. The parent merges chunks in deterministic order.
- The final CSV and plot are written atomically after all 365 dates succeed.
  No source granule, regridded field, manifest, cache, or daily comparison table
  is retained.

## 4. Final artifacts

- `results/water_year_2023_comparison_stats.csv`: 12 month rows and 4 season
  rows, including bias, MAE, valid cell/day counts, support, and observed-pixel
  fraction.
- `results/water_year_2023_bias_mae.png`: presentation-ready monthly/seasonal
  summary plot generated only from the final statistics.

The CSV records the product versions, variable names, time interpretation,
domain, aggregation rule, error sign, calendar-day count, compared-day count,
and number of all-fill/missing-reference days.

## 5. Validation gates

1. Decode one real MODSCAG granule and verify shapes, projection, 0–100 range,
   fill value 255, and `days_without_observation` range.
2. Verify MERRA subset shape is 9 × 8, coordinates match the requested centers,
   and values are finite or documented fill.
3. Unit-test target-grid selection, pixel aggregation, support masking, metric
   sign/weighting, and season assignment.
4. Verify one-worker and two-worker sufficient-statistic reductions agree.
5. Confirm 365 successful dates and the expected month/season day counts.
6. Check values in [0,1], MAE ≥ 0, and `abs(bias) ≤ MAE` within tolerance.
7. Confirm task-local directories are gone and only the CSV and plot were added
   to `results/`.

## 6. Authentication and failure policy

- Credentials are read through `earthaccess` from `~/.netrc` or environment
  variables; they are never accepted as CLI arguments, printed, or stored in
  project files.
- Network operations use bounded retries with backoff.
- A missing granule, changed variable/schema, or exhausted retry is fatal. An
  existing all-fill reference day is explicitly counted and excluded from the
  metric rather than silently skipped or re-interpolated.
- Final files are created via a temporary sibling and atomic rename, so a
  failed run cannot replace valid prior results.
