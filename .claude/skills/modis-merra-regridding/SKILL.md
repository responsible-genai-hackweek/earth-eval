---
name: modis-merra-regridding
description: Use when collocating a fine satellite raster with a coarse model grid - MODIS sinusoidal 500 m pixels onto MERRA-2 0.625x0.5 degree cells, or any comparable fine-to-coarse pairing - including choosing pixel-center binning versus interpolation, deriving cell edges, computing spatial support, masking under-supported cells, and area-weighting the result. Also use when reviewing a change to how the reference field is placed on the comparison grid.
---

# MODIS-to-MERRA Regridding

**REQUIRED BACKGROUND:** read the `snow-hydrology-fsca-evaluation` skill and its
scientific contract for the exact domain, products, and thresholds this project
fixes. This skill is the method and its failure modes.

**Core principle: always aggregate the fine field up to the coarse grid.** The
coarse cell is the physical unit the model actually predicts. Interpolating the
model down to 500 m manufactures structure the model never produced, and then
invites treating those fabricated samples as independent observations.

## The method

1. Take the coarse grid's published cell centers, select the target subset, and
   derive **complete** cell edges from the native spacing (half a cell either
   side of each center). Never infer edges from the data extent.
2. Crop each fine tile in its **native projected** coordinates to the target
   envelope, before any transformation. Cropping first is what keeps memory and
   coordinate-transform cost bounded.
3. Transform the cropped fine **pixel centers** to lon/lat **once**, and cache
   the resulting pixel-to-cell index array. It is static for the whole run;
   recomputing it per day is the single most common performance mistake here.
4. Per day, mask fill values, then reduce valid pixels per target cell with a
   `bincount`-style sum over the cached index. Reduce diagnostics
   (e.g. `days_without_observation == 0`) in the same pass.
5. Compute `support = valid_count / expected_count`, where `expected_count` is
   the count for a fully covered cell — not the count of pixels present today.
   Reject the cell-day below the threshold.
6. Compare the accepted cell mean with the coarse-grid value for that date.

## Why pixel centers, and what it costs

MODIS sinusoidal pixels are **equal area**, so a plain count of contributing
pixels is a valid area weight and a plain mean is an area-weighted mean. No
`cos(lat)` term belongs anywhere in this reduction.

Assigning a pixel to whichever cell contains its center is a hard boundary rule:
reproducible, order-independent, and cheap. It does not fractionally clip pixels
that straddle a cell edge. That is acceptable only because the fine pixel is
~1/100 of a cell edge length — the error is a one-pixel fringe. State the
approximation; do not silently upgrade it to fractional-area weighting, and do
not downgrade it to nearest-neighbour lookup of cell centers.

## Quick reference

| Decision | Rule |
|----------|------|
| Direction | Fine → coarse, always |
| Membership | Fine pixel center inside coarse cell edges |
| Cell value | Arithmetic mean of valid fine pixels |
| Weight for pooling | Valid fine-pixel count (equal-area) |
| Support denominator | Expected pixels for a complete cell |
| Below-threshold cell-day | Null for that cell only — not zero, not dropped domain-wide |
| Fill handling | Mask before reducing; validate the documented fill sentinel |
| Interpolation | Never bilinear/nearest onto the comparison grid |

## Common mistakes

- **Recomputing the mapping per day.** It is static. Build once per worker.
- **Transforming before cropping.** Wastes the majority of the work on pixels
  outside the domain.
- **Deriving `expected_count` from today's data.** Then support is 1.0 by
  construction and the threshold never fires.
- **Treating fill as zero snow.** `snow_fraction > 100` is fill, not bare
  ground; a zeroed fill value biases the reference low exactly where retrieval
  failed.
- **Partial edge cells in the domain.** Select only cells whose complete edges
  lie in the requested bounds, so every cell has the same expected support.
- **Silently changing the threshold** to rescue a sparse month. An
  under-supported month should show as missing, not as a quietly weaker average.

## Verification

- Selected cell count and coordinates match the contract exactly (72 cells;
  centers -108.75 to -104.375°E, 37.0 to 41.0°N).
- Round-trip a synthetic tile whose pixels are constructed to land in known
  cells; the reduced means must equal the planted values.
- A fully-fill day yields zero accepted cell-days, not zero-valued ones.
- Aggregated cell means stay in [0, 1]; support stays in [0, 1].
- Rendering one day's fine field, the cell means, and the cell edges together is
  the fastest way to catch a half-cell offset in the edge derivation.
