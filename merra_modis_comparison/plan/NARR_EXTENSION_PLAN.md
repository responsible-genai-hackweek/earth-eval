# NARR extension plan

## Objective

Add NARR direct 15Z snow cover to the existing model/MODSCAG pipeline while
making product access and target-grid geometry independently replaceable.

## Fixed scientific contract

- STC-MODSCAG v1 daily reference and missing-value semantics.
- Water years 2010–2023 and the Colorado center-selection domain.
- Equal-area MODIS pixel-center aggregation to the model grid.
- 80% daily reference-support threshold.
- Fine-pixel-area weighting and model-minus-MODSCAG error sign.
- Atomic monthly sufficient-statistic checkpoints and final statistics only.

## NARR-specific contract

- NOAA PSL annual `snowc.YYYY.nc` OPeNDAP source.
- Direct `snowc` fraction at exactly 15:00 UTC.
- Native AWIPS Grid 221 Lambert conformal cells; 185 centers in the configured
  Colorado domain.
- Public NOAA access with bounded retries; no authentication or raw-data cache.

## Implementation

1. Replace regular-grid-only MODSCAG assignment with a `SpatialGrid` interface
   that owns point-to-cell assignment, geographic coverage, stable cell
   metadata, and checkpoint fingerprint data.
2. Preserve `RegularLatLonGrid` behavior exactly for ERA5 and ERA5-Land, then
   add a native Lambert projected grid implementation for NARR.
3. Add an access-backend field to each model specification and dispatch monthly
   loading between CDS NetCDF retrieval and NOAA PSL OPeNDAP slicing.
4. Read only each month's 15Z NARR subset covering the selected native cells;
   validate timestamps, coordinates, units, range, and row/column identity.
5. Preserve existing ERA checkpoint fingerprints and aggregation metadata so
   completed work remains resumable.
6. Add NARR configuration, grid, loader, mapping, checkpoint, and CLI tests;
   run the public live preflight before declaring the adapter ready.
7. Add a 16-worker NARR launcher and document outputs and extension points.

## Acceptance gates

- Existing ERA5 and ERA5-Land tests and checkpoint fingerprints are unchanged.
- Native NARR cell centers match NOAA's published two-dimensional lat/lon grid
  within coordinate precision.
- A live sample returns finite 0–1 `snowc` at exactly 15Z with shape
  `1 × 185`.
- Every selected NARR cell has mapped MODSCAG support and archive eligibility is
  reported explicitly.
- Full tests pass without writing credentials or retaining source fields.
