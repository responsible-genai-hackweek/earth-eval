# ERA5 and ERA5-Land extension plan

Status: **implemented; authenticated live preflight passed 2026-08-26**

## 1. Scientific contract

- Period: water years 2010–2023, matching the homogeneous historical
  STC-MODSCAG v1 record.
- Domain: cells whose centers fall within 109–104°W and 37–41°N.
- Models: ERA5 fSCA diagnosed from `snow_depth` and `snow_density` on the CDS
  0.25° grid using ECMWF's documented equation, and ERA5-Land `snow_cover` on
  the CDS 0.1° grid.
- Time: each product's 15:00 UTC hourly field, paired to the same MODSCAG date.
- Reference aggregation: equal-area MODSCAG pixel-center binning separately to
  each model grid, followed by the existing 80% support rule.
- Error sign and weighting: model minus MODSCAG, pooled with valid MODSCAG
  pixel count as the fine-area weight.

## 2. Efficient execution

- Submit calendar months to a 16-process spawn pool.
- Download each day's three available MODSCAG tiles once per monthly task and
  reuse them for both model-grid reductions.
- Limit the shared MODSCAG FTP gate to eight connections and the shared CDS
  monthly-retrieval gate to four connections.
- Retrieve only the minimum source fields (two for ERA5, one for ERA5-Land), one
  UTC hour, one month, and the requested spatial subset from CDS.
- Hold decoded monthly model arrays in worker memory; delete their NetCDF files
  with the task temporary directory. Delete daily MODSCAG files immediately
  after both model reductions.

## 3. Resumability and persistence

- Write separate atomic monthly CSV checkpoints for ERA5 and ERA5-Land so one
  model can resume without invalidating the other.
- Validate schema, model, variable, time, grid coordinates, support threshold,
  error sign, sufficient statistics, and cell/domain reconstruction before
  reusing a checkpoint.
- Persist additive sums for bias, MAE, MODSCAG mean, NMB, and NMAE plus support,
  direct-observation, pair, and calendar-day counts.
- Save no raw or regridded model fSCA and no daily comparison table.

## 4. Final artifacts

For each model, write only when all 168 monthly checkpoints validate:

- `results/<model>_modis_water_year_2010_2023_overall_stats.csv`
- `results/<model>_modis_water_year_2010_2023_pixel_stats.csv`

The final files contain water-year monthly/seasonal rows and pooled
WY2010–WY2023 climatological monthly/seasonal rows. Per-cell outputs retain the
model-specific target coordinates and are never forced onto the MERRA-2 grid.

## 5. Validation gates

1. Compare request keys to the official CDS catalogue forms.
2. Decode a real one-day subset for each product and verify source variables,
   units, ERA5 diagnostic, exact 15Z timestamp, coordinate order, target-grid
   match, and 0–1 range.
3. Validate synthetic NetCDF handling for descending latitude and 0–360
   longitude conventions.
4. Test grid construction, weighted/normalized statistics, atomic checkpoint
   round trips, contract rejection, and final row identities.
5. Run the existing MERRA-2 regression suite unchanged.
6. Before a full campaign, run the authenticated preflight and inspect its
   report of cells capable of meeting the MODSCAG archive-support threshold.

All gates pass. The authenticated one-day live preflight returned the expected
ERA5 17×21 and ERA5-Land 41×51 Colorado arrays at exactly 15:00 UTC and produced
finite 0–1 fSCA values with the documented direct/diagnosed methods.
