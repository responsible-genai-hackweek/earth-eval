# Scientific contract

Use this reference when deciding whether a proposed change is scientifically
equivalent to the established analysis.

## Domain and period

- Water years: 2010–2023, inclusive. A water year runs October–September.
- Requested center-selection bounds: 109–104°W and 37–41°N.
- Native MERRA-2 resolution: 0.625° longitude × 0.5° latitude.
- Selected grid: eight longitude columns × nine latitude rows = 72 cells.
- Cell centers: -108.75 to -104.375°E and 37.0 to 41.0°N.
- Complete cell edges: -109.0625 to -104.0625°E and 36.75 to 41.25°N.
- ERA5 CDS grid: 21 longitude columns × 17 latitude rows = 357 cells at 0.25°.
- ERA5-Land CDS grid: 51 longitude columns × 41 latitude rows = 2,091 cells at
  0.1°.

The end year is deliberately 2023 because the selected historical MODSCAG v1
record ends on 2023-09-30. Extending later requires a new product-continuity
assessment rather than silently mixing MODIS data streams.

## Daily product match

Reference:

- Product: `STC_MODSCGDRF_HIST` v1.
- Variable: `snow_fraction`, stored as 0–100 percent.
- Native grid: approximately 500 m equal-area MODIS sinusoidal pixels.
- Diagnostic: `days_without_observation`.

Supported model fields:

- Collection: MERRA-2 `M2T1NXLND` v5.12.4.
- Variable: `FRSNO`, stored as a 0–1 fraction.
- Time index: 15, the hourly mean for 15:00–16:00 UTC, timestamped 15:30 UTC.
- Filename stream: 300 through 2010, 400 from 2011, except 401 for September
  2020 and June–September 2021 reprocessing.
- ERA5 CDS dataset `reanalysis-era5-single-levels`, variable `snow_cover`,
  hourly 15:00 UTC field, on the regular 0.25° CDS distribution grid.
- ERA5-Land CDS dataset `reanalysis-era5-land`, variable `snow_cover`, hourly
  15:00 UTC field, on the regular 0.1° CDS distribution grid.

Pair records by calendar date. MERRA is an hourly average stamped 15:30 UTC;
the ERA fields are at 15:00 UTC. Do not substitute a daily mean or a different
hour without treating it as a new experiment.

## Regridding

1. Validate each granule's native sinusoidal coordinates and variable shapes.
2. Transform each 500 m pixel center from MODIS sinusoidal coordinates to
   longitude and latitude.
3. Bin the center into one cell of the selected model product grid using its
   target-cell edges.
4. Accept `snow_fraction <= 100`; values above 100 are fill.
5. Compute the cell reference as `sum(snow_fraction / 100) / valid_count`.
6. Compute support as `valid_count / expected_count` and mask support below 0.8.

This is an equal-area pixel-center mean. It does not fractionally clip MODIS
pixels at model-cell boundaries. That approximation is appropriate because the
fine pixels are much smaller than the target cells. Do not use bilinear
resampling for the comparison reference.

## Error metrics

Let `M` be model fSCA, `R` be aggregated MODSCAG fSCA, and `w` be the valid
MODSCAG pixel count for a paired cell-day.

```text
error = M - R
bias  = Σw(M - R) / Σw
MAE   = Σw|M - R| / Σw
NMB   = 100 × Σw(M - R) / ΣwR
NMAE  = 100 × Σw|M - R| / ΣwR
```

- Positive bias means the model is too snowy; negative bias means it is too low.
- Bias and MAE are converted to fSCA percentage points for presentation.
- NMB and NMAE are percentages relative to paired MODSCAG snow signal.
- Combine sufficient statistics first, then derive a composite metric. Do not
  average already-derived monthly metrics unless the scientific question calls
  for equal weighting of those months.

## Missingness and support

- An all-fill MODSCAG granule contributes no paired observation; do not invent a
  replacement interpolation.
- Retain calendar days, paired days, valid pixels, expected pixels, directly
  observed pixels, and missing-reference days.
- `days_without_observation == 0` counts direct observations. Other valid values
  are retained because interpolation is part of this chosen MODSCAG product.
- Daily model and MODSCAG values must both be finite before an error contributes.

## Fixed composite groups

- Wet water years: 2011, 2017, 2019, 2023.
- Dry water years: 2012, 2013, 2015, 2018.
- Months plotted: November through May.

These groups encode the hydrologic interpretation supplied for this analysis.
Do not recompute or relabel them from the resulting errors.
