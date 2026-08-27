# NARR snow-cover product research

## Reviewed source

- Product: NCEP North American Regional Reanalysis (NARR), distributed by
  NOAA Physical Sciences Laboratory.
- Access: public NOAA PSL THREDDS/OPeNDAP annual NetCDF files at
  `Datasets/NARR/monolevel/snowc.YYYY.nc`.
- Field: `snowc`, described by NOAA as 3-hourly snow cover at the surface.
- Units and range: dimensionless fraction, valid range 0–1.
- Statistic: individual observation/analysis field, not a daily or monthly
  average.
- Time: eight analyses daily at 00, 03, 06, 09, 12, 15, 18, and 21 UTC. The
  comparison therefore uses the exact 15:00 UTC field on each MODSCAG date.

Authoritative references:

- [NOAA PSL NARR product and variable inventory](https://psl.noaa.gov/data/gridded/data.narr.html)
- [NOAA PSL NARR Lambert-grid documentation](https://psl.noaa.gov/data/narr/format.html)
- [NOAA/NCEI NARR dataset record](https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ncdc:C00618)
- [NOAA/NCEI NARR data documentation](https://www.ncei.noaa.gov/sites/default/files/2022-06/ncdc-narrdsi-6175-final.pdf)

## Grid contract

NARR output is distributed on AWIPS Grid 221: a 349 × 277 Lambert conformal
grid with approximately 32 km spacing. The NOAA PSL NetCDF coordinate contract
is:

- projection origin latitude: 50°N;
- central meridian: 107°W;
- standard parallels: 50°N and 50°N;
- false easting: 5,632,642.22547 m;
- false northing: 4,612,545.65137 m;
- spherical Earth radius: 6,371,200 m; and
- stored x/y spacing: 32,463 m.

The implementation reconstructs the published x/y grid, transforms its cell
centers to longitude/latitude, and selects centers within 109–104°W and
37–41°N. This yields 185 native NARR cells. MODSCAG pixel centers are
transformed into the same Lambert projection and binned by the native NARR cell
edges. NARR is never interpolated down to MODIS resolution.

## Scientific continuity

The comparison preserves the existing contract:

- water years 2010–2023;
- daily STC-MODSCAG v1 `snow_fraction`;
- 80% daily MODSCAG support;
- valid-MODSCAG-pixel weighting;
- error sign NARR minus MODSCAG; and
- monthly sufficient-statistic checkpoints with no retained raw NARR or MODIS
  files.

NARR differs intentionally from MERRA-2 timing: NARR supplies an instantaneous
15:00 UTC analysis, while the chosen MERRA-2 value is a 15:00–16:00 UTC mean.
The product-specific time description is retained in checkpoint metadata.
