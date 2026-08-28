# Statistics and figure conventions

Use this reference for interpretation, statistical changes, and plot design.

## Spatial and elevation context

- Use the included coarse USGS 3DEP bare-earth DEM for geographic context.
- Put subtle grayscale hillshade below the metric layer.
- Keep the metric layer mostly opaque so relief does not materially distort the
  bias, MAE, or fSCA colors.
- Use only major labeled elevation contours at 2,000 and 3,000 m.
- Crop excess whitespace and keep longitude/latitude aspect geographically
  legible.

For wet/dry composites, show November–May as rows and present wet and dry
versions of normalized mean bias, normalized MAE, and MODIS fSCA. Include MODIS
fSCA in the elevation-dependence figure so error behavior can be interpreted in
the context of the reference snow climatology.

## Normalized metrics and masks

Normalized metrics become unstable when the reference snow signal approaches
zero.

- Composite NMB and NMAE: mask a group-month cell where composite MODIS fSCA is
  below 0.05.
- Cellwise NMB significance map: black out a group-month cell where pooled
  MODIS fSCA is below 0.10, and omit it from the test display.

Do not treat masked cells as zero error or nonsignificant observations. Retain
the mask explicitly in the companion CSV.

Use a diverging red/blue map centered at zero for signed normalized bias. Trim
the darkest ends so extreme cells do not dominate the visual. Use a sequential
scale for nonnegative MAE or MODIS fSCA. Keep one shared scale for directly
comparable panels.

## Wet/dry cellwise t-test

For each group, month, and MERRA-2 cell:

1. Compute one annual NMB for each of the four specified water years.
2. Use those four annual NMB values as the independent replicates.
3. Test `H0: mean annual NMB = 0` against the two-sided alternative.
4. With four finite years, use `df = 3`.
5. Hatch the cell when the raw two-sided `p < 0.05`.

The map color is the pooled group-month NMB, while the test operates on the
four annual NMB replicates. Preserve that distinction in captions and CSVs.

The current requested display is uncorrected. Do not show FDR-adjusted results,
FDR counts, or FDR terminology unless the user explicitly requests a separate
multiple-testing analysis.

## Why pixels are not degrees of freedom

MERRA cells in the same month share storms, snowline anomalies, model forcing,
and spatially coherent retrieval errors. They are spatially autocorrelated and
cannot be counted as independent temporal replicates. Testing each cell across
years answers whether that location's mean bias is consistently different from
zero across the chosen years.

Four years provide only three degrees of freedom, so report exact p values and
avoid overstating power. Hatching is evidence under this narrow test, not proof
that every day or every storm has the same bias.

## Figure interpretation checklist

Before describing a pattern, check:

- whether color represents percentage points or normalized percent;
- whether the plotted value is pooled or an equal-year mean;
- whether black or blank cells are reference-snow masks or missing support;
- whether hatching is raw p-value significance;
- whether a high normalized error is driven by small MODIS fSCA;
- whether terrain patterns align with elevation or simply with MERRA cell
  geometry; and
- whether wet/dry differences are robust across the four annual replicates.
