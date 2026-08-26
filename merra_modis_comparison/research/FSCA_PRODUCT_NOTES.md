# Daily fSCA product research

Research date: 2026-08-25; revised for the daily trial on 2026-08-26.

## Selected products

### MERRA-2

- Collection: `M2T1NXLND` / `tavg1_2d_lnd_Nx`, version 5.12.4
- Variable: `FRSNO`, fractional area of land snow cover (0–1)
- Grid: 0.5° latitude × 0.625° longitude, 361 × 576 cell centers
- Time: hourly averages stamped at the interval midpoint. Array index 15 is
  therefore the 15:00–16:00 UTC mean stamped 15:30 UTC; there is no
  instantaneous 15:00 field in this collection.
- Trial cells: centers within 109–104°W and 37–41°N, giving 9 latitude rows × 8
  longitude columns = 72 complete MERRA-2 cells.
- Granule filenames use production stream 300 through 2010 and stream 400 from
  2011 onward. The multi-year URL builder selects this stream from each date;
  authenticated preflight verified 2009-10-01 and 2023-09-30 endpoints.
- NASA reprocessed September 2020 and June–September 2021 under filename prefix
  `MERRA2_401`; the surrounding dates remain stream 400. The resolver handles
  those five months explicitly and preflight samples both reprocessed periods.
- DOI: [10.5067/RKPHT8KC1Y1T](https://doi.org/10.5067/RKPHT8KC1Y1T)

The land collection is land-model output rather than a whole-grid-box surface
mixture. The trial region is inland; aggregation and summary weights are based
on valid paired MODSCAG 500 m pixels.

References:

- [MERRA-2 file specification and documentation](https://gmao.gsfc.nasa.gov/gmao-products/merra-2/documentation_merra-2/)
- [MERRA-2 file specification](https://gmao.gsfc.nasa.gov/pubs/docs/Bosilovich785.pdf)
- [MERRA-2 FAQ, including `FRSNO` interpretation](https://gmao.gsfc.nasa.gov/gmao-products/merra-2/faq_merra-2/)
- [Earth Engine catalog entry for `M2T1NXLND`](https://developers.google.com/earth-engine/datasets/catalog/NASA_GSFC_MERRA_lnd_2)

### STC-MODSCAG

- Collection: `STC_MODSCGDRF_HIST`, version 1
- Variable: `snow_fraction`, the on-ground snow fraction adjusted for canopy,
  stored as 0–100 percent and converted to 0–1
- Diagnostic: `days_without_observation`; zero means directly observed on that
  date and positive values identify the length of the gap-filled series
- Grid: daily 500 m (463.3127 m nominal pixel size) MODIS sinusoidal tiles
- Trial tiles: `h09v04`, `h09v05`, and `h10v04`
- Trial coverage: 2022-10-01 through 2023-09-30 is present in the historical
  archive, whose final date is 2023-09-30
- DOI: [10.7265/f6j3-f387](https://doi.org/10.7265/f6j3-f387)

`snow_fraction`, not `viewable_snow_fraction`, is selected because the desired
comparison is modeled ground snow-covered area. STC-MODSCAG is explicitly a
spatially and temporally complete product, so gap-filled values are included.
The observed-pixel fraction is reported with the comparison metrics so the
degree of temporal interpolation remains visible.

References:

- [STC-MODSCAG/MODDRFS historical product page](https://nsidc.org/data/stc_modscgdrf_hist/versions/1)
- [Public historical product archive](ftp://sidads.colorado.edu/pub/DATASETS/STC_MODSCGDRF_HIST_v1)

## Access findings

- The STC-MODSCAG historical NetCDF files are available from the public NSIDC
  FTP archive without a login.
- The current MERRA-2 cloud OPeNDAP endpoint supports fine spatial/variable/time
  subsetting but requires a free NASA Earthdata Login. Anonymous access returns
  a login redirect; its protected S3 object returns HTTP 403.
- A public NCAR MERRA-2 forcing mirror was inspected but rejected because its
  schema does not contain `FRSNO`.
- No available MCP connector provides a more direct, credential-free semantic
  path for these two verified products.

## Scientific cautions carried into implementation

1. MODSCAG is treated as the observational reference, not error-free truth.
2. STC gap filling means “daily” does not imply a new clear-sky observation on
   every day; `days_without_observation` is summarized as a diagnostic.
3. Bias is signed `MERRA-2 - MODSCAG`, and both bias and MAE are reported in
   percentage points.
4. MODIS sinusoidal pixels are equal area. Assigning pixel centers to target
   cells gives an area-weighted average with a sub-500 m boundary approximation.
5. The requested “15Z value” maps to the 15:00–16:00 hourly mean stamped 15:30Z,
   not an instantaneous 15:00Z model state.

## WY2010–WY2025 expansion research

Research update: 2026-08-26

- The exact `STC_MODSCGDRF_HIST` reference used for WY2023 ends on
  2023-09-30 and therefore cannot cover WY2024 or WY2025.
- `MODSCGDRF_NRT` begins on 2023-11-01. Its technical reference documents that
  it reports observed snow cover rather than the historical canopy-adjusted
  ground-snow field; users may derive ground snow as `SNOW / (1 - VEG)`, but
  the processing and canopy adjustment still differ from the historical STC
  product. October 2023 is absent.
- `SPIRES_HIST` v1 provides daily 500 m, interpolated, canopy-adjusted on-ground
  `snow_fraction` and `days_without_observation` from 2000-03-01 through
  2025-09-30. Its archive contains all five western-US tiles and complete year
  directories needed for WY2010–WY2025. SPIReS is a different spectral-mixture
  retrieval, so it must not be relabeled MODSCAG.
- MERRA-2 `M2T1NXLND` granule availability was verified on 2025-09-30; the
  model side can cover the requested period without a collection change.

The scientifically preferred long-record route is to use SPIReS for the entire
2010–2025 span, with an explicit WY2023 overlap comparison against the existing
STC-MODSCAG trial. A strict-MODSCAG route requires separate historical and NRT
eras and must not be interpreted as one homogeneous time series.

References:

- [MODSCAG NRT landing page](https://nsidc.org/data/modscgdrf_nrt/versions/1)
- [MODSCAG NRT technical reference](https://nsidc.org/sites/default/files/documents/technical-reference/modscgdrf_nrt-technical_ref_v01.pdf)
- [SPIReS historical landing page](https://nsidc.org/data/spires_hist/versions/1)
