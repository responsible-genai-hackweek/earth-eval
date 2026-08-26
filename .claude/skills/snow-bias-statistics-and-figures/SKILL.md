---
name: snow-bias-statistics-and-figures
description: Use when computing, testing, plotting, or interpreting snow-cover error statistics - bias, MAE, normalized mean bias, normalized MAE, wet/dry composites, cellwise t-tests, significance hatching, low-snow masking, elevation-dependence plots, or spatial bias maps - and when describing what a pattern in one of those figures does or does not show.
---

# Snow Bias Statistics and Figures

**REQUIRED BACKGROUND:** read the `snow-hydrology-fsca-evaluation` skill and its
scientific contract for the fixed metric definitions, masks, and wet/dry year
groups. This skill covers how to compute, test, draw, and read them.

**Core principle: combine sufficient statistics first, then derive the metric.**
A mean of monthly biases is a different number from a pooled bias, and a
normalized metric computed where there is almost no snow is noise with a
confident-looking sign.

## Metrics

With `M` = model fSCA, `R` = aggregated reference fSCA, `w` = valid reference
pixel count for a paired cell-day:

```text
error = M - R
bias  = Σw(M − R) / Σw
MAE   = Σw|M − R| / Σw
NMB   = 100 × Σw(M − R) / ΣwR
NMAE  = 100 × Σw|M − R| / ΣwR
```

Positive bias = model too snowy. Bias and MAE are reported in fSCA percentage
points; NMB and NMAE are percent of the paired reference snow signal. Always
label which of the two a color bar shows.

**Pooled is not the mean of annual.** The maps plot the pooled group-month NMB;
the significance test uses the four annual NMB values as replicates. Keep that
distinction in captions, CSV column names, and any sentence describing a result.

## Low-reference masking

Normalized metrics blow up as `R → 0`. Two different thresholds are in force,
and they are not interchangeable:

| Product | Mask |
|---------|------|
| Composite NMB / NMAE panels | Group-month cell with composite reference fSCA < 0.05 |
| Cellwise NMB significance map | Pooled reference fSCA < 0.10 — blacked out and excluded from the test display |

A masked cell is **not** zero error and **not** a nonsignificant result. Carry
the mask explicitly into the companion CSV so a reader can tell "masked" from
"tested and null".

## Cellwise wet/dry t-test

Per group (wet/dry), per month, per cell:

1. Compute one annual NMB for each of the four water years in the group.
2. Those four annual values are the independent replicates.
3. Test `H0: mean annual NMB = 0`, two-sided.
4. Four finite years → `df = 3`. Report exact p values; do not overstate power.
5. Hatch where raw two-sided `p < 0.05`.

**The display is deliberately uncorrected.** Do not show FDR-adjusted results,
FDR counts, or FDR vocabulary unless the user explicitly asks for a separate
multiple-testing analysis.

### Why cells are not degrees of freedom

Cells in the same month share storms, snowline anomalies, model forcing, and
spatially coherent retrieval error. They are strongly autocorrelated, so
counting 72 cells as 72 samples inflates significance by roughly the
autocorrelation length. Testing one cell across years asks the answerable
question: is *this location's* mean bias consistently nonzero across the chosen
years? Hatching is evidence under that narrow test — not proof that every day or
every storm carries the same bias.

## Figure conventions

- Terrain context from the coarse 3DEP DEM (see
  `merra_modis_comparison/research/COARSE_DEM_NOTES.md`): subtle grayscale
  hillshade **below** the metric layer.
- Keep the metric layer mostly opaque so relief does not shift the perceived
  color. Terrain is orientation, not data.
- Only major labeled contours, at 2,000 m and 3,000 m.
- Diverging red/blue centered at zero for signed NMB; trim the darkest ends so a
  few extreme cells do not eat the dynamic range. Sequential scale for
  nonnegative MAE or reference fSCA.
- One shared scale across directly comparable panels; never a per-panel autoscale
  in a grid meant for comparison.
- Wet/dry composites: November-May as rows, with wet and dry versions of NMB,
  NMAE, and reference fSCA. Include reference fSCA in the elevation-dependence
  figure so error can be read against the snow climatology.
- Crop excess whitespace; keep the lon/lat aspect geographically legible.

## Interpretation checklist

Before describing any pattern, confirm:

- percentage points or normalized percent?
- pooled value or equal-year mean?
- are blank/black cells a low-snow mask or missing support?
- is the hatching raw-p or corrected?
- is a large normalized error just a small denominator?
- does the spatial pattern follow elevation, or merely the MERRA cell geometry?
- is the wet/dry difference robust across all four annual replicates?

## Verification

- `abs(bias) <= MAE` for every group, within floating-point tolerance.
- Every group has a row, including zero-pair groups (null metric, explicit zero
  counts) — never omit the row.
- Domain statistics reconstruct from the per-cell statistics.
- **Look at the rendered PNG.** A plotting command exiting 0 says nothing about
  month order, mask placement, hatch visibility, color limits, or labels.
