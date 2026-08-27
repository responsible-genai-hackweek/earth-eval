# ERA5 and ERA5-Land fSCA product research

Research date: 2026-08-26.

## Selected model fields

### ERA5

- CDS dataset: `reanalysis-era5-single-levels`
- Variable: `snow_cover` (NetCDF short name normally `snowc`), documented as
  the grid-box fraction occupied by snow. ECMWF parameter metadata uses percent
  units, so the decoder uses the file `units` attribute to convert percent
  encodings to a 0–1 comparison fraction.
- Time: hourly field at 15:00 UTC for each MODSCAG calendar date
- Comparison grid: the CDS regular 0.25° latitude/longitude distribution grid
- Important resolution qualification: this CDS entry is a regular-grid subset
  regridded from the full ERA5 native representation; it is the product grid to
  which MODSCAG is aggregated, not the spectral/native ERA5 grid
- DOI: [10.24381/cds.adbb2d47](https://doi.org/10.24381/cds.adbb2d47)

Official sources:

- [ERA5 hourly single-level catalogue](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels)
- [ERA5 documentation](https://confluence.ecmwf.int/display/CKB/ERA5%3A+data+documentation)
- [ECMWF `snowc` parameter record](https://codes.ecmwf.int/grib/param-db/?id=260038)

### ERA5-Land

- CDS dataset: `reanalysis-era5-land`
- Variable: `snow_cover` (NetCDF short name normally `snowc`), documented as
  the fraction of a cell occupied by snow. Percent-encoded files are converted
  to 0–1 from their `units` metadata.
- Time: hourly field at 15:00 UTC for each MODSCAG calendar date
- Comparison grid: regular 0.1° latitude/longitude CDS distribution grid; the
  catalogue describes the underlying native resolution as 9 km
- ERA5-Land replays the ERA5 land component with ERA5 atmospheric forcing and
  lapse-rate correction. Observations influence it indirectly through that
  forcing rather than through direct land-state assimilation in ERA5-Land.
- DOI: [10.24381/cds.e2161bac](https://doi.org/10.24381/cds.e2161bac)

Official sources:

- [ERA5-Land hourly catalogue](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land)
- [ERA5-Land documentation](https://confluence.ecmwf.int/display/CKB/ERA5-Land%3A+data+documentation)

## CDS request contract

The current official catalogue schemas accept monthly requests containing:

```text
variable = snow_cover
year, month, day
time = 15:00
area = [41, -109, 37, -104]
data_format = netcdf
download_format = unarchived
```

ERA5 additionally requires `product_type = reanalysis`; ERA5-Land does not
expose that request field. The code preserves this distinction rather than
assuming both CDS datasets have the same form schema.

CDS access requires a personal access token and prior acceptance of the dataset
licences. Credentials are read by `cdsapi` from `~/.cdsapirc` or `CDSAPI_KEY`.
See the official [CDS API setup guide](https://cds.climate.copernicus.eu/how-to-api).

## Comparison decisions

The established snow-hydrology method remains fixed:

1. Pair by calendar date at 15Z.
2. Aggregate equal-area MODSCAG pixel centers independently to each model's CDS
   product grid; never interpolate a model down to 500 m.
3. Include valid gap-filled STC-MODSCAG values, retain
   `days_without_observation == 0` as a direct-observation diagnostic, and mask
   a cell-day below 80% valid fine-pixel support.
4. Weight pooled errors by the number of valid MODSCAG pixels.
5. Define error as model minus MODSCAG.
6. Persist only additive monthly statistics and final CSVs. Monthly model
   NetCDF subsets and daily MODSCAG granules remain task-local temporary files.

ERA5 and ERA5-Land are evaluated on different target grids. Their per-cell CSVs
therefore must not be joined by row number or treated as spatially identical.
The center-selection rectangle gives 357 ERA5 cells (17 × 21) and 2,091
ERA5-Land cells (41 × 51). Because the historical MODSCAG archive lacks tile
`h10v05`, the theoretical archive footprint cannot meet 80% support for three
ERA5 cells and twelve ERA5-Land cells at the southeastern edge; these remain
explicitly unpaired rather than being extrapolated.

## Timing qualification relative to MERRA-2

The existing MERRA-2 comparison uses time index 15 from an hourly averaged
product: the 15:00–16:00 UTC mean stamped 15:30 UTC. The ERA products use their
hourly field at exactly 15:00 UTC. This is the closest implementation of the
requested daily 15Z match, but the temporal operators are not identical and
must remain visible in metadata and interpretation.
